"""光锥效果模块基类。

光锥模块不直接修改角色技能，只通过战斗事件钩子挂载 buff/debuff：
- on_battle_start / on_turn_start / on_turn_end
- on_skill_cast / on_skill_end / on_post_skill
- on_attack_hit（可拿到本次伤害的 skill_type，用于识别追加攻击）
- on_enemy_act / on_enemy_dead / enemy_buffs

模块状态字段应为纯数据（deepcopy 安全），不持有 sim/char 引用。
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


class LightconeModule:
    """光锥模块基类。"""

    CHAR_ID: str = ""

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        """战斗开始。"""

    def on_turn_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        """装备者回合开始（buff tick 之后）。"""

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
        """装备者施放技能（伤害结算前）。"""

    def on_skill_end(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """装备者技能结算完成（含模块 on_skill_end 后）。"""

    def on_post_skill(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        """行动完全结束后。"""

    def on_memo_skill_end(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
    ) -> None:
        """装备者的忆灵技完整结算后（含全部目标伤害）。"""

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
        """任意角色攻击命中（is_attack=True）后。

        skill_type 可用于识别追加攻击（SkillType.FOLLOW_UP）。
        """

    def on_enemy_act(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        enemy: EnemyState,
        log: ActionLog | None,
    ) -> None:
        """敌方行动后：用于敌方回合计时类 debuff。"""

    def on_enemy_dead(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        enemy: EnemyState,
    ) -> None:
        """敌方死亡：清理模块对它的引用。"""

    def enemy_buffs(
        self,
        sim: BattleSimulator,
        enemy: EnemyState,
    ) -> list[tuple[str, str]]:
        """返回本光锥施加在该敌人身上的 debuff 列表。"""
        return []
