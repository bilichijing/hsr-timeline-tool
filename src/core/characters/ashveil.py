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
  #3 婪酣消耗层数（4）、#4 强化追打/额外段倍率（1→2）
- 150404 天赋「宿怨，切齿奉还」：#1 初始充能（2）、#2 充能上限（3）、
  #3 追打消耗充能（1）、#4 追打倍率（1→2）、#5 获得婪酣（2）、
  #6 婪酣上限（12）、#7 回能量（8）
- 150407 秘技：战前机制，不建模

未建模（TODO，因模拟器暂无敌人 HP/死亡模型）：
- 终结技强化追打"致命攻击转移"（击杀饲饵后转移到新饲饵继续打）
- 战技"当前生命最低的敌方单体"选取（暂用 enemies[0] 占位）
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

ELEMENT = "Thunder"  # 雷属性


@register
class AshveilModule(CharacterModule):
    """不死途技能模块。"""

    CHAR_ID = "1504"

    # ── 状态（纯数据，deepcopy 安全）──────────────────────
    unit_id: str = ""        # 所属角色单位 ID（on_battle_start 时记录）
    bait_unit_id: str = ""   # 当前饲饵（仅最新目标生效）
    charge: float = 2        # 充能（战斗开始时按天赋 #1 重置）
    greed: int = 0           # 婪酣层数

    # ── 事件钩子 ─────────────────────────────────────────

    def on_battle_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        self.unit_id = char.unit_id
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        self.charge = module_params(talent, 1, 2)  # 初始充能 #1
        self.bait_unit_id = ""
        self.greed = 0
        self._update_def_reduce(sim, char)

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
    ) -> None:
        """天赋：饲饵被我方其他目标攻击后触发追加攻击。"""
        if not self.bait_unit_id or target.unit_id != self.bait_unit_id:
            return
        # 防自激：不死途自己的攻击不触发（含其追加攻击自身，避免链式递归）
        if attacker.unit_id == self.unit_id:
            return
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

        # 强化天赋追加攻击（不消耗充能），倍率 = 终结技 #4
        mult = module_params(ultra, 4, 1.0)
        self._follow_up_attack(sim, char, target, mult, notes="强化追打")

        # 每消耗 #3 层婪酣额外 1 段（#4 倍率）
        greed_cost = int(module_params(ultra, 3, 4))
        while self.greed >= greed_cost:
            self.greed -= greed_cost
            self._follow_up_attack(sim, char, target, mult, notes="婪酣追打")
        # TODO: 致命攻击转移未建模（需敌人 HP/死亡模型）：
        #   追打击杀饲饵后应转移到新饲饵继续打，直至婪酣 < #3 层。

    # ── 私有辅助 ─────────────────────────────────────────

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
            # 场上无饲饵：使目标成为饲饵
            # TODO: 描述为"当前场上生命值最低的敌方单体"，无 HP 模型暂用施法目标占位
            self._set_bait(sim, char, target)
        # 已有饲饵且目标不同：战技仍使目标成为新饲饵（仅最新目标生效）
        else:
            self._set_bait(sim, char, target)

    def _set_bait(self, sim: BattleSimulator, char: CharacterUnit, target: EnemyState) -> None:
        """置饲饵（仅最新目标生效）并更新减防。"""
        self.bait_unit_id = target.unit_id
        self._update_def_reduce(sim, char)

    def _update_def_reduce(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """场上存在饲饵 → 敌方全体减防 = 战技 #4；否则清零。"""
        rate = 0.0
        if self.bait_unit_id:
            skill = get_skill_by_type(char.skills, SkillType.SKILL)
            rate = module_params(skill, 4, 0.0)
        for enemy in sim.enemies:
            enemy.def_reduce = rate

    def _talent_follow_up(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """天赋追加攻击：回能 → 消耗充能追打 → 获得婪酣。"""
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        if talent is None:
            return
        # 固定回能量（#7）
        sim.recover_energy(char, module_params(talent, 7, 0))
        # 充能不足则不追打
        charge_cost = module_params(talent, 3, 1)
        if self.charge < charge_cost:
            return
        self.charge -= charge_cost
        # 追打伤害（#4 倍率）
        mult = module_params(talent, 4, 0.0)
        if mult:
            self._follow_up_attack(sim, char, self._bait(sim), mult, notes="天赋追打")
        # 获得婪酣（钳制上限）
        greed_max = int(module_params(talent, 6, 12))
        self.greed = min(self.greed + int(module_params(talent, 5, 2)), greed_max)

    def _bait(self, sim: BattleSimulator) -> EnemyState | None:
        """当前饲饵敌人实例。"""
        for enemy in sim.enemies:
            if enemy.unit_id == self.bait_unit_id:
                return enemy
        return None

    def _follow_up_attack(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        target: EnemyState | None,
        multiplier: float,
        notes: str,
    ) -> None:
        """打一段追加攻击（独立日志，不推进队列）。"""
        if target is None or multiplier <= 0:
            return
        log = sim.make_follow_up_log(char, target, notes=notes)
        effect = SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=multiplier,
            # TODO: 追加攻击削韧数据待勘探（天赋追打 15，强化追打未单独给出）
            toughness_damage=0,
            element=ELEMENT,
        )
        sim.deal_damage(char, target, effect, skill_type=SkillType.FOLLOW_UP, log=log)
        # 同步日志快照（回能/SP 变化发生在打伤害前后）
        log.energy_after = char.energy
        log.sp_after = sim.sp.current
