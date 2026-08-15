"""不死途（Ashveil）技能模块。char_id=1504，巡猎 / 雷 / 5 星。

机制：
- 【饲饵】：敌方单体标记，仅最新目标生效（施加新饲饵时旧饲饵失效）。
  场上存在饲饵时，敌方全体防御力降低（战技 #4）。
- 【充能】：初始 #1（2）点、上限 #2（3）点；终结技获得 #2（3）点；
  天赋追加攻击消耗 #3（1）点。
- 【婪酣】：上限 #6（12）层；天赋追加攻击获得 #5（2）层；
  终结技强化追加攻击每消耗 #3（4）层额外造成 1 段伤害。
- 天赋追加攻击：饲饵受到我方其他目标攻击后触发——
  回能量 #7（8）、消耗 1 点充能对饲饵追加攻击（#4 倍率）、获得 2 层婪酣。

技能（nanoka ID，参数经 skill.params 读取，#N → params[N-1]）：
- 150401 普攻「利爪，授以礼仪」
- 150402 战技「鞭哨，逐尽恶兽」：#1 首段倍率（1→2）、#3 额外段倍率（0.5→1）、
  #4 敌方全体减防（0.2→0.4）、#5 额外段命中时回战技点（1）
- 150403 终结技「飨宴，自始无终」：#1 首段倍率（2→4）、#2 获得充能（3）、
  #3 婪酣消耗层数（4）、#4 强化追击/额外段倍率（1→2）
- 150404 天赋「宿怨，切齿奉还」：#1 初始充能（2）、#2 充能上限（3）、
  #3 追击消耗充能（1）、#4 追击倍率（1→2）、#5 获得婪酣（2）、
  #6 婪酣上限（12）、#7 回能量（8）
- 150407 秘技：战前机制，不建模

未建模（TODO，因模拟器暂无敌人 HP/死亡模型）：
- 终结技强化追击"致命攻击转移"（击杀饲饵后转移到新饲饵继续打）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..damage import DamageType
from ..skill import SkillEffect, SkillType, get_skill_by_type
from . import register
from .base import CharacterModule, module_params

if TYPE_CHECKING:
    from ..simulator import ActionLog, BattleSimulator, CharacterUnit, EnemyState, PlayerAction
    from ..skill import Skill

# 技能 ID 常量（nanoka）
SKILL_NORMAL = "150401"
SKILL_SKILL = "150402"
SKILL_ULTRA = "150403"
SKILL_TALENT = "150404"
SKILL_TECHNIQUE = "150407"  # 秘技（注意：150406 迷宫普攻同为 Technique 类型但无参数）

ELEMENT = "Thunder"  # 雷属性


@register
class AshveilModule(CharacterModule):
    """不死途技能模块。"""

    CHAR_ID = "1504"

    # 充能指示样式（UI 头像徽章）：圆点模式（紫色实心/空心圆点）
    CHARGE_STYLE = "dots"
    CHARGE_MAX = 3  # 追击充能上限（天赋 #2）

    # ── 状态（纯数据，deepcopy 安全）──────────────────────
    unit_id: str = ""        # 所属角色单位 ID（on_battle_start 时记录）
    bait_unit_id: str = ""   # 当前饲饵（仅最新目标生效）
    charge: float = 2        # 充能（战斗开始时按天赋 #1 重置）
    greed: int = 0           # 婪酣层数
    # 本模块对敌方 def_reduce 的贡献值（增量式累加/撤销，
    # 与千冶【煞火缠身】等其余模块的减防贡献共存）
    def_reduce_contribution: float = 0.0
    # 已处理天赋的受击行动令牌集合（按行动计：一次攻击行动的多段命中
    # 只触发一次"固定回 8 能量 + 追击判定"，避免战技 5 段回 5 次）。
    # 用集合而非单值：连锁触发（追击/追加战技 begin_new_action）后令牌
    # 交替（T/T+1/T+2），单值无法去重"较早令牌"的后续命中（同千冶）。
    _proc_tokens: set[int] = set()

    # ── 事件钩子 ─────────────────────────────────────────

    def on_battle_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        self.unit_id = char.unit_id
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        self.charge = module_params(talent, 1, 2)  # 初始充能 #1
        self.bait_unit_id = ""
        self.greed = 0
        self._proc_tokens = set()
        # 战斗开始：当前场上生命值最低的敌方单体成为饲饵
        lowest = self._lowest_hp_enemy(sim)
        if lowest is not None:
            self._set_bait(sim, char, lowest)
        # 秘技进战效果：对敌方全体造成攻击力 #2 倍率雷伤，并获 #3 点充能
        self._technique_on_battle_start(sim, char)

    def on_skill_cast(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        if target is None:
            return
        skill_id = str(skill.id)

        if skill_id == SKILL_SKILL:
            self._on_skill(sim, char, target, log)
        elif skill_id == SKILL_ULTRA:
            # 终结技：先标记饲饵（首段伤害即可享受减防）
            self._set_bait(sim, char, target)

    def on_attack_hit(
        self,
        sim: BattleSimulator,
        attacker: CharacterUnit,
        skill: Skill | None,
        target: EnemyState,
        effect: SkillEffect,
        damage: float,
        log: ActionLog | None,
        action_token: int,
    ) -> None:
        """天赋：饲饵被我方其他目标攻击后触发追加攻击。

        按行动计（一次攻击行动的多段命中只触发一次天赋效果），
        用分发时冻结的 action_token 去重（同千冶，避免分发循环内
        begin_new_action 修改全局令牌导致的误判）。
        """
        if not self.bait_unit_id or target.unit_id != self.bait_unit_id:
            return
        # 防自激：不死途自己的攻击不触发（含其追加攻击自身，避免链式递归）
        if attacker.unit_id == self.unit_id:
            return
        # 行动级去重：战技 5 段命中只算一次"受到攻击"（用集合，乱序令牌也能正确去重）
        if action_token in self._proc_tokens:
            return
        self._proc_tokens.add(action_token)
        char = next((c for c in sim.characters if c.unit_id == self.unit_id), None)
        if char is None:
            return
        self._talent_follow_up(sim, char)

    def on_skill_end(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """终结技：获得充能 + 强化天赋追加攻击链。"""
        if str(skill.id) != SKILL_ULTRA or target is None:
            return
        ultra = skill
        talent = get_skill_by_type(char.skills, SkillType.TALENT)

        # 获得充能（钳制到上限）
        charge_max = module_params(talent, 2, 3)
        self.charge = min(self.charge + module_params(ultra, 2, 3), charge_max)

        # 终结技后的追击链视为一次独立攻击行动（开启新行动令牌）：
        # 终结技本体命中算 1 次攻击，强化追击 + 婪酣追击整体算 1 次攻击
        sim.begin_new_action()

        # 强化天赋追加攻击（不消耗充能），倍率 = 终结技 #4
        # 基础的一次强化追击有追加攻击回能（天赋 sp_base=5）
        mult = module_params(ultra, 4, 1.0)
        follow_up_recover = talent.energy_recover
        self._follow_up_attack(
            sim, char, target, mult, notes="强化追击", energy_recover=follow_up_recover
        )

        # 每消耗 #3 层婪酣额外 1 段（#4 倍率）
        # 婪酣额外攻击不提供追加攻击回能（用户实测校准）
        greed_cost = int(module_params(ultra, 3, 4))
        while self.greed >= greed_cost:
            self.greed -= greed_cost
            self._follow_up_attack(sim, char, target, mult, notes="婪酣追击", energy_recover=0)
        # TODO: 致命攻击转移未建模（需敌人 HP/死亡模型）：
        #   追击击杀饲饵后应转移到新饲饵继续打，直至婪酣 < #3 层。

    def on_enemy_dead(self, sim: BattleSimulator, enemy: EnemyState) -> None:
        """饲饵死亡：转移到当前生命值最低的存活敌人（无存活则清除饲饵与减防）。"""
        if enemy.unit_id != self.bait_unit_id:
            return
        char = next((c for c in sim.characters if c.unit_id == self.unit_id), None)
        if char is None:
            return
        self.bait_unit_id = ""
        lowest = self._lowest_hp_enemy(sim)
        if lowest is not None:
            self._set_bait(sim, char, lowest)
        else:
            self._update_def_reduce(sim, char)

    def enemy_buffs(
        self,
        sim: BattleSimulator,
        enemy: EnemyState,
    ) -> list[tuple[str, str]]:
        """饲饵 debuff：减防对所有敌人生效，饲饵标记仅当前饲饵目标显示。"""
        items: list[tuple[str, str]] = []
        # 场上存在饲饵时，敌方全体减防（对所有敌人生效）
        if self.bait_unit_id and self.def_reduce_contribution:
            items.append((
                "饲饵·防御降低",
                f"敌方全体防御降低 {self.def_reduce_contribution * 100:.1f}%",
            ))
        # 仅当前饲饵目标显示标记
        if enemy.unit_id == self.bait_unit_id:
            items.append(("饲饵", "当前为不死途的饲饵目标"))
        return items

    # ── 私有辅助 ─────────────────────────────────────────

    def _technique_on_battle_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """秘技（150407）进战效果：对敌方全体造成攻击力 #2 倍率雷伤，获得 #3 点充能。

        按技能 ID 精确查找：真实数据中 150406（迷宫普攻）同为 Technique 类型
        但 params 为空，get_skill_by_type 会误取到它。
        """
        technique = char.skills.get(SKILL_TECHNIQUE)
        if technique is None:
            return
        params = technique.params
        if len(params) < 3:
            return
        multiplier = params[1]   # #2 伤害倍率（100%）
        charge_gain = int(params[2])  # #3 获得充能

        # 获得充能（钳制到天赋上限）
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        charge_max = module_params(talent, 2, 3)
        self.charge = min(self.charge + charge_gain, charge_max)

        # 对敌方全体造成伤害（技能类型=秘技）
        for enemy in sim.enemies:
            log = sim.make_follow_up_log(char, enemy, notes="秘技进战", action_type="technique")
            effect = SkillEffect(
                damage_type=DamageType.NORMAL,
                multiplier=multiplier,
                toughness_damage=0,
                element=ELEMENT,
            )
            sim.deal_damage(char, enemy, effect, skill_type=SkillType.TECHNIQUE, log=log)
            log.energy_after = char.energy

    def _on_skill(self, sim: BattleSimulator, char: CharacterUnit, target: EnemyState, log: ActionLog) -> None:
        """战技处理：饲饵标记 / 额外伤害 / 回 SP / 减防。"""
        skill = get_skill_by_type(char.skills, SkillType.SKILL)
        if skill is None:
            return

        if self.bait_unit_id == target.unit_id:
            # 目标已是饲饵：额外伤害 + 恢复战技点
            extra_mult = module_params(skill, 3, 0.0)
            if extra_mult:
                effect = SkillEffect(
                    damage_type=DamageType.NORMAL,
                    multiplier=extra_mult,
                    toughness_damage=0,
                    element=ELEMENT,
                )
                sim.deal_damage(char, target, effect, skill_type=SkillType.SKILL, log=log)
            sp_refund = int(module_params(skill, 5, 0))
            if sp_refund:
                sim.sp.recover(sp_refund)
                log.sp_after = sim.sp.current
        elif not self.bait_unit_id:
            # 场上无饲饵：立即使当前场上生命值最低的敌方单体成为饲饵
            lowest = self._lowest_hp_enemy(sim)
            if lowest is not None:
                self._set_bait(sim, char, lowest)
        # 已有饲饵且目标不同：战技仍使目标成为新饲饵（仅最新目标生效）
        else:
            self._set_bait(sim, char, target)

    def _set_bait(self, sim: BattleSimulator, char: CharacterUnit, target: EnemyState) -> None:
        """置饲饵（仅最新目标生效）并更新减防。"""
        self.bait_unit_id = target.unit_id
        self._update_def_reduce(sim, char)

    def _update_def_reduce(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """场上存在饲饵 → 敌方全体减防 = 战技 #4；否则撤销本模块贡献。

        增量式：只应用本模块贡献值的变化（diff），
        与其他模块的减防（如千冶【煞火缠身】）共存。
        """
        rate = 0.0
        if self.bait_unit_id:
            skill = get_skill_by_type(char.skills, SkillType.SKILL)
            rate = module_params(skill, 4, 0.0)
        diff = rate - self.def_reduce_contribution
        self.def_reduce_contribution = rate
        for enemy in sim.enemies:
            enemy.def_reduce += diff

    def _talent_follow_up(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """天赋（受到攻击后）：固定回能 → 充能足够时追击（独立行动）。

        由 on_attack_hit 按行动去重后调用（战技 5 段命中只触发一次）。
        固定回能 #7 与充能无关（充能不足时追击不触发，回能照常）。
        """
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        if talent is None:
            return
        # 固定回能量（#7，8 点）：描述带"固定"字样，不受能量恢复效率影响
        sim.recover_energy(char, module_params(talent, 7, 0), fixed=True)
        # 充能不足则不追击（回能 8 已发生；追击是"额外施放"）
        charge_cost = module_params(talent, 3, 1)
        if self.charge < charge_cost:
            return
        self.charge -= charge_cost
        # 天赋追击是独立攻击行动（与触发它的那次攻击分开计数）
        sim.begin_new_action()
        # 追击伤害（#4 倍率）；天赋追加攻击有追加攻击回能（天赋 sp_base=5）
        mult = module_params(talent, 4, 0.0)
        if mult:
            self._follow_up_attack(
                sim, char, self._bait(sim), mult,
                notes="天赋追击", energy_recover=talent.energy_recover,
            )
        # 获得婪酣（钳制上限）
        greed_max = int(module_params(talent, 6, 12))
        self.greed = min(self.greed + int(module_params(talent, 5, 2)), greed_max)

    def _bait(self, sim: BattleSimulator) -> EnemyState | None:
        """当前饲饵敌人实例。"""
        for enemy in sim.enemies:
            if enemy.unit_id == self.bait_unit_id:
                return enemy
        return None

    def _lowest_hp_enemy(self, sim: BattleSimulator) -> EnemyState | None:
        """当前场上生命值最低的敌方单体（无敌人返回 None）。"""
        if not sim.enemies:
            return None
        return min(sim.enemies, key=lambda e: e.current_hp)

    def _follow_up_attack(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        target: EnemyState | None,
        multiplier: float,
        notes: str,
        energy_recover: float = 0.0,
    ) -> None:
        """打一段追加攻击（独立日志，不推进队列）。

        energy_recover: 本次追击的能量回复（追加攻击回能 5；婪酣额外段为 0）。
        """
        if target is None or multiplier <= 0:
            return
        log = sim.make_follow_up_log(char, target, notes=notes)
        effect = SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=multiplier,
            # TODO: 追加攻击削韧数据待勘探（天赋追击 15，强化追击未单独给出）
            toughness_damage=0,
            element=ELEMENT,
        )
        sim.deal_damage(char, target, effect, skill_type=SkillType.FOLLOW_UP, log=log)
        # 追加攻击回能（走能量恢复效率乘区）
        if energy_recover:
            sim.recover_energy(char, energy_recover)
        # 同步日志快照（回能/SP 变化发生在打伤害前后）
        log.energy_after = char.energy
        log.sp_after = sim.sp.current
