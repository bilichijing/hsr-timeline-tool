"""光锥：如果时间是一朵花（id=23038）。

叠影效果：
- 装备者暴击伤害提高 #1。
- 装备者施放追加攻击后，额外恢复 #2 点能量，并获得【谕示】持续 #3 回合。
- 持有【谕示】时，我方全体暴击伤害提高 #4。
- 进入战斗时，恢复 #5 点能量并获得【谕示】持续 #6 回合。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from ..skill import SkillType
from . import register
from .base import LightconeModule

if TYPE_CHECKING:
    from ..simulator import ActionLog, BattleSimulator, CharacterUnit, EnemyState, PlayerAction
    from ..skill import Skill

LC_ID = "23038"
OWNER_CRIT_BUFF_ID = "lc23038_owner_crit_dmg"
ORACLE_BUFF_ID = "lc23038_oracle"
TEAM_CRIT_BUFF_ID_PREFIX = "lc23038_team_crit_dmg"
ORACLE_NAME = "谕示"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    params = getattr(owner, "lightcone_params", None) or []
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class FlowerOfTimeModule(LightconeModule):
    CHAR_ID = LC_ID

    owner_unit_id: str = ""
    oracle_active: bool = False
    _counted_tokens: set[int] = set()

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.owner_unit_id = owner.unit_id
        self.oracle_active = False
        self._counted_tokens = set()
        # 第一句“暴击伤害提高”已计入局外面板，不在战斗中重复挂载
        sim.recover_energy(owner, _param(owner, 5, 21))
        self._grant_oracle(sim, owner, turns=int(_param(owner, 6, 2)))

    def on_turn_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        if self.oracle_active and not self._has_oracle(owner):
            self.oracle_active = False
            self._remove_team_crit(sim, owner)

    def on_attack_hit(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        attacker: CharacterUnit,
        skill_type: SkillType,
        target: EnemyState,
        damage: float,
        log: ActionLog | None,
        action_token: int,
    ) -> None:
        if attacker.unit_id != owner.unit_id or skill_type != SkillType.FOLLOW_UP:
            return
        if action_token in self._counted_tokens:
            return
        self._counted_tokens.add(action_token)
        sim.recover_energy(owner, _param(owner, 2, 12))
        self._grant_oracle(sim, owner, turns=int(_param(owner, 3, 2)))

    def _has_oracle(self, owner: CharacterUnit) -> bool:
        return any(b.id == ORACLE_BUFF_ID for b in owner.buff_mgr.buffs)

    def _grant_oracle(self, sim: BattleSimulator, owner: CharacterUnit, *, turns: int) -> None:
        owner.buff_mgr.add(Buff(
            id=ORACLE_BUFF_ID,
            name=ORACLE_NAME,
            stat="crit_dmg",
            value=0.0,
            duration_type=BuffDuration.TURNS_SELF_START,
            duration_count=turns,
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        self.oracle_active = True
        team_value = _param(owner, 4, 0.48)
        for ally in sim.characters:
            ally.buff_mgr.add(Buff(
                id=f"{TEAM_CRIT_BUFF_ID_PREFIX}_{owner.unit_id}",
                name="谕示·全队暴击伤害",
                stat="crit_dmg",
                value=team_value,
                duration_type=BuffDuration.PERMANENT,
                duration_count=-1,
                source_unit=owner.unit_id,
                stack_rule=StackRule.NO_STACK_SAME_NAME,
            ))

    def _remove_team_crit(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        buff_id = f"{TEAM_CRIT_BUFF_ID_PREFIX}_{owner.unit_id}"
        for ally in sim.characters:
            ally.buff_mgr.remove(buff_id)
