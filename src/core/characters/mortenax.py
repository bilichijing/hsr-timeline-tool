"""千冶•刃（Mortenax Blade）技能模块。char_id=1507，虚无 / 火 / 5 星。

机制：
- 伤害全部基于【生命上限】倍率（base_stat="hp"）。
- 战技/终结技消耗生命：不足时降至 1 点；生命 ≤1 时无法施放战技。
- 【无量忿怒】（结界）：终结技（150703）施放后展开——
  暴击率 +20%（#2）、暴伤 +30%（#3）、普攻强化（150708，#1 倍率）、
  终结技替换为【千冶铸一，万劫烬灭】（150714，#1 倍率，耗能 160）。
  行动序列出现 #5（70）速倒计时，倒计时回合开始时结界解除。
- 【煞火缠身】：敌方 debuff——防御降低 #7（20%）、受伤提高 #4（30%），
  持续 #8（2）个敌方回合；终结技施加全体，天赋命中施加目标。
- 天赋【因果尽偿】：结界期间我方每次攻击（按行动计，含自身）后，
  目标煞火缠身 + 充能 +1；充能达 #1（9）点且生命 >1 时消耗充能、
  恢复 #2（15）点能量、额外施放 1 次战技（视为追加攻击）。
  充能不足或生命 ≤1 无法施放时，充能保留（封顶 #1）。
- 致命攻击免死（解除结界并回复 #6 生命）：无我方受击模型，TODO。

技能（nanoka ID，参数经 skill.params 读取，#N → params[N-1]）：
- 150701 普攻「残锋，掠尽」：#1 25% 生命上限
- 150702 战技「刃下，归葬」：#1 36% 全体、#2 4 次额外、#3 12% 每次、
  #4 10% 生命消耗；不耗战技点；非无量忿怒或生命 ≤1 无法施放
- 150703 终结技「骸骨当炉，血肉即薪」：#1 20% 生命消耗开结界、#2 暴击率、
  #3 暴伤、#4 煞火缠身易伤、#5 倒计时速度 70、#6 免死回复、
  #7 煞火缠身减防、#8 持续回合 2（本体无伤害，effects 需清空）
- 150704 天赋「因果尽偿」：#1 充能需求 9、#2 回能量 15
- 150707 秘技「十方无赦」：嘲讽 + 自身减伤，无受击模型，TODO
- 150708 强化普攻「淬锋，断魄」：#1 50% 生命上限（无量忿怒下普攻）
- 150709 强化战技「刃下，归葬」：desc 为空，效果同 150702（仅解锁）
- 150714 强化终结技「千冶铸一，万劫烬灭」：#1 210% 生命上限全体

未建模（TODO，无我方受击模型）：
- 致命攻击免死（结界内受致命伤：解除结界、回复 50% 生命）
- 普攻/秘技的嘲讽、秘技自身减伤 90%
- 战技额外段与强化终结技的削韧（show_stance_list 第二项语义待勘探）
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from ..damage import DamageType
from ..skill import SkillEffect, SkillType, get_skill_by_type
from . import register
from .base import CharacterModule, module_params

if TYPE_CHECKING:
    from ..simulator import ActionLog, BattleSimulator, CharacterUnit, EnemyState, PlayerAction
    from ..skill import Skill

# 技能 ID 常量（nanoka）
SKILL_NORMAL = "150701"
SKILL_SKILL = "150702"
SKILL_ULTRA_OPEN = "150703"  # 终结技：开结界
SKILL_TALENT = "150704"
SKILL_TECHNIQUE = "150707"  # 秘技（150706 迷宫普攻同为 Technique 类型但无效果）
SKILL_NORMAL_ENH = "150708"  # 强化普攻（无量忿怒）
SKILL_ULTRA_ENH = "150714"  # 强化终结技（无量忿怒）

ELEMENT = "Fire"  # 火属性

# 【煞火缠身】兜底常量（正常从终结技 #7/#4/#8 读取，数据缺失时使用）
BLAZE_DEF_REDUCE = 0.20
BLAZE_VULNERABILITY = 0.30
BLAZE_TURNS = 2

# 【百炼骨】额外能力：战斗开始/结界解除时能量不足该比例则恢复至该比例
# （正常从行迹额外能力 param_list[0] 读取，数据缺失时使用）
TRACE_ENERGY_RATIO = 0.75
TRACE_EXTRA_NAME = "百炼骨"


@register
class MortenaxModule(CharacterModule):
    """千冶•刃技能模块。"""

    CHAR_ID = "1507"

    # 充能指示样式（UI 头像徽章）：文字模式显示"当前/上限"（红色）
    CHARGE_STYLE = "text"
    CHARGE_MAX = 9  # 天赋充能上限（天赋 #1）

    # ── 状态（纯数据，deepcopy 安全）──────────────────────
    unit_id: str = ""            # 所属角色单位 ID（on_battle_start 时记录）
    rage: bool = False           # 无量忿怒（结界）状态
    charge: float = 0.0          # 天赋充能（0-9，结界期间攻击累计）
    countdown_unit_id: str = ""  # 无量忿怒倒计时单位 ID（行动时结界解除）
    # 【煞火缠身】状态：{enemy_unit_id: (剩余敌方回合, 减防贡献, 易伤贡献)}
    blaze: dict[str, tuple[float, float, float]] = {}
    # 已计充能的行动令牌集合（同一次行动的多次命中只计 1 点充能）。
    # 用集合而非单值：连锁触发（追击/追加战技 begin_new_action）后令牌交替
    # （T、T+1、T+2），单值无法去重"较早令牌"的后续命中（会重复计费）。
    _charged_tokens: set[int] = set()
    # 【百炼骨】能量恢复比例（on_battle_start 时从行迹额外能力读取）
    energy_ratio: float = TRACE_ENERGY_RATIO

    # ── 事件钩子 ─────────────────────────────────────────

    def on_battle_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        self.unit_id = char.unit_id
        self.rage = False
        self.charge = 0.0
        self.countdown_unit_id = ""
        self.blaze = {}
        self._charged_tokens = set()
        # 【百炼骨】额外能力：战斗开始时若能量不足 75% 则立刻恢复至 75%
        self._read_trace_params(char)
        self._regen_energy_to_ratio(sim, char)

    def on_resolve_skill(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill_type: SkillType,
        skill: Skill,
    ) -> Skill | None:
        """技能解析：战技限制 + 无量忿怒下普攻/终结技切换强化版。

        仅对本角色生效（队友的技能解析由各队友模块负责，本模块不拦截）。
        """
        if char.unit_id != self.unit_id:
            return skill
        if skill_type == SkillType.SKILL:
            # 未处于无量忿怒或生命 ≤1 时无法施放战技
            if not self._can_cast_skill(char):
                return None
            return skill
        if self.rage:
            # 无量忿怒：普攻强化（150708）、终结技替换（150714）
            if skill_type == SkillType.NORMAL and SKILL_NORMAL_ENH in char.skills:
                return char.skills[SKILL_NORMAL_ENH]
            if skill_type == SkillType.ULTRA and SKILL_ULTRA_ENH in char.skills:
                return char.skills[SKILL_ULTRA_ENH]
        return skill

    def on_skill_cast(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        skill_id = str(skill.id)
        if skill_id == SKILL_ULTRA_OPEN:
            self._on_ultra_open(sim, char, skill, log)
        elif skill_id in (SKILL_NORMAL, SKILL_NORMAL_ENH):
            # 单体生命倍率：修正 parse 默认的攻击力基础属性
            if skill.effects:
                skill.effects[0].base_stat = "hp"
        elif skill_id == SKILL_SKILL:
            # 战技：全体主伤害 + 随机单体额外段（多敌人），延迟到 on_skill_end 结算
            # （清空 effects，避免 _resolve_skill 单目标误结算主伤害）
            skill.effects = []
            self._consume_hp(char, module_params(skill, 4, 0.1))
        elif skill_id == SKILL_ULTRA_ENH:
            # 强化终结技：全体生命上限伤害（多敌人），延迟到 on_skill_end 结算
            skill.effects = []

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
        """天赋：结界期间我方每次攻击（按行动计，含自身）后触发。

        - 【煞火缠身】：每个命中的目标都施加/刷新（全体攻击命中谁就给谁上）。
        - 充能按行动计：一次行动（含终结技后的追击链、技能多段/多目标伤害）
          只计 1 点充能；模块主动开启的新行动（begin_new_action）独立计数
          （如千冶天赋额外施放的战技）。
        注意：用分发时冻结的 action_token（非 sim.action_token）——
        分发循环内其他模块 begin_new_action 会修改全局令牌，导致本体命中
        被误判为与追击同一行动。
        """
        if not self.rage:
            return
        char = next((c for c in sim.characters if c.unit_id == self.unit_id), None)
        if char is None:
            return
        # 每个命中目标都陷入【煞火缠身】（全体攻击逐目标施加/刷新）
        self._apply_blaze(sim, char, target)
        # 充能按行动计（一次行动只计 1 点）
        if action_token in self._charged_tokens:
            return
        self._charged_tokens.add(action_token)
        # 充能 +1（封顶需求值；无法施放战技时保留）
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        need = int(module_params(talent, 1, 9))
        self.charge = min(self.charge + 1, need)
        self._talent_proc(sim, char)

    def on_skill_end(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """技能结算后：战技（全体+随机）与强化终结技（全体）的伤害。

        放在 on_skill_end（主日志已入列、首段伤害已结算）而非 on_skill_cast，
        保证日志顺序与连锁顺序正确：战技 → 追击 → 追加战技。
        """
        skill_id = str(skill.id)
        if skill_id == SKILL_SKILL:
            self._deal_skill_skill(sim, char, skill, log)
        elif skill_id == SKILL_ULTRA_ENH:
            self._deal_ultra_enh(sim, char, skill, log)

    def on_countdown(self, sim: BattleSimulator, char: CharacterUnit, log: ActionLog) -> None:
        """倒计时回合开始：结界解除、退出无量忿怒。"""
        self._exit_rage(sim, char)

    def on_enemy_act(
        self,
        sim: BattleSimulator,
        enemy: EnemyState,
        log: ActionLog,
    ) -> None:
        """敌方回合计时：【煞火缠身】剩余回合 -1，到期撤销减防/易伤贡献。"""
        if enemy.unit_id not in self.blaze:
            return
        turns_left, def_part, vuln_part = self.blaze[enemy.unit_id]
        turns_left -= 1
        if turns_left <= 0:
            del self.blaze[enemy.unit_id]
            enemy.def_reduce -= def_part
            enemy.vulnerability -= vuln_part
        else:
            self.blaze[enemy.unit_id] = (turns_left, def_part, vuln_part)

    def on_enemy_dead(self, sim: BattleSimulator, enemy: EnemyState) -> None:
        """煞火缠身目标死亡：移除其状态记录（敌对象已离场，无需撤销贡献）。"""
        self.blaze.pop(enemy.unit_id, None)

    def enemy_buffs(
        self,
        sim: BattleSimulator,
        enemy: EnemyState,
    ) -> list[tuple[str, str]]:
        """煞火缠身 debuff：仅身中该 debuff 的敌人显示。"""
        if enemy.unit_id not in self.blaze:
            return []
        turns_left, def_part, vuln_part = self.blaze[enemy.unit_id]
        desc = (
            f"防御降低 {def_part * 100:.1f}%、易伤 {vuln_part * 100:.1f}%，"
            f"剩余 {turns_left:.0f} 个敌方回合"
        )
        return [("煞火缠身", desc)]

    # ── 私有辅助 ─────────────────────────────────────────

    def skill_deny_reason(self, sim: BattleSimulator, char: CharacterUnit) -> str | None:
        """战技被拒绝的原因（None=可施放）。UI 弹窗提示用。"""
        if not self.rage:
            return "未开启结界，无法施放战技"
        if char.current_hp <= 1:
            return "当前生命值 ≤1，无法施放战技"
        return None

    def _read_trace_params(self, char: CharacterUnit) -> None:
        """读取【百炼骨】额外能力参数（param_list[0] = 能量恢复比例）。"""
        ratio = TRACE_ENERGY_RATIO
        for group in char.skill_trees_raw.values():
            if not isinstance(group, dict):
                continue
            for point in group.values():
                if not isinstance(point, dict):
                    continue
                if (
                    point.get("point_type") == 3
                    and point.get("point_name") == TRACE_EXTRA_NAME
                    and point.get("param_list")
                ):
                    ratio = float(point["param_list"][0])
                    break
        self.energy_ratio = ratio

    def _regen_energy_to_ratio(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """【百炼骨】：能量不足该比例（默认 75%）则立刻恢复至该比例。"""
        target = char.base_stats.energy_max * self.energy_ratio
        if char.energy < target:
            char.energy = target

    def _can_cast_skill(self, char: CharacterUnit) -> bool:
        """战技可施放：处于无量忿怒且当前生命 >1。"""
        return self.rage and char.current_hp > 1

    def _consume_hp(self, char: CharacterUnit, pct: float) -> None:
        """消耗生命上限 pct 的生命（不足时降至 1 点）。"""
        cost = char.final_stats().hp * pct
        char.current_hp = max(1.0, char.current_hp - cost)

    def _on_ultra_open(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        log: ActionLog,
    ) -> None:
        """终结技 150703：本体无伤害（#1 是生命消耗而非倍率），清空误解析 effects。

        结界展开：全体煞火缠身 → 消耗生命 → 无量忿怒（属性 buff + 倒计时）。
        """
        skill.effects = []
        if self.rage:
            # 无量忿怒下终结技已被替换为 150714，正常流程不会走到这里；防御性返回
            return

        # 全体【煞火缠身】
        for enemy in sim.enemies:
            self._apply_blaze(sim, char, enemy)
        # 消耗生命（不足降至 1）
        self._consume_hp(char, module_params(skill, 1, 0.2))

        # 无量忿怒：暴击率 #2、暴伤 #3
        self.rage = True
        char.buff_mgr.add(Buff(
            id=f"rage_crit_rate_{char.unit_id}",
            name="无量忿怒",
            stat="crit_rate",
            value=module_params(skill, 2, 0.2),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=char.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        char.buff_mgr.add(Buff(
            id=f"rage_crit_dmg_{char.unit_id}",
            name="无量忿怒",
            stat="crit_dmg",
            value=module_params(skill, 3, 0.3),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=char.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        # 行动序列倒计时（固定 #5 速度）：倒计时回合开始时结界解除
        speed = module_params(skill, 5, 70)
        self.countdown_unit_id = sim.add_countdown(
            char, speed=speed, name="无量忿怒倒计时"
        )
        log.notes = (log.notes + " 结界展开" if log.notes else "结界展开")

    def _deal_skill_skill(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        log: ActionLog,
    ) -> None:
        """战技「刃下，归葬」：全体主伤害（#1）+ 随机单体额外段（#2 次 × #3 倍率）。

        全体主伤害每个敌人独立承受完整倍率 + 完整削韧；随机段用固定种子
        真随机（sim.random_enemy）选取目标，结果可复现。所有命中同属本次
        行动（用冻结令牌），按"行动"粒度去重。
        """
        if not sim.enemies:
            return
        token = sim.frozen_action_token
        # 全体主伤害
        main_mult = module_params(skill, 1, 0.0)
        main_toughness = self._skill_toughness(skill)
        for enemy in sim.enemies:
            self._deal_hit(
                sim, char, enemy, main_mult, main_toughness,
                SkillType.SKILL, log, token,
            )
        # 随机单体额外段（真随机，固定种子可复现；单敌场景全部命中同一目标）
        for _ in range(int(module_params(skill, 2, 4))):
            mult = module_params(skill, 3, 0.0)
            if mult <= 0:
                continue
            self._deal_hit(
                sim, char, sim.random_enemy(), mult, 0.0,
                SkillType.SKILL, log, token,
            )

    def _deal_ultra_enh(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        log: ActionLog,
    ) -> None:
        """强化终结技「千冶铸一，万劫烬灭」：全体生命上限伤害（#1）。"""
        if not sim.enemies:
            return
        mult = module_params(skill, 1, 0.0)
        toughness = self._skill_toughness(skill)
        for enemy in sim.enemies:
            self._deal_hit(
                sim, char, enemy, mult, toughness,
                SkillType.ULTRA, log, sim.frozen_action_token,
            )

    def _deal_hit(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        target: EnemyState | None,
        multiplier: float,
        toughness: float,
        skill_type: SkillType,
        log: ActionLog,
        action_token: int,
    ) -> None:
        """打一段生命上限倍率伤害（target 为 None 时跳过）。"""
        if target is None or multiplier <= 0:
            return
        effect = SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=multiplier,
            base_stat="hp",
            toughness_damage=toughness,
            element=ELEMENT,
        )
        sim.deal_damage(
            char, target, effect,
            skill_type=skill_type, log=log, action_token=action_token,
        )

    def _skill_toughness(self, skill: Skill) -> float:
        """技能主削韧（show_stance_list[0]；缺失为 0）。"""
        stance = skill.raw.get("show_stance_list") or []
        if stance:
            return float(stance[0])
        return 0.0

    def _apply_blaze(self, sim: BattleSimulator, char: CharacterUnit, enemy: EnemyState) -> None:
        """施加/刷新【煞火缠身】（终结技 #7/#4/#8 参数；同目标刷新剩余回合）。"""
        skill = char.skills.get(SKILL_ULTRA_OPEN)
        def_part = module_params(skill, 7, BLAZE_DEF_REDUCE)
        vuln_part = module_params(skill, 4, BLAZE_VULNERABILITY)
        turns = int(module_params(skill, 8, BLAZE_TURNS))
        if enemy.unit_id in self.blaze:
            _, old_def, old_vuln = self.blaze[enemy.unit_id]
            self.blaze[enemy.unit_id] = (turns, old_def, old_vuln)
            return
        enemy.def_reduce += def_part
        enemy.vulnerability += vuln_part
        self.blaze[enemy.unit_id] = (turns, def_part, vuln_part)

    def _exit_rage(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """结界解除：退出无量忿怒、清除 buff 与倒计时记录。

        触发路径：倒计时行动（on_countdown）。致命攻击免死解除结界 TODO。
        """
        self.rage = False
        self.countdown_unit_id = ""
        char.buff_mgr.remove_by_name("无量忿怒")
        # 【百炼骨】：结界解除时若能量不足 75% 则立刻恢复至 75%
        self._regen_energy_to_ratio(sim, char)

    def _talent_proc(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """充能达标且可施放战技 → 消耗充能、恢复能量、额外施放战技。"""
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        need = int(module_params(talent, 1, 9))
        if self.charge < need:
            return
        if not self._can_cast_skill(char):
            return  # 生命 ≤1 无法施放：充能保留（已封顶，待生命恢复后触发）
        self.charge = max(0.0, self.charge - need)
        # 恢复能量（#2，无"固定"字样，走能量恢复效率乘区）
        sim.recover_energy(char, module_params(talent, 2, 15))
        self._cast_extra_skill(sim, char)

    def _cast_extra_skill(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """天赋额外战技：消耗生命 → 全体首段 + 4 次随机 → 战技回能（视为追加攻击）。

        视为一次独立行动（"额外施放 1 次战技"）：开启新行动令牌，
        使其命中计入天赋充能（含自身的攻击按行动计）。
        """
        skill = char.skills.get(SKILL_SKILL)
        if skill is None or not sim.enemies:
            return
        sim.begin_new_action()
        # 消耗生命（战技 #4，不足降至 1）
        self._consume_hp(char, module_params(skill, 4, 0.1))

        log = sim.make_follow_up_log(char, sim.enemies[0], notes="因果尽偿·追加战技")
        # 本次独立行动的所有命中共享同一令牌
        token = sim.action_token

        # 全体首段（#1 倍率 + 首段削韧）
        main_toughness = self._skill_toughness(skill)
        for enemy in sim.enemies:
            self._follow_up_deal(
                sim, char, enemy, module_params(skill, 1, 0.0), main_toughness, log, token,
            )
        # 额外 #2 次随机单体（#3 倍率；真随机固定种子）
        for _ in range(int(module_params(skill, 2, 4))):
            self._follow_up_deal(
                sim, char, sim.random_enemy(), module_params(skill, 3, 0.0), 0, log, token,
            )
        # 战技回能（sp_base=30；"视为追加攻击"仅改伤害类型，回能按战技）
        sim.recover_energy(char, skill.energy_recover)
        # 同步日志快照
        log.energy_after = char.energy
        log.sp_after = sim.sp.current

    def _follow_up_deal(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        target: EnemyState | None,
        multiplier: float,
        toughness: float,
        log: ActionLog,
        action_token: int,
    ) -> None:
        """打一段伤害（技能类型=追加攻击，同时标记为战技，共享 log）。

        天赋触发的战技"本次战技视为追加攻击"：伤害记录同时标注
        FOLLOW_UP（主）与 SKILL（secondary），统计/buff 判定时可两者兼顾。
        """
        if target is None or multiplier <= 0:
            return
        effect = SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=multiplier,
            base_stat="hp",
            toughness_damage=toughness,
            element=ELEMENT,
        )
        sim.deal_damage(
            char, target, effect,
            skill_type=SkillType.FOLLOW_UP,
            secondary_skill_type=SkillType.SKILL,
            log=log,
            action_token=action_token,
        )
