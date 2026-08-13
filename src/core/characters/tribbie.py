"""缇宝（Tribbie）技能模块。char_id=1403，同谐 / 量子 / 5 星。

机制：
- 【神启】：战技/秘技进战获得，持续 #2（3）回合（自身回合开始 -1）。
  神启期间我方全体目标全属性抗性穿透提高 #1（12%）。
- 【结界】（终结技 140303）：开启结界并对敌方全体造成 #1 生命上限量子伤害。
  结界期间敌方目标受到的伤害提高 #2（15%）；我方目标攻击（按行动计）后，
  对被攻击目标中当前生命值最高的目标造成 1 次 #3（6%）生命上限量子附加伤害。
  附加伤害并入触发它的那次行动（不单独成行动、不建独立日志），攻击类型为
  【附加伤害】（SkillType.ADDED，不属于普攻/战技/终结技/追加攻击），
  伤害来源为缇宝。结界持续 #4（2）回合（自身回合开始 -1）。
- 【天赋】（140304）：我方其他角色施放终结技后，缇宝发动追加攻击，
  对敌方全体造成 #1（9%）生命上限量子伤害。该效果每个角色最多触发 1 次，
  缇宝施放终结技时重置其他角色可触发次数。
- 行迹额外能力（point_type=3，on_battle_start 读取）：
  - 【长翅膀的玻璃球】：结界期间缇宝生命上限提高，提高数值 = 我方全体
    角色生命上限之和的 #1（9%）。
  - 【岔路旁的小石子】：战斗开始时缇宝恢复 #1（30）点能量；我方其他目标
    攻击后（按行动计）每击中 1 个目标使缇宝恢复 #2（1.5）点能量。
  - 【城墙外的羊羔儿】：施放天赋的追加攻击后，缇宝造成的伤害提高
    #1（72%），最多 #2（3）层，持续 #3（3）回合（自身回合开始 -1）。

技能（nanoka ID，参数经 skill.params 读取，#N → params[N-1]）：
- 140301 普攻「一百层的小火箭」：#1 主目标 15% 生命上限、#2 相邻目标 7.5%
- 140302 战技「礼物都去哪儿了」：#1 抗性穿透 12%、#2 神启持续 3 回合
- 140303 终结技「猜猜这里住着谁」：#1 全体伤害 15%、#2 敌方受伤提高 15%、
  #3 附加伤害 6%、#4 结界持续 2 回合
- 140304 天赋「好忙好忙的缇宝」：#1 追加攻击倍率 9%
- 140307 秘技「开心你就拍拍手」：进战获得【神启】#1（3）回合

未建模（TODO）：
- 普攻相邻目标伤害（#2，需敌人位置模型）
- 附加伤害目标"被攻击目标中当前生命值最高的目标"（无敌方 HP 模型，
  暂取触发命中的目标；单敌场景一致）
- 结界期间缇宝生命上限随我方 HP 变化动态重算（暂在结界开启时计算一次）
- 天赋追击前目标被消灭则对新入场敌人发动（无敌人死亡模型）
- 终结技/天赋追击的削韧（show_stance_list 第二项语义待勘探）
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
SKILL_NORMAL = "140301"
SKILL_SKILL = "140302"
SKILL_ULTRA = "140303"
SKILL_TALENT = "140304"
SKILL_TECHNIQUE = "140307"  # 秘技

ELEMENT = "Quantum"  # 量子属性

# 【神启】buff 标识
ORACLE_BUFF_ID = "tribbie_oracle_pen"
ORACLE_BUFF_NAME = "神启"
# A2 结界 HP 上限 buff 标识
A2_HP_BUFF_ID = "tribbie_a2_hp"
# A6 增伤 buff 标识
A6_BUFF_ID = "tribbie_a6_dmg"

# 行迹额外能力名称前缀（point_name 带省略号/标点，用前缀匹配）
TRACE_A2_NAME = "长翅膀的玻璃球"   # [0.09]
TRACE_A4_NAME = "岔路旁的小石子"   # [30, 1.5]
TRACE_A6_NAME = "城墙外的羊羔儿"   # [0.72, 3, 3]

# 行迹参数兜底常量（数据缺失时使用）
TRACE_A2_HP_RATIO = 0.09   # 结界期间 HP 上限 = 我方全体 HP 之和的 9%
TRACE_A4_START_ENERGY = 30.0  # 战斗开始回 30 能量
TRACE_A4_HIT_ENERGY = 1.5  # 我方其他目标攻击后回 1.5 能量
TRACE_A6_DMG = 0.72        # 天赋追击后增伤 72%/层
TRACE_A6_STACKS = 3        # 最多 3 层
TRACE_A6_TURNS = 3         # 持续 3 回合


@register
class TribbieModule(CharacterModule):
    """缇宝技能模块。"""

    CHAR_ID = "1403"

    # ── 状态（纯数据，deepcopy 安全）──────────────────────
    unit_id: str = ""              # 所属角色单位 ID（on_battle_start 时记录）
    field_turns: int = 0           # 结界剩余回合（缇宝回合开始 -1，0=已解除）
    vuln_contribution: float = 0.0  # 本模块对敌方 vulnerability 的贡献（增量式）
    # 天赋追击可用次数：{unit_id: bool}；缺省按 True（首次终结技可触发），
    # 缇宝施放终结技时清空（全部重置为可触发）
    ultra_ready: dict[str, bool] = {}
    # 已处理结界附加伤害的行动令牌集合（按行动计：一次攻击行动的多段命中
    # 只触发 1 次附加伤害；用集合避免连锁触发后令牌交替导致的去重失败）
    _extra_tokens: set[int] = set()
    # 已处理 A4 回能的行动令牌集合（同上，我方其他目标攻击按行动回能）
    _a4_tokens: set[int] = set()
    # 行迹参数（on_battle_start 从 skill_trees 读取）
    a2_hp_ratio: float = TRACE_A2_HP_RATIO
    a4_start_energy: float = TRACE_A4_START_ENERGY
    a4_hit_energy: float = TRACE_A4_HIT_ENERGY
    a6_dmg: float = TRACE_A6_DMG
    a6_max_stacks: int = TRACE_A6_STACKS
    a6_turns: int = TRACE_A6_TURNS

    # ── 事件钩子 ─────────────────────────────────────────

    def on_battle_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        self.unit_id = char.unit_id
        self.field_turns = 0
        self.vuln_contribution = 0.0
        self.ultra_ready = {}
        self._extra_tokens = set()
        self._a4_tokens = set()
        # 读取行迹额外能力参数
        self._read_trace_params(char)
        # 【岔路旁的小石子】：战斗开始恢复 30 点能量（走能量恢复效率乘区）
        if self.a4_start_energy:
            sim.recover_energy(char, self.a4_start_energy)
        # 秘技进战：获得【神启】（140307 #1 回合）
        self._apply_oracle(
            sim, char,
            turns=int(module_params(char.skills.get(SKILL_TECHNIQUE), 1, 3)),
            ratio=module_params(char.skills.get(SKILL_SKILL), 1, 0.12),
        )

    def on_turn_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """自身回合开始：结界剩余回合 -1，归零时解除结界。

        【神启】的回合扣减由 buff 系统处理（TURNS_SELF_START + source_unit=缇宝，
        只有缇宝回合开始时 tick）。
        """
        if char.unit_id != self.unit_id:
            return
        if self.field_turns <= 0:
            return
        self.field_turns -= 1
        if self.field_turns <= 0:
            self._close_field(sim, char)

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
        if skill_id == SKILL_NORMAL:
            # 普攻：生命上限倍率伤害（#1；相邻目标 #2 未建模 TODO）
            if skill.effects:
                skill.effects[0].base_stat = "hp"
        elif skill_id == SKILL_SKILL:
            # 战技无伤害（#1 是抗性穿透而非倍率），清空误解析 effects
            skill.effects = []
            self._apply_oracle(
                sim, char,
                turns=int(module_params(skill, 2, 3)),
                ratio=module_params(skill, 1, 0.12),
            )
        elif skill_id == SKILL_ULTRA:
            # 终结技：生命上限倍率伤害（#1）+ 开启结界（易伤影响本体伤害，
            # 故在伤害结算前 on_skill_cast 开启，本体伤害吃到易伤）
            if skill.effects:
                skill.effects[0].base_stat = "hp"
            self._open_field(sim, char, skill)

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
        """结界附加伤害 + A4 行迹回能（均按行动计，一次行动只触发一次）。

        附加伤害以 is_attack=False 打出（不进 on_attack_hit 分发），
        无递归问题；此处只需按行动令牌去重。
        """
        char = next((c for c in sim.characters if c.unit_id == self.unit_id), None)
        if char is None:
            return

        # 结界期间：我方目标攻击（含缇宝自己，按行动）后触发附加伤害。
        # 附加伤害并入触发它的那次行动（log 为触发攻击的日志，不单独成行动）；
        # 附加伤害不是"攻击"（is_attack=False，不进 on_attack_hit 分发），
        # 因此不会递归触发自身，也不会触发不死途天赋等"攻击后"系效果
        if self.field_turns > 0 and action_token not in self._extra_tokens:
            self._extra_tokens.add(action_token)
            self._extra_damage(sim, char, target, log)

        # 【岔路旁的小石子】：我方其他目标攻击（按行动，缇宝自己不算）回能
        if attacker.unit_id != self.unit_id and action_token not in self._a4_tokens:
            self._a4_tokens.add(action_token)
            if self.a4_hit_energy:
                sim.recover_energy(char, self.a4_hit_energy)

    def on_skill_end(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """终结技结算后：队友终结技 → 天赋追击；缇宝终结技 → 重置触发次数。"""
        if skill.skill_type != SkillType.ULTRA:
            return
        if char.unit_id == self.unit_id:
            # 缇宝施放终结技：重置我方其他角色可触发次数
            self.ultra_ready = {}
            return
        # 我方其他角色施放终结技后：缇宝发动天赋追加攻击（每角色最多 1 次）
        if self.ultra_ready.get(char.unit_id, True):
            self.ultra_ready[char.unit_id] = False
            self._ultra_follow_up(sim, char)

    # ── 私有辅助 ─────────────────────────────────────────

    def _read_trace_params(self, char: CharacterUnit) -> None:
        """读取三个行迹额外能力参数（point_type=3，按名称前缀匹配）。"""
        for group in char.skill_trees_raw.values():
            if not isinstance(group, dict):
                continue
            for point in group.values():
                if not isinstance(point, dict) or point.get("point_type") != 3:
                    continue
                name = str(point.get("point_name", ""))
                params = point.get("param_list") or []
                if name.startswith(TRACE_A2_NAME) and params:
                    self.a2_hp_ratio = float(params[0])
                elif name.startswith(TRACE_A4_NAME) and len(params) >= 2:
                    self.a4_start_energy = float(params[0])
                    self.a4_hit_energy = float(params[1])
                elif name.startswith(TRACE_A6_NAME) and len(params) >= 3:
                    self.a6_dmg = float(params[0])
                    self.a6_max_stacks = int(params[1])
                    self.a6_turns = int(params[2])

    def _apply_oracle(self, sim: BattleSimulator, char: CharacterUnit, *, turns: int, ratio: float) -> None:
        """获得【神启】：我方全体目标全属性抗性穿透提高（自身回合开始 -1）。

        buff 加到全体我方角色（含缇宝自己），source_unit=缇宝：
        TURNS_SELF_START 的扣减按 source_unit 匹配，只有缇宝回合开始时才 tick。
        """
        if ratio <= 0 or turns <= 0:
            return
        for ally in sim.characters:
            ally.buff_mgr.add(Buff(
                id=ORACLE_BUFF_ID,
                name=ORACLE_BUFF_NAME,
                stat="res_pen",
                value=ratio,
                duration_type=BuffDuration.TURNS_SELF_START,
                duration_count=turns,
                source_unit=self.unit_id,
                stack_rule=StackRule.NO_STACK_SAME_NAME,
            ))

    def _open_field(self, sim: BattleSimulator, char: CharacterUnit, skill: Skill) -> None:
        """开启结界：敌方受伤提高 #2 + 持续 #4 回合 + A2 行迹生命上限。

        若已在结界中（刷新），先撤销旧贡献再按新参数重开。
        """
        # 敌方受伤提高（增量式，与千冶【煞火缠身】等其余模块的易伤共存；
        # 刷新结界时先归零旧贡献再应用新值）
        self._set_vulnerability(sim, 0.0)
        self._set_vulnerability(sim, module_params(skill, 2, 0.15))
        self.field_turns = int(module_params(skill, 4, 2))

        # 【长翅膀的玻璃球】：结界期间缇宝生命上限提高 = 我方全体生命上限
        # 之和的 #1。在结界开启时计算一次（我方 HP 上限后续变化不重算，TODO）。
        # 注意：计算时不能含 A2 buff 自身（先移除旧的再求和，避免自我叠加）。
        char.buff_mgr.remove(A2_HP_BUFF_ID)
        total_hp = sum(ally.final_stats().hp for ally in sim.characters)
        if self.a2_hp_ratio > 0 and total_hp > 0:
            char.buff_mgr.add(Buff(
                id=A2_HP_BUFF_ID,
                name="长翅膀的玻璃球",
                stat="hp_flat",
                value=total_hp * self.a2_hp_ratio,
                duration_type=BuffDuration.PERMANENT,
                duration_count=-1,
                source_unit=char.unit_id,
                stack_rule=StackRule.NO_STACK_SAME_NAME,
            ))

    def _close_field(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """结界解除：撤销敌方易伤贡献、移除 A2 生命上限 buff。"""
        self._set_vulnerability(sim, 0.0)
        self.field_turns = 0
        char.buff_mgr.remove(A2_HP_BUFF_ID)

    def _set_vulnerability(self, sim: BattleSimulator, rate: float) -> None:
        """设置本模块对敌方易伤的贡献（增量式 diff 应用，与其他模块共存）。"""
        diff = rate - self.vuln_contribution
        self.vuln_contribution = rate
        for enemy in sim.enemies:
            enemy.vulnerability += diff

    def _extra_damage(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        target: EnemyState,
        log: ActionLog | None,
    ) -> None:
        """结界附加伤害：对被攻击目标造成 #3 生命上限量子附加伤害。

        - 攻击类型为【附加伤害】（SkillType.ADDED），不属于普攻/战技/
          终结技/追加攻击中的任何一种；伤害来源为缇宝。
        - 不单独成行动（不 begin_new_action）、不建独立日志——
          伤害直接并入触发它的那次行动（log 为触发攻击的日志）。
        - 不是"攻击"（is_attack=False）：不触发 on_attack_hit 钩子与
          NEXT_ATTACK buff tick，"攻击后"系效果（不死途天赋、千冶充能等）
          不受附加伤害影响；自身也不会递归触发。
        - 目标简化：文本为"被攻击目标中当前生命值最高的目标"
          （无敌方 HP 模型，暂取触发命中的目标，单敌场景一致；多敌 TODO）。
        """
        ultra = char.skills.get(SKILL_ULTRA)
        mult = module_params(ultra, 3, 0.0)
        if mult <= 0:
            return
        effect = SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=mult,
            base_stat="hp",
            toughness_damage=0,  # TODO: 附加伤害削韧待勘探
            element=ELEMENT,
        )
        sim.deal_damage(char, target, effect, skill_type=SkillType.ADDED, log=log, is_attack=False)

    def _ultra_follow_up(self, sim: BattleSimulator, ult_char: CharacterUnit) -> None:
        """天赋【好忙好忙的缇宝】：其他角色施放终结技后，缇宝对敌方全体
        造成 #1 生命上限量子伤害（追加攻击，独立行动，追加攻击回能）。

        追击后叠加【城墙外的羊羔儿】增伤（A6 行迹）。
        注意：技能参数取自缇宝自己的 skills（ult_char 是施放终结技的队友）。
        """
        char = next((c for c in sim.characters if c.unit_id == self.unit_id), None)
        if char is None or not sim.enemies:
            return
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        if talent is None:
            return
        mult = module_params(talent, 1, 0.0)
        if mult <= 0:
            return
        # 天赋追击是独立攻击行动（与触发它的终结技分开计数）
        sim.begin_new_action()
        target = sim.enemies[0]
        log = sim.make_follow_up_log(char, target, notes="天赋追击")
        # 对敌方全体造成伤害（单敌模型 = 1 段；多敌 TODO 全打）
        for enemy in sim.enemies:
            effect = SkillEffect(
                damage_type=DamageType.NORMAL,
                multiplier=mult,
                base_stat="hp",
                toughness_damage=0,  # TODO: 追击削韧待勘探（show_stance_list 第二项 15）
                element=ELEMENT,
            )
            sim.deal_damage(char, enemy, effect, skill_type=SkillType.FOLLOW_UP, log=log)
        # 追加攻击回能（天赋 sp_base=5）
        sim.recover_energy(char, talent.energy_recover)
        log.energy_after = char.energy
        log.sp_after = sim.sp.current
        # A6：施放天赋追击后，缇宝造成的伤害提高（最多 3 层，3 回合）
        self._stack_a6(sim, char)

    def _stack_a6(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        """【城墙外的羊羔儿】：增伤 buff（STACK_LIMIT_N，满层刷新时效）。"""
        if self.a6_dmg <= 0:
            return
        char.buff_mgr.add(Buff(
            id=A6_BUFF_ID,
            name="城墙外的羊羔儿",
            stat="dmg_bonus",
            value=self.a6_dmg,
            duration_type=BuffDuration.TURNS_SELF_START,
            duration_count=self.a6_turns,
            source_unit=char.unit_id,
            stack_rule=StackRule.STACK_LIMIT_N,
            max_stacks=self.a6_max_stacks,
        ))
