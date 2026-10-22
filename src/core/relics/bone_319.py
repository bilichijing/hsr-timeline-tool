"""遗器套装：谧宁拾骨地（id=319）。

2件：生命上限提高 #1；生命上限 ≥ #2 时，装备者暴击伤害提高 #3。
忆灵部分暂未建模（TODO）。

“生命上限提高”属无条件面板属性，已计入局外面板
（`freesr.RELIC_SET_PANEL_BONUSES`）；本模块只负责“生命上限达标 → 暴击伤害提高”
这一条件效果（阈值判定用含面板加成的最终生命上限）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit

SET_ID = "319"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get("2", [])
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class BoneModule(RelicSetModule):
    CHAR_ID = SET_ID

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        if owner.final_stats().hp >= _param(owner, 2, 5000):
            owner.buff_mgr.add(Buff(
                id="relic319_crit_dmg",
                name="拾骨地·暴击伤害",
                stat="crit_dmg",
                value=_param(owner, 3, 0.28),
                duration_type=BuffDuration.PERMANENT,
                duration_count=-1,
                source_unit=owner.unit_id,
                stack_rule=StackRule.NO_STACK_SAME_NAME,
            ))
