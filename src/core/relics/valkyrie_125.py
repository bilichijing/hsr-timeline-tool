"""遗器套装：烈阳惊雷的女武神（id=125）。

2件：速度提高 #1。
4件：装备者及其忆灵为装备者/忆灵以外的我方目标治疗后，装备者获得【甘霖】，
每回合最多触发 1 次，持续 #3 回合；【甘霖】期间速度提高 #1，我方全体
暴击伤害提高 #2，同类效果无法叠加。

2 件套属性属**无条件面板属性**，已计入局外面板
（`freesr.RELIC_SET_PANEL_BONUSES`），战斗内不再重复挂载；本模块只负责 4 件套【甘霖】。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit

SET_ID = "125"
GANLIN_SPEED_ID = "relic125_ganlin_speed"
GANLIN_CRIT_ID = "relic125_ganlin_crit"


def _param(owner: CharacterUnit, pieces: int, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get(str(pieces), [])
    return float(params[index - 1]) if 1 <= index <= len(params) else default


@register
class ValkyrieModule(RelicSetModule):
    CHAR_ID = SET_ID

    can_grant: bool = False

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        """2 件套（速度提高）已在局外面板，此处只重置【甘霖】触发状态。"""
        self.can_grant = True

    def on_turn_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.can_grant = True

    def on_heal(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        healer: CharacterUnit,
        target: CharacterUnit,
        amount: float,
        raw: float,
        actual: float,
        source: str,
    ) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 4:
            return
        if not self.can_grant or healer.unit_id != owner.unit_id:
            return
        if source not in ("hyacine", "memosprite"):
            return
        if target.unit_id == owner.unit_id:
            return
        self.can_grant = False
        turns = int(_param(owner, 4, 3, 2))
        speed_value = _param(owner, 4, 1, 0.06)
        crit_value = _param(owner, 4, 2, 0.15)
        owner.buff_mgr.add(Buff(
            id=GANLIN_SPEED_ID, name="甘霖", stat="spd_pct", value=speed_value,
            duration_type=BuffDuration.TURNS_SELF_START, duration_count=turns,
            source_unit=owner.unit_id, stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        for ally in sim.characters:
            ally.buff_mgr.add(Buff(
                id=GANLIN_CRIT_ID, name="甘霖·全队暴伤", stat="crit_dmg",
                value=crit_value,
                duration_type=BuffDuration.TURNS_SELF_START, duration_count=turns,
                source_unit=owner.unit_id, stack_rule=StackRule.NO_STACK_SAME_NAME,
            ))
