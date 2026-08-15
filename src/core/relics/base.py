"""遗器套装效果模块基类。

套装效果由模块在战斗事件中挂载 buff / 修改状态实现；
2 件与 4 件效果写在同一个模块中，模块按 owner.relic_set_counts 判断。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..simulator import (
        ActionLog,
        BattleSimulator,
        CharacterUnit,
        EnemyState,
        PlayerAction,
    )
    from ..skill import Skill, SkillType


class RelicSetModule:
    CHAR_ID: str = ""

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        """战斗开始。"""

    def on_turn_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        """装备者回合开始。"""

    def on_turn_end(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        """装备者回合结束。"""

    def on_skill_cast(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """装备者技能释放（伤害结算前）。"""

    def on_skill_end(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """装备者技能结算完成。"""

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
        """攻击命中。"""

    def on_enemy_act(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        enemy: EnemyState,
        log: ActionLog | None,
    ) -> None:
        """敌方行动。"""

    def on_enemy_dead(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        enemy: EnemyState,
    ) -> None:
        """敌方死亡。"""

    def enemy_buffs(
        self,
        sim: BattleSimulator,
        enemy: EnemyState,
    ) -> list[tuple[str, str]]:
        """返回本套装施加在该敌人身上的 debuff 列表。"""
        return []
