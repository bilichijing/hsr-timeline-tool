"""遗器套装：生命的翁瓦克（id=308）。

2件：能量恢复效率提高 #1；速度 ≥ #2 时，进入战斗立刻行动提前 #3。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
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
        owner.buff_mgr.add(Buff(
            id="relic308_energy_regen",
            name="翁瓦克·回能",
            stat="energy_regen",
            value=_param(owner, 1, 0.05),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        if owner.final_stats().spd >= _param(owner, 2, 120):
            sim.action_queue.apply_pull(owner.unit_id, _param(owner, 3, 0.40))
