"""光锥：愿虹光永驻天空（id=23042）。

叠影效果：
- 装备者速度提高 #1。
- 装备者施放普攻/战技/终结技时，消耗我方全体当前生命值 #2%，并累计消耗总量。
- 装备者忆灵下一次攻击后，对攻击目标额外造成一次等同于
  #6% 生命值消耗总量的忆灵属性附加伤害，随后清空消耗总量。
- 装备者忆灵施放忆灵技时，使敌方全体受到的伤害提高 #4，持续 #5 回合，
  同类效果无法叠加。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from ..damage import DamageType
from ..skill import SkillEffect, SkillType
from . import register
from .base import LightconeModule

if TYPE_CHECKING:
    from ..simulator import BattleSimulator, CharacterUnit, EnemyState
    from ..skill import Skill

LC_ID = "23042"
SPEED_BUFF_ID = "lc23042_speed"


def _param(owner: CharacterUnit, index: int, default: float) -> float:
    params = getattr(owner, "lightcone_params", None) or []
    return float(params[index - 1]) if 1 <= index <= len(params) else default


@register
class RainbowSkyModule(LightconeModule):
    CHAR_ID = LC_ID

    owner_unit_id: str = ""
    consumed_total: float = 0.0
    vuln_contribution: float = 0.0
    vuln_turns: int = 0

    def on_battle_start(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        self.owner_unit_id = owner.unit_id
        self.consumed_total = 0.0
        self.vuln_contribution = 0.0
        self.vuln_turns = 0
        # 第一句“速度提高”已计入局外面板，不在战斗中重复挂载

    def on_skill_cast(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        skill: Skill,
        action,
        target: EnemyState | None,
        log,
    ) -> None:
        if skill.skill_type not in (SkillType.NORMAL, SkillType.SKILL, SkillType.ULTRA):
            return
        ratio = _param(owner, 2, 0.01)
        total = 0.0
        # 消耗我方角色当前生命（最低保留 1）
        for ally in sim.characters:
            cost = ally.current_hp * ratio
            cost = min(cost, max(0.0, ally.current_hp - 1.0))
            ally.current_hp -= cost
            total += cost
        # 若装备者是小伊卡主人，也消耗忆灵当前生命（最低保留 1）
        hyacine = sim.char_modules.get(owner.unit_id)
        if hyacine is not None and getattr(hyacine, "memosprite_alive", False):
            memo_hp = getattr(hyacine, "memosprite_hp", 0.0)
            memo_max = getattr(hyacine, "memosprite_max_hp", 0.0)
            cost = memo_hp * ratio
            cost = min(cost, max(0.0, memo_hp - 1.0))
            hyacine.memosprite_hp = memo_hp - cost
            total += cost
        self.consumed_total += total

    def on_memo_skill_end(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        # 忆灵技使敌方全体受伤提高（同类不叠加）
        self._apply_vulnerability(sim, owner)
        # 附加伤害：对本次忆灵技命中的每个目标各触发一次
        if self.consumed_total <= 0:
            return
        base = self.consumed_total * _param(owner, 6, 2.5)
        effect = SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=1.0,
            fixed_base_value=base,
            toughness_damage=0,
            element="Wind",
        )
        for enemy in sim.enemies:
            sim.deal_damage(
                owner, enemy, effect,
                skill_type=SkillType.MEMO_DNSKILL, log=None,
                is_attack=False,
            )
        self.consumed_total = 0.0

    def on_enemy_act(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit,
        enemy: EnemyState,
        log,
    ) -> None:
        if self.vuln_turns <= 0:
            return
        self.vuln_turns -= 1
        if self.vuln_turns <= 0:
            self._remove_vulnerability(sim)

    def _apply_vulnerability(self, sim: BattleSimulator, owner: CharacterUnit) -> None:
        rate = _param(owner, 4, 0.18)
        diff = rate - self.vuln_contribution
        if abs(diff) < 1e-12:
            self.vuln_turns = int(_param(owner, 5, 2))
            return
        self.vuln_contribution = rate
        self.vuln_turns = int(_param(owner, 5, 2))
        for enemy in sim.enemies:
            enemy.vulnerability += diff

    def _remove_vulnerability(self, sim: BattleSimulator) -> None:
        if self.vuln_contribution == 0:
            return
        for enemy in sim.enemies:
            enemy.vulnerability -= self.vuln_contribution
        self.vuln_contribution = 0.0
        self.vuln_turns = 0
