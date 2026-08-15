"""遗器套装：千星荟萃之城（id=326）。

2件：装备者施放追加攻击时，攻击力提高 #1，持续 #2 回合。
当敌方目标被消灭时，我方全体本场战斗暴击伤害提高 #3，该效果无法叠加。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from ..skill import SkillType
from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit, EnemyState

SET_ID = "326"
ATK_BUFF_ID = "relic326_follow_up_atk"
CRIT_BUFF_ID = "relic326_team_crit"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get("2", [])
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class CityModule(RelicSetModule):
    CHAR_ID = SET_ID

    kill_triggered: bool = False

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.kill_triggered = False
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return

    def on_attack_hit(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        attacker: CharacterUnit,
        skill_type: SkillType,
        target: EnemyState,
        damage: float,
        log,
        action_token: int,
    ) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        if attacker.unit_id != owner.unit_id or skill_type != SkillType.FOLLOW_UP:
            return
        owner.buff_mgr.add(Buff(
            id=ATK_BUFF_ID,
            name="千星城·攻击",
            stat="atk_pct",
            value=_param(owner, 1, 0.24),
            duration_type=BuffDuration.TURNS_SELF_START,
            duration_count=int(_param(owner, 2, 2)),
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))

    def on_enemy_dead(self, sim: BattleSimulator, owner: CharacterUnit, enemy: EnemyState) -> None:
        if self.kill_triggered or owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        self.kill_triggered = True
        value = _param(owner, 3, 0.12)
        for ally in sim.characters:
            ally.buff_mgr.add(Buff(
                id=CRIT_BUFF_ID,
                name="千星城·全队暴伤",
                stat="crit_dmg",
                value=value,
                duration_type=BuffDuration.PERMANENT,
                duration_count=-1,
                source_unit=owner.unit_id,
                stack_rule=StackRule.NO_STACK_SAME_NAME,
            ))
