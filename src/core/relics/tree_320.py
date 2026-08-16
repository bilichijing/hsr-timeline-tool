"""遗器套装：渊思寂虑的巨树（id=320）。

2件：速度提高 #1；速度 ≥ #2 / #3 时，装备者及其忆灵的治疗量提高
#4 / #5。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit

SET_ID = "320"
SPEED_BUFF_ID = "relic320_speed"
HEAL_BUFF_ID = "relic320_heal"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get("2", [])
    return float(params[index - 1]) if 1 <= index <= len(params) else default


@register
class TreeModule(RelicSetModule):
    CHAR_ID = SET_ID

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        owner.buff_mgr.add(Buff(
            id=SPEED_BUFF_ID, name="巨树·速度", stat="spd_pct",
            value=_param(owner, 1, 0.06),
            duration_type=BuffDuration.PERMANENT, duration_count=-1,
            source_unit=owner.unit_id, stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        self._sync_heal_bonus(owner)

    def on_turn_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self._sync_heal_bonus(owner)

    def _sync_heal_bonus(self, owner: CharacterUnit) -> None:
        owner.buff_mgr.remove(HEAL_BUFF_ID)
        speed = owner.final_stats().spd
        if speed >= _param(owner, 3, 180.0):
            value = _param(owner, 5, 0.20)
        elif speed >= _param(owner, 2, 135.0):
            value = _param(owner, 4, 0.12)
        else:
            return
        owner.buff_mgr.add(Buff(
            id=HEAL_BUFF_ID, name="巨树·治疗", stat="outgoing_heal",
            value=value, duration_type=BuffDuration.PERMANENT, duration_count=-1,
            source_unit=owner.unit_id, stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
