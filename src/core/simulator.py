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

import copy
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

from .av_system import ActionEntry, ActionQueue, AV_PER_ACTION
from .buff import Buff, BuffDuration, BuffManager, StackRule
from .damage import (
    DamageContext,
    DamageType,
    DefenseContext,
    calculate_damage,
    ELATION_BASE_LEVEL_80,
)
from .skill import Skill, SkillType, get_skill_by_type
from .sp import SkillPoint
from .stats import BaseStats, FinalStats, StatBonus, StatCalculator

if TYPE_CHECKING:
    from .characters.base import CharacterModule


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
    speed: float = 100.0             # 行动速度（默认 100，进队列用）
    resistance: dict[str, float] = field(default_factory=dict)  # {属性: 抗性}
    def_reduce: float = 0.0  # 敌方减防（模块各自维护贡献值，增量式累加/撤销）
    vulnerability: float = 0.0  # 敌方易伤（同上，增量式管理，如千冶【煞火缠身】）
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

    def reduce_defense(self, rate: float) -> None:
        """设置敌方全体减防（由角色模块维护，如不死途【饲饵】）。"""
        self.def_reduce = rate

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
    initial_energy: float = 0.0  # 战斗开始初始能量（freesr sp_value，setup 时应用）
    # 欢愉系统
    laugh_point: float = 0   # 笑点（动态资源）
    # 好活当赏以 buff 形式存在，由 buff_mgr 管理
    is_elation: bool = False  # 是否欢愉命途
    elation_skill_index: int = 0  # 欢愉技参演编号
    elation_skill_level: int = 1  # 欢愉技等级（识别逻辑 TODO，暂只存储）
    char_id: str = ""        # nanoka 角色 ID（用于加载头像，空表示无头像）
    current_hp: float = 0.0  # 当前生命值（最小 HP 模型：模块在 on_battle_start 初始化
    #                        为面板生命上限，生命消耗/回复由模块管理；上限取 final_stats().hp）
    skill_trees_raw: dict = field(default_factory=dict)  # 原始行迹（模块读额外能力参数用）

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
class DamageRecord:
    """单段伤害记录：技能类型 × 伤害类型双维度。

    追加攻击（FOLLOW_UP）可造成任何伤害类型（常规/击破/超击破/持续/欢愉），
    因此每个伤害段同时标注 skill_type 与 damage_type。
    部分伤害同时属于两种技能类型（如千冶天赋触发的战技：既按战技施放、
    又被视为追加攻击），用 secondary_skill_type 标注第二种类型。
    """

    value: float
    skill_type: SkillType
    damage_type: DamageType
    element: str = ""
    target_id: str = ""
    secondary_skill_type: SkillType | None = None  # 同时属于的第二种技能类型（无则 None）


@dataclass
class ActionLog:
    """单次行动日志（用于 UI 展示）。"""

    av: float                          # 行动者当时的 AV（单位自身）
    total_av: float                    # 战斗累计总行动值
    actor_id: str
    actor_name: str
    action_type: str                   # "normal"/"skill"/"ultra"/"monster"/"aha_moment"/"follow_up"/...
    target_id: str = ""
    damages: list[float] = field(default_factory=list)  # 每段伤害
    damage_records: list[DamageRecord] = field(default_factory=list)  # 每段伤害明细（技能类型×伤害类型）
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
    # 角色技能模块（unit_id → 模块实例），由 setup() 按 char.char_id 挂载
    char_modules: dict[str, CharacterModule] = field(default_factory=dict)
    # advance_av() 已推进到的行动者（手动推进键幂等标记；交互模式用）
    pending_av_actor: str | None = None
    # 行动条倒计时单位（倒计时 unit_id → 所属角色 unit_id）
    # 如千冶无量忿怒倒计时：倒计时行动时触发模块 on_countdown（结界解除）
    countdown_units: dict[str, str] = field(default_factory=dict)
    # 行动令牌：每次技能施放（_resolve_skill）递增。
    # 一次行动内的所有命中（主伤害 + 模块 on_skill_end 追击链）共享同一令牌，
    # 供模块按"行动"粒度去重（如千冶天赋"每次攻击 +1 充能"——不死途终结技
    # 后的强化追打/婪酣追打链整体视为一次行动）。模块可用 begin_new_action()
    # 主动开启新行动（如千冶天赋额外施放的战技为独立行动）。
    action_token: int = 0

    def setup(self) -> None:
        """战斗初始化。"""
        # SP
        self.sp = SkillPoint(initial=self.initial_sp)

        # 初始能量（freesr sp_value，钳制到能量上限；默认 0 保持原行为）
        for char in self.characters:
            char.energy = min(char.initial_energy, char.base_stats.energy_max)

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
            spd = enemy.speed
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

        # 角色技能模块挂载（按 char.char_id 查注册表）
        self._init_char_modules()
        self.pending_av_actor = None

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
        """阿哈加入行动条（一场战斗仅召唤最先的一只）。"""
        elation_chars = [c for c in self.characters if c.is_elation]
        if not elation_chars:
            return
        # 若阿哈已在行动条上，则不重复召唤
        if self.aha_entry is not None:
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

    # ── 行动条倒计时 ──────────────────────────────────────

    def add_countdown(
        self,
        owner: CharacterUnit,
        *,
        speed: float,
        name: str = "倒计时",
    ) -> str:
        """在行动序列上插入倒计时单位（如千冶无量忿怒倒计时）。

        倒计时固定速度（如 70），回合开始时触发所属角色模块的 on_countdown
        （结界解除等），随后从行动条移除。同角色已有倒计时时先移除旧的
        （刷新位置）。

        Args:
            owner: 所属角色
            speed: 倒计时速度
            name: 显示名

        Returns: 倒计时单位 ID
        """
        unit_id = f"__countdown_{owner.unit_id}__"
        self._remove_countdown(unit_id)
        self.countdown_units[unit_id] = owner.unit_id
        self.action_queue.add(ActionEntry(
            unit_id=unit_id,
            name=name,
            speed=speed,
            current_av=AV_PER_ACTION / speed,
            is_monster=False,
        ))
        return unit_id

    def _remove_countdown(self, unit_id: str) -> None:
        """从行动条移除倒计时单位。"""
        if unit_id in self.countdown_units:
            self.action_queue.remove(unit_id)
            del self.countdown_units[unit_id]

    def is_auto_unit(self, actor: ActionEntry) -> bool:
        """该行动者是否自动行动（怪物/阿哈/倒计时），无需玩家选择技能。"""
        return (
            actor.is_monster
            or actor.unit_id == "__aha__"
            or actor.unit_id in self.countdown_units
        )

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
            # 累计总行动值（本次行动消耗的 AV = 行动者当前 AV，一次性模式自动推进）
            self.total_av += actor.current_av

            # 阿哈时刻
            if actor.unit_id == "__aha__":
                self._trigger_aha_moment()
                continue

            # 倒计时（如无量忿怒倒计时）：触发所属模块 on_countdown 后移除
            if actor.unit_id in self.countdown_units:
                self._countdown_act(actor)
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

    # ── 交互模式：步进 / 终结技插队 / 快照回溯 ────────

    def step(self, action: PlayerAction | None = None) -> ActionLog | None:
        """执行一步模拟（交互模式用）。

        - 当前行动者是怪物/阿哈：自动行动，忽略 action 参数
        - 当前行动者是角色：使用 action 执行操作（为 None 时用默认逻辑）

        Returns: 本次行动的 ActionLog；战斗已结束则返回 None
        """
        if self.total_av >= self.max_av or self.current_turn >= self.max_turns:
            return None
        if not self.action_queue.entries:
            return None

        actor = self.action_queue.next_actor()
        if actor.current_av > 10000:
            return None

        self.current_turn += 1
        # 交互模式：时间推进由 advance_av()（手动推进键）负责，行动本身不推进

        # 阿哈时刻
        if actor.unit_id == "__aha__":
            self._trigger_aha_moment()
            return self.logs[-1] if self.logs else None

        # 倒计时（如无量忿怒倒计时）：触发所属模块 on_countdown 后移除
        if actor.unit_id in self.countdown_units:
            self._countdown_act(actor)
            return self.logs[-1] if self.logs else None

        # 怪物行动
        if actor.is_monster:
            self._monster_act(actor)
            return self.logs[-1] if self.logs else None

        # 角色行动
        char = self._get_character(actor.unit_id)
        if char is None:
            self.action_queue.advance()
            return None

        if action is None:
            action = self._default_action(char)

        return self._character_act(char, action, actor)

    def execute_ultra(self, char_index: int) -> ActionLog | None:
        """释放终结技（插队，不推进行动队列，不消耗回合）。

        插队位置 = 当前时间（total_av）：交互模式中"行动后插队"停在行动者位置，
        "轮到时插队"在手动推进（advance_av）之后位于下个行动者的位置。

        Args:
            char_index: 角色在队伍中的位置（0-3）

        Returns: 终结技的 ActionLog；能量不足或角色不存在则返回 None
        """
        if char_index < 0 or char_index >= len(self.characters):
            return None
        char = self.characters[char_index]

        # 找到终结技
        skill: Skill | None = None
        for s in char.skills.values():
            if s.skill_type == SkillType.ULTRA:
                skill = s
                break
        if skill is None:
            return None

        # 技能解析钩子（同回合行动）：无量忿怒下终结技切换为强化版等
        resolved = self._resolve_skill_override(char, SkillType.ULTRA, skill)
        if resolved is None:
            return None
        skill = resolved

        # 检查能量
        energy_cost = skill.energy_cost or self._get_energy_cost(char, SkillType.ULTRA)
        if char.energy < energy_cost:
            return None

        target_id = self.enemies[0].unit_id if self.enemies else ""
        action = PlayerAction(
            unit_id=char.unit_id,
            skill_type=SkillType.ULTRA,
            target_id=target_id,
        )

        return self._resolve_skill(char, skill, action, entry=None, is_turn=False)

    def snapshot(self) -> dict:
        """保存当前完整状态快照（用于交互模式回溯）。"""
        return {
            "characters": copy.deepcopy(self.characters),
            "enemies": copy.deepcopy(self.enemies),
            "action_queue": copy.deepcopy(self.action_queue),
            "sp": copy.deepcopy(self.sp),
            "logs": copy.deepcopy(self.logs),
            "total_damage": self.total_damage,
            "total_av": self.total_av,
            "current_turn": self.current_turn,
            "aha_count": self.aha_count,
            "aha_entry": copy.deepcopy(self.aha_entry),
            "char_modules": copy.deepcopy(self.char_modules),
            "pending_av_actor": self.pending_av_actor,
            "countdown_units": dict(self.countdown_units),
            "action_token": self.action_token,
        }

    def restore(self, snap: dict) -> None:
        """从快照恢复状态。"""
        self.characters = copy.deepcopy(snap["characters"])
        self.enemies = copy.deepcopy(snap["enemies"])
        self.action_queue = copy.deepcopy(snap["action_queue"])
        self.sp = copy.deepcopy(snap["sp"])
        self.logs = copy.deepcopy(snap["logs"])
        self.total_damage = snap["total_damage"]
        self.total_av = snap["total_av"]
        self.current_turn = snap["current_turn"]
        self.aha_count = snap["aha_count"]
        self.aha_entry = copy.deepcopy(snap["aha_entry"])
        self.char_modules = copy.deepcopy(snap.get("char_modules", {}))
        self.pending_av_actor = snap.get("pending_av_actor")
        self.countdown_units = dict(snap.get("countdown_units", {}))
        self.action_token = snap.get("action_token", 0)

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
        # 战技不消耗 SP 的角色（如千冶）不受 SP 限制
        skill = get_skill_by_type(char.skills, SkillType.SKILL)
        if skill is not None and skill.sp_cost <= 0:
            return PlayerAction(
                unit_id=char.unit_id,
                skill_type=SkillType.SKILL,
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
            return None

        # 技能解析钩子：模块可替换技能（如千冶无量忿怒下普攻/终结技强化版）
        # 或返回 None 拒绝施放（如千冶非无量忿怒/生命≤1 时无法施放战技）
        resolved = self._resolve_skill_override(char, action.skill_type, skill)
        if resolved is None:
            # 技能无效：仍消耗回合，不结算，返回"无法施放"日志
            # （避免与"战斗结束"混淆——step() 返回 None 会被 UI 当作结束）
            char.buff_mgr.tick_turn_end()
            char.buff_mgr.end_turn()
            self.action_queue.advance()
            log = ActionLog(
                av=entry.current_av,
                total_av=self.total_av,
                actor_id=char.unit_id,
                actor_name=char.name,
                action_type=action.skill_type.value.lower(),
                sp_after=self.sp.current,
                energy_after=char.energy,
                notes="无法施放（技能受限）",
            )
            self.logs.append(log)
            return log
        skill = resolved

        return self._resolve_skill(char, skill, action, entry, is_turn=True)

    def _resolve_skill_override(
        self,
        char: CharacterUnit,
        skill_type: SkillType,
        skill: Skill,
    ) -> Skill | None:
        """技能解析钩子：遍历模块，首个"响应"的模块决定实际技能。

        on_resolve_skill(sim, char, skill_type, skill) 返回：
        - 原 skill 对象 → 不参与，继续下一个模块
        - 新 Skill → 替换（如千冶无量忿怒下普攻/终结技强化版）
        - None → 拒绝施放（如千冶无法施放战技：回合照常消耗，无结算）
        """
        for module in self.char_modules.values():
            fn = getattr(module, "on_resolve_skill", None)
            if not callable(fn):
                continue  # 模块未实现该钩子，不参与
            resolved = fn(self, char, skill_type, skill)
            if resolved is None:
                return None  # 模块明确拒绝施放
            if resolved is not skill:
                return resolved  # 模块替换技能
        return skill

    def _resolve_skill(
        self,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        entry: ActionEntry | None,
        is_turn: bool = True,
    ) -> ActionLog:
        """结算技能效果（SP/能量、伤害、削韧、buff）。

        Args:
            char: 行动角色
            skill: 使用的技能
            action: 玩家操作
            entry: 行动条目（终结技插队时为 None）
            is_turn: True=正常回合行动（推进队列、回合管理）；
                     False=终结技插队（不推进队列、不管理回合）
        """
        # 新行动：令牌递增（本行动主伤害与模块追击链共享）
        self.action_token += 1
        # SP / 能量结算
        if skill.sp_cost > 0:
            self.sp.consume(skill.sp_cost)
        elif skill.sp_cost < 0:
            self.sp.recover(-skill.sp_cost)
        if skill.energy_cost > 0:
            char.energy = max(0, char.energy - skill.energy_cost)
        # 行动回复能量（能量恢复效率乘区：回复量 × (1 + energy_regen)）
        # - 正常回合：真实技能用解析出的回复值（如普攻 20），预设为 0 时回 20
        # - 终结技插队：仅回复技能自带回能（如不死途 5）；预设终结技无回能则不回
        if is_turn:
            recover = skill.energy_recover or 20
        elif skill.skill_type == SkillType.ULTRA:
            recover = skill.energy_recover
        else:
            recover = 0.0
        if recover:
            regen = char.final_stats().energy_regen
            char.energy = min(
                char.base_stats.energy_max,
                char.energy + recover * (1 + regen),
            )

        # 目标
        target = self._get_enemy(action.target_id) if action.target_id else (
            self.enemies[0] if self.enemies else None
        )

        log = ActionLog(
            av=entry.current_av if entry else 0,
            total_av=self.total_av,
            actor_id=char.unit_id,
            actor_name=char.name,
            action_type=action.skill_type.value.lower(),
            target_id=target.unit_id if target else "",
            sp_after=self.sp.current,
            energy_after=char.energy,
            notes=action.notes,
        )

        # 技能释放钩子（模块在此标记目标、追加伤害/回 SP 等，需在伤害结算前）
        for module in self.char_modules.values():
            self._dispatch_hook(module, "on_skill_cast", self, char, skill, action, target, log)

        # 主日志先入列：模块在 on_attack_hit / on_skill_end 中创建的追加攻击日志
        # 自然排在本行动之后（damages 等字段仍可继续写入，列表是引用）
        self.logs.append(log)

        # 计算伤害
        if target:
            # 冻结本次行动的分发令牌：模块在 on_attack_hit 内 begin_new_action()
            # 会修改 sim.action_token（如追打开启新行动），本体命中的去重键
            # 必须用冻结值，否则会被中途新增的令牌误判为"同行动"
            hit_token = self.action_token
            for effect in skill.effects:
                damage = self._calc_skill_damage(char, effect, target)
                log.damages.append(damage)
                log.total_damage += damage
                log.damage_records.append(
                    DamageRecord(
                        value=damage,
                        skill_type=skill.skill_type,
                        damage_type=effect.damage_type,
                        element=effect.element or char.element,
                        target_id=target.unit_id,
                    )
                )
                self.total_damage += damage

                # 削韧
                if effect.toughness_damage > 0:
                    broken = target.reduce_toughness(
                        effect.toughness_damage, effect.element or char.element
                    )
                    if broken:
                        log.enemy_broken = True
                        break_dmg = self._calc_break_damage(char, target)
                        log.damages.append(break_dmg)
                        log.total_damage += break_dmg
                        log.damage_records.append(
                            DamageRecord(
                                value=break_dmg,
                                skill_type=skill.skill_type,
                                damage_type=DamageType.BREAK,
                                element=char.element,
                                target_id=target.unit_id,
                            )
                        )
                        self.total_damage += break_dmg

                # buff 触发（攻击命中）
                char.buff_mgr.tick_attack()
                target.buff_mgr.tick_attack()

                # 攻击命中钩子（模块在此判定天赋追加攻击等）
                # 传冻结的 hit_token：分发循环内模块 begin_new_action 修改
                # sim.action_token 不影响本次命中的去重键
                for module in self.char_modules.values():
                    self._dispatch_hook(
                        module, "on_attack_hit",
                        self, char, skill, target, effect, damage, log, hit_token,
                    )

        # NEXT_ATTACK 类型 buff 失效
        char.buff_mgr.tick_attack()

        if is_turn:
            # 回合结束
            char.buff_mgr.tick_turn_end()
            char.buff_mgr.end_turn()

        # 技能结算钩子（模块在此触发终结技强化链等；其创建的追加攻击日志排在本日志之后）
        for module in self.char_modules.values():
            self._dispatch_hook(module, "on_skill_end", self, char, skill, action, target, log)

        if is_turn:
            self.action_queue.advance()

        return log

    def _calc_skill_damage(
        self,
        char: CharacterUnit,
        effect: SkillEffect,
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

        # 防御上下文（减防来自角色模块写入的 target.def_reduce）
        def_ctx = DefenseContext(
            attacker_level=char.level,
            defender_level=target.level,
            defender_defense=0,  # 怪物防御暂未建模
            def_reduce=target.def_reduce,
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
            # 面板增伤已由 attacker_stats.dmg_bonus 带入，此处为技能额外增伤（默认 0）
            dmg_bonus=0.0,
            # 易伤取自目标（模块增量式维护，如千冶【煞火缠身】受伤+30%）
            vulnerability=target.vulnerability,
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
            def_reduce=target.def_reduce,
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

    # ── 角色技能模块（事件钩子分发）─────────────────────────

    def _init_char_modules(self) -> None:
        """按 char.char_id 查注册表实例化角色技能模块并触发战斗开始钩子。"""
        # 延迟导入：characters 包导入 ashveil 触发注册，避免模块加载时循环依赖
        from .characters import get_module_cls

        self.char_modules = {}
        for char in self.characters:
            if not char.char_id:
                continue
            cls = get_module_cls(char.char_id)
            if cls is None:
                continue
            module = cls()
            self.char_modules[char.unit_id] = module
            self._dispatch_hook(module, "on_battle_start", self, char)

    def _module_for(self, char: CharacterUnit) -> CharacterModule | None:
        """按单位 ID 取角色模块实例。"""
        return self.char_modules.get(char.unit_id)

    def _dispatch_hook(self, module: CharacterModule, hook: str, *args: Any) -> Any:
        """分发事件钩子（模块未实现则跳过），返回钩子返回值（无实现返回 None）。"""
        fn = getattr(module, hook, None)
        if callable(fn):
            return fn(*args)
        return None

    # ── 模块可用的公共 API ─────────────────────────────────

    def deal_damage(
        self,
        attacker: CharacterUnit,
        target: EnemyState,
        effect: SkillEffect,
        *,
        skill_type: SkillType = SkillType.FOLLOW_UP,
        secondary_skill_type: SkillType | None = None,
        log: ActionLog | None = None,
    ) -> float:
        """公共打伤害入口（角色模块用）。

        复用技能伤害/击破伤害结算路径，记录 DamageRecord（技能类型×伤害类型），
        累加 log 与本模拟器总伤害，并触发 on_attack_hit 钩子（含击破结算后）。

        Args:
            attacker: 攻击角色
            target: 目标敌人
            effect: 伤害效果段（倍率/削韧/属性）
            skill_type: 本次伤害的技能类型（默认追加攻击）
            secondary_skill_type: 同时属于的第二种技能类型
                （如千冶天赋触发的战技：主类型追加攻击，同时是战技）
            log: 要写入的日志（模块自建日志时传入；None 则不记录日志）
        """
        damage = self._calc_skill_damage(attacker, effect, target)

        if log is not None:
            log.damages.append(damage)
            log.total_damage += damage
            log.damage_records.append(
                DamageRecord(
                    value=damage,
                    skill_type=skill_type,
                    damage_type=effect.damage_type,
                    element=effect.element or attacker.element,
                    target_id=target.unit_id,
                    secondary_skill_type=secondary_skill_type,
                )
            )
        self.total_damage += damage

        # 削韧与击破
        if effect.toughness_damage > 0:
            broken = target.reduce_toughness(
                effect.toughness_damage, effect.element or attacker.element
            )
            if broken:
                log_damage = log if log is not None else None
                break_dmg = self._calc_break_damage(attacker, target)
                if log_damage is not None:
                    log_damage.damages.append(break_dmg)
                    log_damage.total_damage += break_dmg
                    log_damage.damage_records.append(
                        DamageRecord(
                            value=break_dmg,
                            skill_type=skill_type,
                            damage_type=DamageType.BREAK,
                            element=attacker.element,
                            target_id=target.unit_id,
                        )
                    )
                    log_damage.enemy_broken = True
                self.total_damage += break_dmg

        # 攻击命中钩子（模块可响应，如天赋追加攻击判定；skill 非模块发起时为 None）
        # 追加攻击等独立行动使用当前 action_token（begin_new_action 已生效）
        attacker.buff_mgr.tick_attack()
        target.buff_mgr.tick_attack()
        for module in self.char_modules.values():
            self._dispatch_hook(
                module, "on_attack_hit",
                self, attacker, None, target, effect, damage, log, self.action_token,
            )

        return damage

    def make_follow_up_log(
        self,
        actor: CharacterUnit,
        target: EnemyState,
        *,
        notes: str = "",
        action_type: str = "follow_up",
    ) -> ActionLog:
        """创建行动日志（不推进队列、不管理回合）。

        默认 action_type="follow_up"（追加攻击）；秘技等进战效果可传其他类型。
        av=0（无行动消耗），记录当前 SP/能量快照。
        """
        log = ActionLog(
            av=0,
            total_av=self.total_av,
            actor_id=actor.unit_id,
            actor_name=actor.name,
            action_type=action_type,
            target_id=target.unit_id,
            sp_after=self.sp.current,
            energy_after=actor.energy,
            notes=notes,
        )
        self.logs.append(log)
        return log

    def advance_av(self) -> float:
        """交互模式：手动推进时间到下一个行动者的位置（如 200 → 250）。

        幂等：已推进到当前行动者时再次调用不重复推进。
        角色释放普攻/战技后时间停在该行动者位置（行动后插队 = 该位置），
        按推进键后才轮到下个行动者（轮到时插队 = 新位置）。

        Returns: 本次推进的 AV（未推进返回 0）
        """
        if not self.action_queue.entries:
            return 0.0
        actor = self.action_queue.next_actor()
        if self.pending_av_actor == actor.unit_id:
            return 0.0  # 已推进到该行动者
        self.total_av += actor.current_av
        self.pending_av_actor = actor.unit_id
        return actor.current_av

    def begin_new_action(self) -> None:
        """模块主动开启新行动（行动令牌 +1）。

        用于把后续命中标记为独立行动（如千冶天赋额外施放的战技
        "视为追加攻击"，是一次新的攻击行动，触发天赋充能计数）。
        """
        self.action_token += 1

    def recover_energy(self, char: CharacterUnit, amount: float, *, fixed: bool = False) -> float:
        """回复角色能量（钳制到能量上限），返回实际回复量。

        Args:
            amount: 回复量
            fixed: 固定回能（游戏描述带"固定"字样，如不死途天赋 8 点，
                   不受能量恢复效率影响）；普通回能 ×(1+energy_regen)
        """
        before = char.energy
        if fixed:
            actual = amount
        else:
            actual = amount * (1 + char.final_stats().energy_regen)
        char.energy = min(char.base_stats.energy_max, char.energy + actual)
        return char.energy - before

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

        # 怪物行动钩子（模块在此做敌方回合计时，如千冶【煞火缠身】剩余回合 -1）
        for module in self.char_modules.values():
            self._dispatch_hook(module, "on_enemy_act", self, enemy, log)

        self.action_queue.advance()

    def _countdown_act(self, entry: ActionEntry) -> None:
        """倒计时行动：触发所属角色模块的 on_countdown（结界解除等）后移除。"""
        owner_id = self.countdown_units.get(entry.unit_id, "")
        owner = self._get_character(owner_id) if owner_id else None

        log = ActionLog(
            av=entry.current_av,
            total_av=self.total_av,
            actor_id=entry.unit_id,
            actor_name=entry.name,
            action_type="countdown",
            notes="结界解除" if owner is not None else "",
        )
        self.logs.append(log)

        if owner is not None:
            module = self._module_for(owner)
            self._dispatch_hook(module, "on_countdown", self, owner, log)

        self.action_queue.advance()
        self._remove_countdown(entry.unit_id)

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
            notes=f"笑点 {laugh_before}",
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

        # 阿哈留在行动条上：用 advance() 正常推进 AV
        # （所有单位 AV 减去本次消耗值，阿哈 AV 重置）
        self.action_queue.advance()
        self.logs.append(log)
