"""遗器套装：生命的翁瓦克（id=308）。

2件：能量恢复效率提高 #1；速度 ≥ #2 时，进入战斗立刻行动提前 #3。

能量恢复效率属**无条件面板属性**，已计入局外面板
（`freesr.RELIC_SET_PANEL_BONUSES`），战斗内不再重复挂载；
本模块只负责“速度达标 → 进战拉条”这一条件效果。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit

SET_ID = "308"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get("2", [])
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class VonwacqModule(RelicSetModule):
    CHAR_ID = SET_ID

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        # 速度阈值判定使用最终速度（含面板里的这套回能/速度加成）
        if owner.final_stats().spd >= _param(owner, 2, 120):
            sim.action_queue.apply_pull(owner.unit_id, _param(owner, 3, 0.40))
