"""战技点（SP）管理。

星铁战斗核心资源：
- 队伍共享，上限 5，初始 3
- 普攻 +1，战技 -1
- 某些技能可回复或消耗额外 SP
"""

from __future__ import annotations


class SkillPoint:
    """战技点管理器。"""

    MAX = 5
    INITIAL = 3

    def __init__(self, initial: int | None = None) -> None:
        self.current = initial if initial is not None else self.INITIAL

    def consume(self, amount: int = 1) -> bool:
        """消耗 SP，不足返回 False。"""
        if self.current < amount:
            return False
        self.current -= amount
        return True

    def recover(self, amount: int = 1) -> int:
        """回复 SP，返回实际回复量。"""
        before = self.current
        self.current = min(self.MAX, self.current + amount)
        return self.current - before

    def can_consume(self, amount: int = 1) -> bool:
        """检查是否足够消耗（不实际消耗）。"""
        return self.current >= amount

    def __repr__(self) -> str:
        return f"<SkillPoint {self.current}/{self.MAX}>"
