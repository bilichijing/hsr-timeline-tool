"""Buff 系统。

负责：
- 时效类型管理（永久 / N 回合 / 下次攻击后 / 一次性）
- 叠加规则（同名不叠刷新、同源不叠、最多 N 层）
- Buff 生效与失效

时效类型（开发文档 6.3）：
| 类型              | 失效时机             |
|-------------------|---------------------|
| PERMANENT         | 战斗结束             |
| TURNS_SELF_START  | 自身回合开始时 -1    |
| TURNS_SELF_END    | 自身回合结束时 -1    |
| NEXT_ATTACK       | 攻击命中后           |
| ONCE              | 触发后立即失效        |

叠加规则：
- NO_STACK_SAME_NAME   同名 buff 不叠加，刷新时效
- NO_STACK_SAME_SOURCE 同源 buff 不叠加
- STACK_LIMIT_N        最多叠 N 层
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .stats import StatBonus


class BuffDuration(Enum):
    """Buff 时效类型。"""

    PERMANENT = "permanent"               # 永久
    TURNS_SELF_START = "turns_self_start"  # 自身回合开始 -1
    TURNS_SELF_END = "turns_self_end"      # 自身回合结束 -1
    NEXT_ATTACK = "next_attack"            # 下次攻击后失效
    ONCE = "once"                          # 一次性触发


class StackRule(Enum):
    """Buff 叠加规则。"""

    NO_STACK_SAME_NAME = "no_stack_same_name"      # 同名不叠，刷新时效
    NO_STACK_SAME_SOURCE = "no_stack_same_source"  # 同源不叠
    STACK_LIMIT_N = "stack_limit_n"                # 最多叠 N 层
    STACK_ALWAYS = "stack_always"                  # 无限叠加


@dataclass
class Buff:
    """单个 Buff 实例。

    stat 字段对应 StatBonus 中的字段名（如 "atk_pct"、"dmg_bonus"）。
    value 为百分比小数（0.2 = +20%）或固定值（依字段而定）。
    """

    id: str                              # 唯一标识（如 "ailb1_atk_pct"）
    name: str                            # 显示名（如 "攻击力提升"）
    stat: str                            # 影响的属性（StatBonus 字段名）
    value: float                         # 数值
    duration_type: BuffDuration
    duration_count: int = 0              # 回合数（PERMANENT 时为 -1）
    source_unit: str = ""                # 来源单位 ID
    stack_rule: StackRule = StackRule.NO_STACK_SAME_NAME
    max_stacks: int = 1                  # STACK_LIMIT_N 时生效
    current_stacks: int = 1              # 当前层数
    # 是否为负面效果（debuff）。千冶【百炼骨】“解除自身所有负面效果”使用。
    is_debuff: bool = False
    # TURNS_SELF_END 特殊规则标志：
    # 若本 buff 是在自身回合内获得的，则获得它的这个回合结束时
    # 持续时间不会减少（首次 tick_turn_end 跳过扣减）。
    applied_in_self_turn: bool = False

    def to_bonus(self) -> StatBonus:
        """转换为 StatBonus（单层）。"""
        bonus = StatBonus()
        if hasattr(bonus, self.stat):
            setattr(bonus, self.stat, self.value * self.current_stacks)
        return bonus

    def is_expired(self) -> bool:
        """是否已过期。"""
        if self.duration_type == BuffDuration.PERMANENT:
            return False
        if self.duration_type == BuffDuration.ONCE:
            return self.duration_count <= 0
        return self.duration_count <= 0

    def tick_turn_start(self, unit_id: str) -> None:
        """单位回合开始时回调。"""
        if self.duration_type == BuffDuration.TURNS_SELF_START and self.source_unit == unit_id:
            self.duration_count -= 1

    def tick_turn_end(self, unit_id: str) -> None:
        """单位回合结束时回调。

        TURNS_SELF_END 特殊规则：若 applied_in_self_turn=True，
        表示本 buff 是在自身回合内获得的，本次回合结束跳过扣减，
        并清除标志（从下一回合开始正常扣减）。
        """
        if self.duration_type == BuffDuration.TURNS_SELF_END and self.source_unit == unit_id:
            if self.applied_in_self_turn:
                # 首次回合结束跳过扣减
                self.applied_in_self_turn = False
            else:
                self.duration_count -= 1

    def tick_attack(self, attacker_id: str) -> None:
        """攻击命中时回调（NEXT_ATTACK 类型失效）。"""
        if self.duration_type == BuffDuration.NEXT_ATTACK and self.source_unit == attacker_id:
            self.duration_count = 0


@dataclass
class BuffManager:
    """管理某个单位身上的所有 Buff。

    负责：
    - 添加 buff（处理叠加规则）
    - 时效递减（回合开始/结束、攻击命中）
    - 清除过期 buff
    - 汇总为 StatBonus

    TURNS_SELF_END 特殊规则：
    若 buff 在自身回合内获得，则获得 buff 的这个回合结束时
    持续时间不扣减。由 in_self_turn 标志驱动：
    - begin_turn() 置 True
    - add() 时若 in_self_turn=True，给 buff 打 applied_in_self_turn=True
    - end_turn() 置 False（注意 end_turn 在 tick_turn_end 之前调用，
      这样本次 tick 才能识别到 applied_in_self_turn 并跳过扣减）
    """

    unit_id: str
    buffs: list[Buff] = field(default_factory=list)
    in_self_turn: bool = False  # 当前是否处于自身回合内

    def begin_turn(self) -> None:
        """自身回合开始（标记 in_self_turn=True）。"""
        self.in_self_turn = True

    def add(self, buff: Buff) -> None:
        """添加 buff（按叠加规则处理）。

        若当前在自身回合内（in_self_turn=True），且 buff 为 TURNS_SELF_END 类型，
        则给 buff 打 applied_in_self_turn 标志，使其本次回合结束不扣减。
        """
        # 标记是否在自身回合内获得（仅对 TURNS_SELF_END 类型有意义）
        if self.in_self_turn and buff.duration_type == BuffDuration.TURNS_SELF_END:
            buff.applied_in_self_turn = True

        if buff.stack_rule == StackRule.STACK_ALWAYS:
            self.buffs.append(buff)
            return

        if buff.stack_rule == StackRule.STACK_LIMIT_N:
            existing = [b for b in self.buffs if b.id == buff.id]
            if existing:
                b0 = existing[0]
                if b0.current_stacks >= buff.max_stacks:
                    # 已满层：刷新时效，不增加层数
                    b0.duration_count = buff.duration_count
                    b0.duration_type = buff.duration_type
                    b0.applied_in_self_turn = buff.applied_in_self_turn
                else:
                    # 未满：层数 +1，刷新时效
                    b0.current_stacks += 1
                    b0.duration_count = buff.duration_count
                    b0.applied_in_self_turn = buff.applied_in_self_turn
            else:
                # 首次添加：current_stacks 不超过 max_stacks
                buff.current_stacks = min(1, buff.max_stacks)
                self.buffs.append(buff)
            return

        # NO_STACK_SAME_NAME / NO_STACK_SAME_SOURCE
        key_field = "id" if buff.stack_rule == StackRule.NO_STACK_SAME_NAME else "source_unit"
        key_val = getattr(buff, key_field)
        for i, b in enumerate(self.buffs):
            if getattr(b, key_field) == key_val and b.name == buff.name:
                # 已存在：刷新时效，取较大值
                b.duration_type = buff.duration_type
                b.duration_count = max(b.duration_count, buff.duration_count)
                b.value = max(b.value, buff.value)
                b.applied_in_self_turn = buff.applied_in_self_turn
                return
        self.buffs.append(buff)

    def remove(self, buff_id: str) -> None:
        """按 ID 移除 buff。"""
        self.buffs = [b for b in self.buffs if b.id != buff_id]

    def remove_by_name(self, name: str) -> None:
        """按名称移除 buff。"""
        self.buffs = [b for b in self.buffs if b.name != name]

    def remove_debuffs(self) -> int:
        """移除所有负面效果，返回移除数量。"""
        before = len(self.buffs)
        self.buffs = [b for b in self.buffs if not b.is_debuff]
        return before - len(self.buffs)

    def clear_expired(self) -> int:
        """清除过期 buff，返回清除数量。"""
        before = len(self.buffs)
        self.buffs = [b for b in self.buffs if not b.is_expired()]
        return before - len(self.buffs)

    def tick_turn_start(self) -> None:
        """自身回合开始时调用（在 begin_turn 之后）。"""
        for b in self.buffs:
            b.tick_turn_start(self.unit_id)
        self.clear_expired()

    def tick_turn_end(self) -> None:
        """自身回合结束时调用。

        会先处理 TURNS_SELF_END 的扣减（识别 applied_in_self_turn），
        然后 in_self_turn 标志由 end_turn() 在本方法之后清除。
        """
        for b in self.buffs:
            b.tick_turn_end(self.unit_id)
        self.clear_expired()

    def end_turn(self) -> None:
        """自身回合结束（在 tick_turn_end 之后调用，清除 in_self_turn 标志）。"""
        self.in_self_turn = False

    def tick_attack(self) -> None:
        """攻击命中时调用。"""
        for b in self.buffs:
            b.tick_attack(self.unit_id)
        self.clear_expired()

    def total_bonus(self) -> StatBonus:
        """汇总所有 buff 为 StatBonus。"""
        total = StatBonus()
        for b in self.buffs:
            total = total.add(b.to_bonus())
        return total

    def get_value(self, stat: str) -> float:
        """查询某属性的 buff 总加成。"""
        return getattr(self.total_bonus(), stat, 0.0)
