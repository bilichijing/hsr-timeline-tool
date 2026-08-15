"""光锥：一场谎言的终幕（id=23056）。

叠影效果：
- 装备者暴击率提高 #1。
- 战斗开始时或每累计施放 #2 次追加攻击，获得【影噬】持续 #3 回合。
- 【影噬】期间：装备者攻击力提高 #4，敌方全体受伤提高 #5。
- 同类效果无法叠加：全队该光锥的易伤只取一份。
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

LC_ID = "23056"
CRIT_BUFF_ID = "lc23056_crit_rate"
SHADOW_BUFF_ID = "lc23056_shadow_atk"
SHADOW_NAME = "影噬"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    params = getattr(owner, "lightcone_params", None) or []
    if 1 <= index <= len(params):
        return float(params[index - 1])
    return default


@register
class LieFinaleModule(LightconeModule):
    CHAR_ID = LC_ID

    owner_unit_id: str = ""
    follow_up_count: int = 0
    shadow_active: bool = False
    vuln_contribution: float = 0.0
    vuln_param: float = 0.20
    _counted_tokens: set[int] = set()

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.owner_unit_id = owner.unit_id
        self.follow_up_count = 0
        self.shadow_active = False
        self.vuln_contribution = 0.0
        self.vuln_param = _param(owner, 5, 0.20)
        self._counted_tokens = set()

        owner.buff_mgr.add(Buff(
            id=CRIT_BUFF_ID,
            name="吞没·暴击率",
            stat="crit_rate",
            value=_param(owner, 1, 0.18),
            duration_type=BuffDuration.PERMANENT,
            duration_count=-1,
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        self._grant_shadow(sim, owner)

    def on_turn_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        if self.shadow_active and not self._has_shadow(owner):
            self.shadow_active = False
            self._sync_all_shadow_vulns(sim)

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
        self.follow_up_count += 1
        if self.follow_up_count >= int(_param(owner, 2, 4)):
            self.follow_up_count = 0
            self._grant_shadow(sim, owner)

    def enemy_buffs(self, sim: BattleSimulator, enemy: EnemyState) -> list[tuple[str, str]]:
        if self.shadow_active and self.vuln_contribution > 0:
            return [(
                SHADOW_NAME,
                f"敌方全体受到伤害提高 {self.vuln_contribution * 100:.1f}%",
            )]
        return []

    def _has_shadow(self, owner: CharacterUnit) -> bool:
        return any(b.id == SHADOW_BUFF_ID for b in owner.buff_mgr.buffs)

    def _grant_shadow(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        owner.buff_mgr.add(Buff(
            id=SHADOW_BUFF_ID,
            name=SHADOW_NAME,
            stat="atk_pct",
            value=_param(owner, 4, 0.40),
            duration_type=BuffDuration.TURNS_SELF_START,
            duration_count=int(_param(owner, 3, 3)),
            source_unit=owner.unit_id,
            stack_rule=StackRule.NO_STACK_SAME_NAME,
        ))
        self.shadow_active = True
        self._sync_all_shadow_vulns(sim)

    def _sync_all_shadow_vulns(self, sim: BattleSimulator) -> None:
        for module in sim.lightcone_modules.values():
            if getattr(module, "CHAR_ID", "") == self.CHAR_ID:
                module._sync_vuln(sim)

    def _sync_vuln(self, sim: BattleSimulator) -> None:
        active = [
            m for m in sim.lightcone_modules.values()
            if getattr(m, "CHAR_ID", "") == self.CHAR_ID
            and getattr(m, "shadow_active", False)
        ]
        winner = min(active, key=lambda m: getattr(m, "owner_unit_id", "")) if active else None
        rate = self.vuln_param if winner is self else 0.0
        diff = rate - self.vuln_contribution
        self.vuln_contribution = rate
        for enemy in sim.enemies:
            enemy.vulnerability += diff
