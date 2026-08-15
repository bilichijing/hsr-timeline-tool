"""光锥：灼尽炼狱的新骸（id=23059）。

叠影效果：
- 装备者生命上限提高 #1。
- 装备者回合开始时固定恢复 #2 点能量，每场战斗触发 1 次。
- 装备者施放战技攻击后，使目标陷入【炼狱】持续 #3 回合。
- 【炼狱】：目标受到的暴击伤害提高 #4，受到来自装备者的暴击伤害额外提高 #5。

暴击受伤加成写入 EnemyState.crit_dmg_taken / crit_dmg_taken_by_unit，
供当前/未来伤害结算的 crit_dmg 字段使用。
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

LC_ID = "23059"
HP_BUFF_ID = "lc23059_hp_pct"
PURGATORY_NAME = "炼狱"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    params = getattr(owner, "lightcone_params", None) or []
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class BlazeRebornModule(LightconeModule):
    CHAR_ID = LC_ID

    owner_unit_id: str = ""
    energy_triggered: bool = False
    # {enemy_unit_id: (remaining_turns, base_contrib, owner_extra_contrib)}
    targets: dict[str, tuple[int, float, float]] = {}

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.owner_unit_id = owner.unit_id
        self.energy_triggered = False
        self.targets = {}
        owner.buff_mgr.add(Buff(
            id=HP_BUFF_ID,
            name="淬炼·生命上限",
            stat="hp_pct",
            value=_param(owner, 1, 0.30),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        # 永久生命上限在 setup() 期间挂载，同步刷新当前生命为满血
        owner.current_hp = owner.final_stats().hp

    def on_turn_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        if self.energy_triggered:
            return
        self.energy_triggered = True
        sim.recover_energy(owner, _param(owner, 2, 20), fixed=True)

    def on_skill_end(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        if skill.skill_type != SkillType.SKILL or target is None or target.is_dead:
            return
        self._apply_purgatory(owner, target)

    def on_enemy_act(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        enemy: EnemyState,
        log: ActionLog | None,
    ) -> None:
        if enemy.unit_id not in self.targets:
            return
        turns, base_part, extra_part = self.targets[enemy.unit_id]
        turns -= 1
        if turns <= 0:
            self._remove_contrib(enemy, base_part, extra_part)
            self.targets.pop(enemy.unit_id, None)
        else:
            self.targets[enemy.unit_id] = (turns, base_part, extra_part)

    def on_enemy_dead(self, sim: BattleSimulator, owner: CharacterUnit, enemy: EnemyState) -> None:
        state = self.targets.pop(enemy.unit_id, None)
        if state is not None:
            self._remove_contrib(enemy, state[1], state[2])

    def enemy_buffs(self, sim: BattleSimulator, enemy: EnemyState) -> list[tuple[str, str]]:
        state = self.targets.get(enemy.unit_id)
        if state is None:
            return []
        turns, base_part, extra_part = state
        return [(
            PURGATORY_NAME,
            f"受到暴击伤害提高 {base_part * 100:.1f}%、"
            f"受到装备者暴击伤害额外提高 {extra_part * 100:.1f}%，"
            f"剩余 {turns} 个敌方回合",
        )]

    def _apply_purgatory(self, owner: CharacterUnit, target: EnemyState) -> None:
        base_part = _param(owner, 4, 0.30)
        extra_part = _param(owner, 5, 0.30)
        turns = int(_param(owner, 3, 2))

        old = self.targets.get(target.unit_id)
        if old is not None:
            self._remove_contrib(target, old[1], old[2])
        target.crit_dmg_taken += base_part
        old_extra = target.crit_dmg_taken_by_unit.get(owner.unit_id, 0.0)
        target.crit_dmg_taken_by_unit[owner.unit_id] = old_extra + extra_part
        self.targets[target.unit_id] = (turns, base_part, extra_part)

    def _remove_contrib(self, target: EnemyState, base_part: float, extra_part: float) -> None:
        target.crit_dmg_taken = max(0.0, target.crit_dmg_taken - base_part)
        if self.owner_unit_id in target.crit_dmg_taken_by_unit:
            target.crit_dmg_taken_by_unit[self.owner_unit_id] = max(
                0.0,
                target.crit_dmg_taken_by_unit.get(self.owner_unit_id, 0.0) - extra_part,
            )
