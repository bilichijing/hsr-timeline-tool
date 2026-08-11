"""战斗模拟引擎。

主循环：
    while not 战斗结束:
        1. ActionQueue.next_actor() 取 AV 最小单位
        2. 单位行动（角色执行技能 / 怪物行动 / 阿哈时刻）
        3. 结算伤害、buff 生效/失效
        4. 更新 SP、能量、韧性
        5. 怪物行动后恢复韧性（如已击破）
        6. 重新计算行动队列（速度可能变化）

操作序列：
    用户预定义的操作列表，按 AV 顺序执行。
    每个操作 = (unit_id, skill_id, target_id)
    若无预定义操作，则使用默认逻辑（普攻优先）。

阿哈机制：
    - 笑点 > 0 时阿哈入队
    - 阿哈行动时触发阿哈时刻：所有欢愉角色按参演编号释放欢愉技
    - 阿哈时刻结束后：清空笑点、好活当赏 += 本次笑点数、笑点 = 欢愉角色数
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .av_system import ActionEntry, ActionQueue, AV_PER_ACTION
from .buff import Buff, BuffDuration, BuffManager, StackRule
from .damage import (
    DamageContext,
    DamageType,
    DefenseContext,
    calculate_damage,
    ELATION_BASE_LEVEL_80,
)
from .skill import Skill, SkillType
from .sp import SkillPoint
from .stats import BaseStats, FinalStats, StatBonus, StatCalculator


# ── 战斗单位 ──────────────────────────────────────────────


@dataclass
class EnemyState:
    """怪物状态（开发文档 6.5）。"""

    unit_id: str
    name: str
    max_toughness: float
    current_toughness: float
    weakness_elements: list[str]
    is_broken: bool = False
    level: int = 80
    resistance: dict[str, float] = field(default_factory=dict)  # {属性: 抗性}
    # 减伤 / 抗性 / 防御 buff（由 BuffManager 管理）
    buff_mgr: BuffManager = field(default_factory=lambda: BuffManager(unit_id=""))

    def __post_init__(self) -> None:
        self.buff_mgr.unit_id = self.unit_id

    def reduce_toughness(self, amount: float, element: str) -> bool:
        """削减韧性，返回是否触发击破。

        非弱点属性不削韧。
        韧性归零且未击破时触发击破状态。
        """
        if element not in self.weakness_elements:
            return False
        self.current_toughness = max(0, self.current_toughness - amount)
        if self.current_toughness <= 0 and not self.is_broken:
            self.is_broken = True
            return True
        return False

    def recover_toughness(self) -> None:
        """怪物自己行动后恢复韧性（满血）。"""
        self.current_toughness = self.max_toughness
        self.is_broken = False


@dataclass
class CharacterUnit:
    """战斗中的角色单位。"""

    unit_id: str
    name: str
    path: str                # 命途（"Elation" 等）
    element: str             # 属性
    level: int = 80
    base_stats: BaseStats = field(default_factory=BaseStats)
    bonus_stats: StatBonus = field(default_factory=StatBonus)  # 光锥+遗器
    skills: dict[str, Skill] = field(default_factory=dict)
    buff_mgr: BuffManager = field(default_factory=lambda: BuffManager(unit_id=""))
    energy: float = 0
    # 欢愉系统
    laugh_point: float = 0   # 笑点（动态资源）
    # 好活当赏以 buff 形式存在，由 buff_mgr 管理
    is_elation: bool = False  # 是否欢愉命途
    elation_skill_index: int = 0  # 欢愉技参演编号

    def __post_init__(self) -> None:
        self.buff_mgr.unit_id = self.unit_id
        self.is_elation = self.path == "Elation"

    def final_stats(self) -> FinalStats:
        """计算当前最终面板（含 buff）。"""
        buff_bonus = self.buff_mgr.total_bonus()
        # 好活当赏累加：从所有 TURNS_SELF_END 类型的好活当赏 buff 取 value 之和
        good_joke_total = self._sum_good_joke()
        bonus = StatBonus(
            **{
                **{k: getattr(self.bonus_stats, k) + getattr(buff_bonus, k)
                   for k in buff_bonus.__dataclass_fields__},
                "good_joke": good_joke_total,
            }
        )
        calc = StatCalculator(base=self.base_stats, bonus=bonus)
        final = calc.final()
        # 笑点是动态资源，直接覆盖
        final.laugh_point = self.laugh_point
        return final

    def _sum_good_joke(self) -> float:
        """累加所有"好活当赏"buff 的点数。

        好活当赏以独立 buff 形式存在（每个独立计时），name="好活当赏"。
        """
        return sum(b.value for b in self.buff_mgr.buffs if b.name == "好活当赏")


@dataclass
class ActionLog:
    """单次行动日志（用于 UI 展示）。"""

    av: float                          # 行动者当时的 AV（单位自身）
    total_av: float                    # 战斗累计总行动值
    actor_id: str
    actor_name: str
    action_type: str                   # "normal"/"skill"/"ultra"/"monster"/"aha_moment"/...
    target_id: str = ""
    damages: list[float] = field(default_factory=list)  # 每段伤害
    total_damage: float = 0
    sp_after: int = 3
    energy_after: float = 0
    enemy_broken: bool = False         # 本次行动是否触发击破
    notes: str = ""                    # 备注（如"欢愉技"、"超击破"）


# ── 操作序列 ──────────────────────────────────────────────


@dataclass
class PlayerAction:
    """玩家预定义操作。"""

    unit_id: str
    skill_type: SkillType              # 普攻/战技/终结技/...
    target_id: str = ""                # 目标怪物
    notes: str = ""


# ── 战斗模拟器 ────────────────────────────────────────────


class BattleEndReason(Enum):
    """战斗结束原因。"""

    MAX_TURNS = "max_turns"
    MAX_AV = "max_av"
    ALL_ENEMIES_DEAD = "all_enemies_dead"
    NO_ACTIONS = "no_actions"


@dataclass
class BattleResult:
    """战斗结果。"""

    logs: list[ActionLog] = field(default_factory=list)
    total_damage: float = 0
    total_turns: int = 0
    total_av: float = 0                 # 战斗累计总行动值
    final_av: float = 0
    end_reason: BattleEndReason = BattleEndReason.MAX_AV
    aha_count: int = 0                  # 阿哈时刻触发次数
    final_laugh_point: float = 0
    final_sp: int = 3


@dataclass
class BattleSimulator:
    """战斗模拟引擎。

    用法：
        sim = BattleSimulator(
            characters=[char1, char2, ...],
            enemies=[enemy1],
            max_turns=10,
        )
        sim.setup()
        result = sim.run(actions=[...])
    """

    characters: list[CharacterUnit]
    enemies: list[EnemyState]
    max_av: float = 300.0              # 战斗结束条件：总行动值达到此值
    max_turns: int = 1000              # 备用安全网（防死循环）
    initial_sp: int = 3

    # 内部状态
    action_queue: ActionQueue = field(default_factory=ActionQueue)
    sp: SkillPoint = field(default_factory=SkillPoint)
    logs: list[ActionLog] = field(default_factory=list)
    total_damage: float = 0
    total_av: float = 0                # 战斗累计总行动值
    aha_count: int = 0
    aha_entry: ActionEntry | None = None  # 阿哈在行动条上的实例
    current_turn: int = 0

    def setup(self) -> None:
        """战斗初始化。"""
        # SP
        self.sp = SkillPoint(initial=self.initial_sp)

        # 行动队列
        self.action_queue = ActionQueue()
        for char in self.characters:
            self.action_queue.add(ActionEntry(
                unit_id=char.unit_id,
                name=char.name,
                speed=char.base_stats.spd_base,
                current_av=AV_PER_ACTION / char.base_stats.spd_base,
                is_monster=False,
            ))
        for enemy in self.enemies:
            spd = 100  # 怪物速度默认 100（应由外部设置）
            self.action_queue.add(ActionEntry(
                unit_id=enemy.unit_id,
                name=enemy.name,
                speed=spd,
                current_av=AV_PER_ACTION / spd,
                is_monster=True,
            ))

        # 欢愉系统初始化
        elation_chars = [c for c in self.characters if c.is_elation]
        if elation_chars:
            # 战斗开始：所有欢愉角色获得 20 点好活当赏
            for char in elation_chars:
                char.buff_mgr.add(Buff(
                    id=f"good_joke_init_{char.unit_id}",
                    name="好活当赏",
                    stat="good_joke",
                    value=20,
                    duration_type=BuffDuration.PERMANENT,  # 初始 20 点永久（不衰减）
                    duration_count=-1,
                    source_unit=char.unit_id,
                    stack_rule=StackRule.STACK_ALWAYS,
                ))
            # 笑点 = 欢愉角色数量
            self._grant_laugh_point(len(elation_chars))

    def _grant_laugh_point(self, amount: float) -> None:
        """获得笑点（若为首次则阿哈入队）。"""
        was_zero = all(c.laugh_point == 0 for c in self.characters if c.is_elation)
        for char in self.characters:
            if char.is_elation:
                char.laugh_point += amount
        # 阿哈入队（若之前不在队列）
        if was_zero and amount > 0:
            self._spawn_aha()

    def _spawn_aha(self) -> None:
        """阿哈加入行动条。"""
        elation_chars = [c for c in self.characters if c.is_elation]
        if not elation_chars:
            return
        # 按速度降序排序
        sorted_chars = sorted(elation_chars, key=lambda c: c.final_stats().spd, reverse=True)
        weights = [5, 10, 20, 50]  # 分母
        aha_speed = 80
        for i, char in enumerate(sorted_chars[:4]):
            aha_speed += char.final_stats().spd / weights[i]
        self.aha_entry = ActionEntry(
            unit_id="__aha__",
            name="阿哈",
            speed=aha_speed,
            current_av=AV_PER_ACTION / aha_speed,
            is_monster=False,
        )
        self.action_queue.add(self.aha_entry)

    def _remove_aha(self) -> None:
        """阿哈离开行动条。"""
        if self.aha_entry:
            self.action_queue.remove("__aha__")
            self.aha_entry = None

    def run(self, actions: list[PlayerAction] | None = None) -> BattleResult:
        """执行战斗模拟。

        战斗结束条件：累计总行动值达到 max_av（默认 300）。

        Args:
            actions: 玩家预定义操作列表（按顺序执行）。
                     若为 None，则使用默认逻辑（普攻优先，SP 足够时用战技）。
        """
        action_idx = 0
        actions = actions or []
        actor: ActionEntry | None = None

        while self.total_av < self.max_av and self.current_turn < self.max_turns:
            # 取下一个行动者
            if not self.action_queue.entries:
                break
            actor = self.action_queue.next_actor()
            # 防死循环：单个单位 AV 异常大
            if actor.current_av > 10000:
                break

            self.current_turn += 1
            # 累计总行动值（本次行动消耗的 AV = 行动者当前 AV）
            self.total_av += actor.current_av

            # 阿哈时刻
            if actor.unit_id == "__aha__":
                self._trigger_aha_moment()
                continue

            # 怪物行动
            if actor.is_monster:
                self._monster_act(actor)
                continue

            # 角色行动
            char = self._get_character(actor.unit_id)
            if char is None:
                self.action_queue.advance()
                continue

            # 决定操作
            action: PlayerAction | None = None
            if action_idx < len(actions):
                # 找到属于当前角色的下一个操作
                for i in range(action_idx, len(actions)):
                    if actions[i].unit_id == char.unit_id:
                        action = actions[i]
                        action_idx = i + 1
                        break

            if action is None:
                # 默认逻辑：能量满用终结技，SP 够用战技，否则普攻
                action = self._default_action(char)

            self._character_act(char, action, actor)

        # 判断结束原因
        if self.total_av >= self.max_av:
            end_reason = BattleEndReason.MAX_AV
        elif not self.action_queue.entries:
            end_reason = BattleEndReason.NO_ACTIONS
        else:
            end_reason = BattleEndReason.MAX_TURNS

        return BattleResult(
            logs=self.logs,
            total_damage=self.total_damage,
            total_turns=self.current_turn,
            total_av=self.total_av,
            final_av=actor.current_av if actor and self.action_queue.entries else 0,
            end_reason=end_reason,
            aha_count=self.aha_count,
            final_laugh_point=sum(c.laugh_point for c in self.characters if c.is_elation),
            final_sp=self.sp.current,
        )

    def _get_character(self, unit_id: str) -> CharacterUnit | None:
        for c in self.characters:
            if c.unit_id == unit_id:
                return c
        return None

    def _get_enemy(self, unit_id: str) -> EnemyState | None:
        for e in self.enemies:
            if e.unit_id == unit_id:
                return e
        return None

    def _default_action(self, char: CharacterUnit) -> PlayerAction:
        """默认操作逻辑。"""
        target = self.enemies[0].unit_id if self.enemies else ""
        # 能量满用终结技
        if char.energy >= self._get_energy_cost(char, SkillType.ULTRA):
            return PlayerAction(
                unit_id=char.unit_id,
                skill_type=SkillType.ULTRA,
                target_id=target,
            )
        # SP 够用战技
        if self.sp.can_consume(1):
            return PlayerAction(
                unit_id=char.unit_id,
                skill_type=SkillType.SKILL,
                target_id=target,
            )
        # 否则普攻
        return PlayerAction(
            unit_id=char.unit_id,
            skill_type=SkillType.NORMAL,
            target_id=target,
        )

    def _get_energy_cost(self, char: CharacterUnit, skill_type: SkillType) -> float:
        """获取技能能量需求。"""
        for s in char.skills.values():
            if s.skill_type == skill_type:
                return s.energy_cost
        return 90 if skill_type == SkillType.ULTRA else 0

    def _character_act(
        self,
        char: CharacterUnit,
        action: PlayerAction,
        entry: ActionEntry,
    ) -> None:
        """角色执行操作。"""
        # 回合开始
        char.buff_mgr.begin_turn()
        char.buff_mgr.tick_turn_start()

        # 获取技能
        skill: Skill | None = None
        for s in char.skills.values():
            if s.skill_type == action.skill_type:
                skill = s
                break
        if skill is None:
            # 回合结束
            char.buff_mgr.tick_turn_end()
            char.buff_mgr.end_turn()
            self.action_queue.advance()
            return

        # SP / 能量结算
        if skill.sp_cost > 0:
            self.sp.consume(skill.sp_cost)
        elif skill.sp_cost < 0:
            self.sp.recover(-skill.sp_cost)
        if skill.energy_cost > 0:
            char.energy = max(0, char.energy - skill.energy_cost)
        # 行动回复能量
        char.energy = min(char.base_stats.energy_max, char.energy + 20)

        # 目标
        target = self._get_enemy(action.target_id) if action.target_id else (self.enemies[0] if self.enemies else None)

        log = ActionLog(
            av=entry.current_av,
            total_av=self.total_av,
            actor_id=char.unit_id,
            actor_name=char.name,
            action_type=action.skill_type.value.lower(),
            target_id=target.unit_id if target else "",
            sp_after=self.sp.current,
            energy_after=char.energy,
        )

        # 计算伤害
        if target:
            for effect in skill.effects:
                damage = self._calc_skill_damage(char, skill, effect, target)
                log.damages.append(damage)
                log.total_damage += damage
                self.total_damage += damage

                # 削韧
                if effect.toughness_damage > 0:
                    broken = target.reduce_toughness(effect.toughness_damage, effect.element or char.element)
                    if broken:
                        log.enemy_broken = True
                        # 触发击破伤害
                        break_dmg = self._calc_break_damage(char, target)
                        log.damages.append(break_dmg)
                        log.total_damage += break_dmg
                        self.total_damage += break_dmg

                # buff 触发（攻击命中）
                char.buff_mgr.tick_attack()
                target.buff_mgr.tick_attack()

        # NEXT_ATTACK 类型 buff 失效
        char.buff_mgr.tick_attack()

        # 回合结束
        char.buff_mgr.tick_turn_end()
        char.buff_mgr.end_turn()

        self.logs.append(log)
        self.action_queue.advance()

    def _calc_skill_damage(
        self,
        char: CharacterUnit,
        skill: Skill,
        effect: Any,
        target: EnemyState,
    ) -> float:
        """计算技能单段伤害。"""
        stats = char.final_stats()
        element = effect.element or char.element
        is_weakness = element in target.weakness_elements

        # 基础值 = 攻击力 × 倍率（或生命/防御）
        if effect.base_stat == "hp":
            base_value = stats.hp * effect.multiplier
        elif effect.base_stat == "def":
            base_value = stats.defense * effect.multiplier
        else:
            base_value = stats.atk * effect.multiplier

        # 防御上下文
        def_ctx = DefenseContext(
            attacker_level=char.level,
            defender_level=target.level,
            defender_defense=0,  # 怪物防御暂未建模
        )

        # 减伤列表（来自目标 buff）
        damage_reductions: list[float] = []
        # 此处可从 target.buff_mgr 提取减伤 buff

        ctx = DamageContext(
            damage_type=effect.damage_type,
            element=element,
            base_value=base_value,
            attacker_stats=stats,
            is_weakness=is_weakness,
            is_broken=target.is_broken,
            resistance=target.resistance.get(element),
            dmg_bonus=stats.dmg_bonus,
            damage_reductions=damage_reductions,
            defense_ctx=def_ctx,
            is_crit=False,  # 暴击由调用方决定
            crit_rate=stats.crit_rate,
            crit_dmg=stats.crit_dmg,
            break_effect=stats.break_effect,
            toughness_max=target.max_toughness,
            actual_toughness_reduced=effect.toughness_damage,
        )
        return calculate_damage(ctx)

    def _calc_break_damage(self, char: CharacterUnit, target: EnemyState) -> float:
        """计算击破伤害（韧性归零时触发）。"""
        stats = char.final_stats()
        def_ctx = DefenseContext(
            attacker_level=char.level,
            defender_level=target.level,
        )
        ctx = DamageContext(
            damage_type=DamageType.BREAK,
            element=char.element,
            base_value=0,
            attacker_stats=stats,
            is_weakness=True,
            is_broken=True,
            break_effect=stats.break_effect,
            toughness_max=target.max_toughness,
            defense_ctx=def_ctx,
        )
        return calculate_damage(ctx)

    def _monster_act(self, entry: ActionEntry) -> None:
        """怪物行动。"""
        enemy = self._get_enemy(entry.unit_id)
        if enemy is None:
            self.action_queue.advance()
            return

        # 怪物行动后恢复韧性（满血）
        if enemy.is_broken:
            enemy.recover_toughness()

        log = ActionLog(
            av=entry.current_av,
            total_av=self.total_av,
            actor_id=enemy.unit_id,
            actor_name=enemy.name,
            action_type="monster",
            notes="恢复韧性" if enemy.is_broken else "",
        )
        self.logs.append(log)
        self.action_queue.advance()

    def _trigger_aha_moment(self) -> None:
        """触发阿哈时刻。"""
        self.aha_count += 1
        # 记录当前笑点数（用于好活当赏转化）
        laugh_before = sum(c.laugh_point for c in self.characters if c.is_elation)

        # 阿哈行动消耗的 AV（total_av 已在 run() 中累计）
        consumed = self.aha_entry.current_av if self.aha_entry else 0

        log = ActionLog(
            av=consumed,
            total_av=self.total_av,
            actor_id="__aha__",
            actor_name="阿哈",
            action_type="aha_moment",
            notes=f"阿哈时刻 #{self.aha_count}（笑点 {laugh_before}）",
        )

        # 1. 解除我方所有欢愉角色的控制类负面状态（暂未实现控制类 buff）
        # 2. 各个欢愉角色按参演编号顺序释放欢愉技
        elation_chars = sorted(
            [c for c in self.characters if c.is_elation],
            key=lambda c: c.elation_skill_index,
        )
        for char in elation_chars:
            # 释放欢愉技（造成欢愉伤害）
            # 欢愉倍率字段待勘探，此处先用 1.0 占位
            target = self.enemies[0] if self.enemies else None
            if target:
                stats = char.final_stats()
                def_ctx = DefenseContext(
                    attacker_level=char.level,
                    defender_level=target.level,
                )
                ctx = DamageContext(
                    damage_type=DamageType.ELATION,
                    element=char.element,
                    base_value=ELATION_BASE_LEVEL_80,  # 80 级固定值
                    attacker_stats=stats,
                    is_weakness=char.element in target.weakness_elements,
                    is_broken=target.is_broken,
                    defense_ctx=def_ctx,
                    elation_multiplier=1.0,  # 待勘探
                    is_elation_skill=True,
                )
                dmg = calculate_damage(ctx)
                log.damages.append(dmg)
                log.total_damage += dmg
                self.total_damage += dmg

        # 3. 清空笑点
        for char in self.characters:
            if char.is_elation:
                char.laugh_point = 0

        # 4. 阿哈时刻结束后：好活当赏 += 本次笑点数，笑点 = 欢愉角色数
        if laugh_before > 0:
            for char in elation_chars:
                char.buff_mgr.add(Buff(
                    id=f"good_joke_aha_{self.aha_count}_{char.unit_id}",
                    name="好活当赏",
                    stat="good_joke",
                    value=laugh_before,
                    duration_type=BuffDuration.TURNS_SELF_END,
                    duration_count=2,
                    source_unit=char.unit_id,
                    stack_rule=StackRule.STACK_ALWAYS,
                ))
        # 重新获得笑点
        self._grant_laugh_point(len(elation_chars))

        # 阿哈离开前：所有其他单位的 AV 减去阿哈消耗的 AV
        for e in self.action_queue.entries:
            if e.unit_id != "__aha__":
                e.current_av -= consumed

        # 阿哈离开行动条
        self._remove_aha()
        self.logs.append(log)
