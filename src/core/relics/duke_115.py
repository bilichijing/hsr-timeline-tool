"""遗器套装：毁烬焚骨的大公（id=115）。

2件：追加攻击伤害提高 #1。
4件：追加攻击的每段命中使装备者攻击力提高 #1，最多 #2 层，持续 #3 回合；
下一次追加攻击行动开始时移除旧层数，同一行动多段命中不重复清空。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from ..skill import SkillType
from . import register
from .base import RelicSetModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit, EnemyState

SET_ID = "115"
ATK_BUFF_ID = "relic115_follow_up_atk"


def _param(owner: CharacterUnit, pieces: int, index: int, default: float) -> float:
    effects = owner.relic_set_effects.get(SET_ID, {})
    params = effects.get(str(pieces), [])
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class DukeModule(RelicSetModule):
    CHAR_ID = SET_ID

    current_follow_up_token: int | None = None
    stacks: int = 0

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.current_follow_up_token = None
        self.stacks = 0
        if owner.relic_set_counts.get(SET_ID, 0) < 2:
            return
        owner.buff_mgr.add(Buff(
            id="relic115_follow_up_dmg",
            name="大公·追加攻击",
            stat="follow_up_dmg_bonus",
            value=_param(owner, 2, 1, 0.20),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))

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
        if owner.relic_set_counts.get(SET_ID, 0) < 4:
            return
        if attacker.unit_id != owner.unit_id or skill_type != SkillType.FOLLOW_UP:
            return
        if self.current_follow_up_token != action_token:
            # 新的追加攻击行动：先移除旧层数
            owner.buff_mgr.remove(ATK_BUFF_ID)
            self.current_follow_up_token = action_token
            self.stacks = 0
        max_stacks = int(_param(owner, 4, 2, 8))
        self.stacks = min(max_stacks, self.stacks + 1)
        owner.buff_mgr.add(Buff(
            id=ATK_BUFF_ID,
            name="大公·愈战愈勇",
            stat="atk_pct",
            value=_param(owner, 4, 1, 0.06) * self.stacks,
            duration_type=BuffDuration.TURNS_SELF_START,
            duration_count=int(_param(owner, 4, 3, 3)),
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
