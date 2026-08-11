"""行动值（AV）系统。

星铁回合制核心：速度决定行动顺序。

基础公式：
    AV = 10000 / 速度

规则：
- 每个单位初始 AV = 10000 / 自身速度
- AV 最小的先行动
- 行动后行动者 AV 重置为 10000 / 速度，其余单位 AV 减去已消耗值
- 推条（延后）：AV += X × AV   （X 为比例，如 0.25 表示延后 25%）
- 拉条（提前）：AV -= X × AV   （下限 0）
"""

from __future__ import annotations

from dataclasses import dataclass, field

AV_PER_ACTION = 10000.0  # 满行动值（满条所需 AV）


@dataclass
class ActionEntry:
    """行动队列中的单个单位。"""

    unit_id: str            # 唯一标识（角色 id 或 "monster_1"）
    name: str               # 显示名
    speed: float            # 当前速度
    current_av: float       # 距离下次行动的 AV
    is_monster: bool = False

    def reset_av(self) -> None:
        """行动后重置 AV。"""
        self.current_av = AV_PER_ACTION / self.speed

    def __repr__(self) -> str:
        return f"<ActionEntry {self.name} spd={self.speed} av={self.current_av:.1f}>"


@dataclass
class ActionQueue:
    """行动队列：管理所有单位的行动顺序。

    实现要点：
    - next_actor() 返回 current_av 最小的单位
    - advance() 推进时间：所有单位 AV 减少，行动者重置
    - apply_push() / apply_pull() 修改指定单位的 AV
    """

    entries: list[ActionEntry] = field(default_factory=list)

    def add(self, entry: ActionEntry) -> None:
        """添加单位到队列。"""
        self.entries.append(entry)

    def remove(self, unit_id: str) -> None:
        """从队列移除单位。"""
        self.entries = [e for e in self.entries if e.unit_id != unit_id]

    def get(self, unit_id: str) -> ActionEntry | None:
        """按 ID 查找单位。"""
        for e in self.entries:
            if e.unit_id == unit_id:
                return e
        return None

    def next_actor(self) -> ActionEntry:
        """返回 AV 最小的行动者。

        并列时按 entries 顺序取第一个（稳定排序）。
        """
        if not self.entries:
            raise RuntimeError("行动队列为空")
        return min(self.entries, key=lambda e: e.current_av)

    def advance(self) -> tuple[ActionEntry, float]:
        """推进到下一个行动者行动。

        返回 (行动者, 本次消耗的 AV)。
        所有单位 AV 减去本次消耗值，行动者 AV 重置。
        """
        actor = self.next_actor()
        consumed = actor.current_av
        for e in self.entries:
            e.current_av -= consumed
        actor.reset_av()
        return actor, consumed

    def apply_push(self, unit_id: str, rate: float) -> None:
        """推条（延后）。

        Args:
            unit_id: 目标单位
            rate: 延后比例（0.25 = 延后 25% AV）
        """
        e = self.get(unit_id)
        if e is not None:
            e.current_av = e.current_av * (1 + rate)

    def apply_pull(self, unit_id: str, rate: float) -> None:
        """拉条（提前）。

        Args:
            unit_id: 目标单位
            rate: 提前比例（0.25 = 提前 25% AV），AV 下限 0
        """
        e = self.get(unit_id)
        if e is not None:
            e.current_av = max(0.0, e.current_av * (1 - rate))

    def update_speed(
        self,
        unit_id: str,
        new_speed: float,
        advance_rate: float = 0.0,
        delay_rate: float = 0.0,
    ) -> None:
        """更新单位速度，并按官方公式调整剩余 AV。

        官方公式（开发文档 6.1）：
            新行动值 = 原行动值 × 新基础行动值 / 原基础行动值
                      - 新基础行动值 × (提前% - 延后%)

        其中：
        - 基础行动值 = 10000 / 速度
        - 提前% / 延后% 为本次速度变化同时附带的推拉条比例（无则为 0）

        Args:
            unit_id: 目标单位
            new_speed: 新速度
            advance_rate: 提前比例（0.25 = 提前 25% AV），默认 0
            delay_rate: 延后比例（0.25 = 延后 25% AV），默认 0
        """
        e = self.get(unit_id)
        if e is None or new_speed <= 0:
            return
        old_speed = e.speed
        if old_speed <= 0:
            e.speed = new_speed
            e.reset_av()
            return
        old_base_av = AV_PER_ACTION / old_speed
        new_base_av = AV_PER_ACTION / new_speed
        new_av = (
            e.current_av * new_base_av / old_base_av
            - new_base_av * (advance_rate - delay_rate)
        )
        e.speed = new_speed
        e.current_av = max(0.0, new_av)

    def snapshot(self) -> list[tuple[str, str, float, float]]:
        """返回当前队列快照（用于 UI 显示）。"""
        return [
            (e.unit_id, e.name, e.speed, e.current_av)
            for e in sorted(self.entries, key=lambda x: x.current_av)
        ]
