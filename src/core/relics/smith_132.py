"""遗器套装：叩问天工的名冶（id=132）。

2件：生命上限提高 #1。
4件：
- 装备者对处于防御力降低状态的敌方目标，暴击伤害提高 #1（接到 crit_dmg 字段）。
- 装备者攻击命中减防目标后，我方全体获得【助燃】#2 回合，伤害提高 #3，无法叠加；
  每次攻击行动最多触发一次，装备者施放攻击后可再次触发。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit, EnemyState

SET_ID = "132"
ASSIST_BUFF_ID = "relic132_assist"


def _param(owner: CharacterUnit, pieces: int, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get(str(pieces), [])
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class SmithModule(RelicSetModule):
    CHAR_ID = SET_ID

    # {enemy_unit_id: 本模块对 crit_dmg_taken_by_unit[owner] 的贡献}
    crit_contrib: dict[str, float] = {}
    _assist_tokens: set[int] = set()

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.crit_contrib = {}
        self._assist_tokens = set()
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        owner.buff_mgr.add(Buff(
            id="relic132_hp",
            name="名冶·生命",
            stat="hp_pct",
            value=_param(owner, 2, 1, 0.12),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        owner.current_hp = owner.final_stats().hp

    def on_attack_hit(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        attacker: CharacterUnit,
        skill_type,
        target: EnemyState,
        damage: float,
        log,
        action_token: int,
    ) -> None:
        if owner.relic_set_counts.get(SET_ID, 0) < 4:
            return
        if attacker.unit_id != owner.unit_id:
            return
        if target.def_reduce > 0:
            self._set_crit_part(owner, target)
            if action_token not in self._assist_tokens:
                self._assist_tokens.add(action_token)
                self._grant_assist(sim, owner)
        else:
            self._remove_crit_part(owner, target)

    def on_enemy_dead(self, sim: BattleSimulator, owner: CharacterUnit, enemy: EnemyState) -> None:
        self._remove_crit_part(owner, enemy)

    def _set_crit_part(self, owner: CharacterUnit, target: EnemyState) -> None:
        if self.crit_contrib.get(target.unit_id, 0.0) > 0:
            return
        part = _param(owner, 4, 1, 0.28)
        target.crit_dmg_taken_by_unit[owner.unit_id] = (
            target.crit_dmg_taken_by_unit.get(owner.unit_id, 0.0) + part
        )
        self.crit_contrib[target.unit_id] = part

    def _remove_crit_part(self, owner: CharacterUnit, target: EnemyState) -> None:
        part = self.crit_contrib.pop(target.unit_id, 0.0)
        if part <= 0:
            return
        target.crit_dmg_taken_by_unit[owner.unit_id] = max(
            0.0, target.crit_dmg_taken_by_unit.get(owner.unit_id, 0.0) - part,
        )

    def _grant_assist(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        value = _param(owner, 4, 3, 0.15)
        turns = int(_param(owner, 4, 2, 2))
        for ally in sim.characters:
            ally.buff_mgr.add(Buff(
                id=ASSIST_BUFF_ID,
                name="助燃",
                stat="dmg_bonus",
                value=value,
                duration_type=BuffDuration.TURNS_SELF_START,
                duration_count=turns,
                source_unit=ally.unit_id,
                stack_rule=StackRule.NO_STACK_SAME_NAME,
            ))
