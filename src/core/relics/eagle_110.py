"""遗器套装：晨昏交界的翔鹰（id=110）。

2件：风属性伤害提高 #1。
4件：装备者施放终结技后，自身行动提前 #1。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from ..skill import SkillType
from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import ActionLog, BattleSimulator, CharacterUnit, EnemyState, PlayerAction
    from ..skill import Skill

SET_ID = "110"


def _param(owner: CharacterUnit, pieces: int, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get(str(pieces), [])
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class EagleModule(RelicSetModule):
    CHAR_ID = SET_ID

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        owner.buff_mgr.add(Buff(
            id="relic110_wind_dmg",
            name="翔鹰·风伤",
            stat="elemental_dmg_bonus",
            element="Wind",
            value=_param(owner, 2, 1, 0.10),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))

    def on_skill_end(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 4:
            return
        if skill.skill_type != SkillType.ULTRA:
            return
        sim.action_queue.apply_pull(owner.unit_id, _param(owner, 4, 1, 0.25))
