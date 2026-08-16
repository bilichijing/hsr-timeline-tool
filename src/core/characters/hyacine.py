"""风堇（Hyacine, char_id=1409）技能模块：记忆 / 风 / 治疗。

当前为风堇专用轻量忆灵模型：小伊卡不进入行动队列，仅作为模块状态。
治疗乘区：实际治疗 = 基础治疗 × (1 + outgoing_heal + incoming_heal)，
溢出部分计入“累计治疗数值”。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..buff import Buff, BuffDuration, StackRule
from ..damage import DamageType
from ..skill import SkillEffect, SkillType, get_skill_by_type
from . import register
from .base import CharacterModule, module_params

if TYPE_CHECKING:
    from ..simulator import ActionLog, BattleSimulator, CharacterUnit, EnemyState, PlayerAction
    from ..skill import Skill

SKILL_NORMAL = "140901"
SKILL_SKILL = "140902"
SKILL_ULTRA = "140903"
SKILL_TALENT = "140904"
SKILL_TECHNIQUE = "140907"

MEMO_SKILL = "1140901"   # 忆灵技
MEMO_AUTO = "1140903"    # 忆灵天赋：自动治疗
MEMO_SUMMON = "1140905"  # 忆灵天赋：召唤回能

ELEMENT = "Wind"

# 用户确认的自动治疗数值
AUTO_COST_PCT = 0.04
AUTO_HEAL_PCT = 0.02
AUTO_HEAL_FLAT = 20.0

SUNNY_HP_PCT_ID = "hyacine_sunny_hp_pct"
SUNNY_HP_FLAT_ID = "hyacine_sunny_hp_flat"
TECH_HP_PCT_ID = "hyacine_tech_hp_pct"
TECH_HP_FLAT_ID = "hyacine_tech_hp_flat"


def _memo_level_params(raw: dict, skill_id: str, level: int) -> list[float]:
    skills = raw.get("skills", {})
    skill = skills.get(skill_id, {})
    level_map = skill.get("level", {}) if isinstance(skill, dict) else {}
    row = level_map.get(str(level)) or level_map.get("1") or {}
    return list(row.get("param_list") or [])


def _p(params: list[float], index: int, default: float) -> float:
    return float(params[index - 1]) if 1 <= index <= len(params) else default


@register
class HyacineModule(CharacterModule):
    CHAR_ID = "1409"

    unit_id: str = ""
    # ── 小伊卡（轻量忆灵）──
    memosprite_alive: bool = False
    memosprite_max_hp: float = 0.0
    memosprite_hp: float = 0.0
    summoned_once: bool = False
    # ── 治疗/增益 ──
    cumulative_healing: float = 0.0
    sunny_turns: int = 0
    tech_turns: int = 0
    memo_dmg_bonus: float = 0.0      # 天赋：治疗时小伊卡伤害提高
    memo_bonus_stacks: int = 0
    memo_bonus_turns: int = 0
    talent_params_cache: list[float] = []
    # 自动治疗判定快照
    _hp_snapshot: dict[str, float] = {}

    # ── 战斗开始 ─────────────────────────────────────
    def on_battle_start_setup(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        self.unit_id = char.unit_id
        self.memosprite_alive = False
        self.memosprite_max_hp = 0.0
        self.memosprite_hp = 0.0
        self.summoned_once = False
        self.cumulative_healing = 0.0
        self.sunny_turns = 0
        self.tech_turns = 0
        self.memo_dmg_bonus = 0.0
        self.memo_bonus_stacks = 0
        self.memo_bonus_turns = 0
        talent = get_skill_by_type(char.skills, SkillType.TALENT)
        self.talent_params_cache = talent.params if talent is not None else []
        # 秘技进战：回复我方全体并提高生命上限
        tech = char.skills.get(SKILL_TECHNIQUE)
        if tech is not None:
            params = tech.params
            heal_pct = _p(params, 1, 0.30)
            heal_flat = _p(params, 2, 600.0)
            max_pct = _p(params, 3, 0.20)
            turns = int(_p(params, 4, 2))
            for ally in sim.characters:
                self._heal_ally(sim, char, ally, char.final_stats().hp * heal_pct + heal_flat)
            self._apply_tech_hp_buffs(sim, char, max_pct, turns)
            self.tech_turns = turns
        self._update_hp_snapshot(sim)

    # ── 回合/行动判定 ─────────────────────────────────
    def on_turn_start(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        self._check_auto_heal(sim)
        if char.unit_id == self.unit_id:
            if self.tech_turns > 0:
                self.tech_turns -= 1
                if self.tech_turns <= 0:
                    self._remove_tech_hp_buffs(sim)
            if self.sunny_turns > 0:
                self.sunny_turns -= 1
                if self.sunny_turns <= 0:
                    self._remove_sunny_buffs(sim)
        self._update_hp_snapshot(sim)

    def on_enemy_act(self, sim: BattleSimulator, enemy: EnemyState, log: ActionLog) -> None:
        self._check_auto_heal(sim)
        self._update_hp_snapshot(sim)

    def on_skill_cast(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        if str(skill.id) == SKILL_NORMAL:
            if skill.effects:
                skill.effects[0].base_stat = "hp"
        elif str(skill.id) in (SKILL_SKILL, SKILL_ULTRA):
            # 治疗/辅助技能无直伤，清空误解析 effects
            skill.effects = []

    def on_skill_end(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        skill_id = str(skill.id)
        if skill_id == SKILL_SKILL:
            self._cast_skill_heal(sim, char, skill, log)
        elif skill_id == SKILL_ULTRA:
            self._cast_ultra(sim, char, skill, log)

    def on_post_skill(
        self,
        sim: BattleSimulator,
        char: CharacterUnit,
        skill: Skill,
        action: PlayerAction,
        target: EnemyState | None,
        log: ActionLog,
    ) -> None:
        # 任意行动后自动治疗判定
        self._check_auto_heal(sim)
        self._update_hp_snapshot(sim)
        # 雨过天晴：风堇技能完全结算后，小伊卡立即获得额外回合并放忆灵技
        if (
            char.unit_id == self.unit_id
            and self.sunny_turns > 0
            and self.memosprite_alive
        ):
            self._execute_memo_skill(sim, char)

    # ── 本体技能 ─────────────────────────────────────
    def _cast_skill_heal(self, sim: BattleSimulator, char: CharacterUnit, skill: Skill, log: ActionLog) -> None:
        self._summon_memosprite(sim, char)
        params = skill.params
        ally_pct = _p(params, 1, 0.04)
        ally_flat = _p(params, 2, 40.0)
        memo_pct = _p(params, 3, 0.05)
        memo_flat = _p(params, 4, 50.0)
        for ally in sim.characters:
            self._heal_ally(sim, char, ally, char.final_stats().hp * ally_pct + ally_flat)
        self._heal_memosprite(sim, char, char.final_stats().hp * memo_pct + memo_flat)
        log.notes = (log.notes + " 治疗" if log.notes else "治疗")
        self._update_hp_snapshot(sim)

    def _cast_ultra(self, sim: BattleSimulator, char: CharacterUnit, skill: Skill, log: ActionLog) -> None:
        self._summon_memosprite(sim, char)
        params = skill.params
        ally_pct = _p(params, 1, 0.05)
        ally_flat = _p(params, 2, 50.0)
        memo_pct = _p(params, 6, 0.06)
        memo_flat = _p(params, 7, 60.0)
        for ally in sim.characters:
            self._heal_ally(sim, char, ally, char.final_stats().hp * ally_pct + ally_flat)
        self._heal_memosprite(sim, char, char.final_stats().hp * memo_pct + memo_flat)
        self._apply_sunny_buffs(sim, char, skill)
        log.notes = (log.notes + " 治疗·雨过天晴" if log.notes else "治疗·雨过天晴")
        self._update_hp_snapshot(sim)

    # ── 治疗 ─────────────────────────────────────────
    def _heal_ally(
        self,
        sim: BattleSimulator,
        healer: CharacterUnit,
        target: CharacterUnit,
        amount: float,
        *,
        source: str = "hyacine",
    ) -> None:
        actual, raw = sim.heal(healer, target, amount, source=source)
        self._record_healing(raw)

    def _heal_memosprite(self, sim: BattleSimulator, healer: CharacterUnit, amount: float) -> None:
        if not self.memosprite_alive:
            return
        raw = max(0.0, amount) * (1.0 + healer.final_stats().outgoing_heal)
        actual = min(raw, max(0.0, self.memosprite_max_hp - self.memosprite_hp))
        self.memosprite_hp = max(0.0, min(self.memosprite_max_hp, self.memosprite_hp + actual))
        self._record_healing(raw)

    def _record_healing(self, raw: float) -> None:
        if raw <= 0:
            return
        self.cumulative_healing += raw
        talent = self._talent_params()
        if not talent:
            return
        inc = _p(talent, 3, 0.40)
        turns = int(_p(talent, 4, 2))
        max_stacks = int(_p(talent, 5, 3))
        self.memo_bonus_stacks = min(max_stacks, self.memo_bonus_stacks + 1)
        self.memo_bonus_turns = turns
        self.memo_dmg_bonus = self.memo_bonus_stacks * inc

    # ── 小伊卡 ───────────────────────────────────────
    def _summon_memosprite(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        if self.memosprite_alive:
            return
        talent = self._talent_params()
        inherit = _p(talent, 1, 0.50)
        self.memosprite_max_hp = char.final_stats().hp * inherit
        self.memosprite_hp = self.memosprite_max_hp
        self.memosprite_alive = True
        # 被召唤时回能；首次召唤额外回能
        params = _memo_level_params(char.memosprite_raw, MEMO_SUMMON, 1)
        energy = _p(params, 1, 15.0)
        if not self.summoned_once:
            energy += _p(params, 2, 30.0)
            self.summoned_once = True
        sim.recover_energy(char, energy)

    def _execute_memo_skill(self, sim: BattleSimulator, char: CharacterUnit) -> None:
        if not self.memosprite_alive or not sim.enemies:
            return
        params = _memo_level_params(char.memosprite_raw, MEMO_SKILL, char.memo_skill_level)
        ratio = _p(params, 1, 0.10)
        clear_ratio = _p(params, 2, 0.50)
        base_value = self.cumulative_healing * ratio
        log = sim.make_follow_up_log(
            char, sim.enemies[0],
            notes="小伊卡·乌云乌云快走开！",
            action_type="memo_skill",
        )
        log.actor_id = f"{char.unit_id}_memo"
        log.actor_name = "小伊卡"
        stats = char.final_stats()
        stats.dmg_bonus += self.memo_dmg_bonus
        effect = SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=1.0,
            fixed_base_value=base_value,
            toughness_damage=0,
            element=ELEMENT,
        )
        for enemy in sim.enemies:
            sim.deal_damage(
                char, enemy, effect,
                skill_type=SkillType.MEMO_DNSKILL,
                log=log, stats=stats,
            )
        # 通知光锥：忆灵技完整结算完成（额外伤害/敌方易伤等）
        lc_module = sim.lightcone_modules.get(char.unit_id)
        if lc_module is not None:
            sim._dispatch_lightcone_hook(lc_module, "on_memo_skill_end", sim, char)
        self.cumulative_healing *= max(0.0, 1.0 - clear_ratio)
        # 小伊卡技能后，自身持续效果回合 -1
        if self.memo_bonus_turns > 0:
            self.memo_bonus_turns -= 1
            if self.memo_bonus_turns <= 0:
                self.memo_bonus_stacks = 0
                self.memo_dmg_bonus = 0.0
        # 忆灵技行动后再次判定自动治疗
        self._check_auto_heal(sim)
        self._update_hp_snapshot(sim)

    def _check_auto_heal(self, sim: BattleSimulator) -> None:
        if not self.memosprite_alive:
            self._update_hp_snapshot(sim)
            return
        lowered = [
            ally for ally in sim.characters
            if ally.unit_id in self._hp_snapshot
            and ally.current_hp < self._hp_snapshot[ally.unit_id]
        ]
        if not lowered:
            self._update_hp_snapshot(sim)
            return
        # 一次判定只消耗一次小伊卡生命
        self.memosprite_hp -= self.memosprite_max_hp * AUTO_COST_PCT
        if self.memosprite_hp <= 0:
            self.memosprite_hp = 0.0
            self.memosprite_alive = False
            self._update_hp_snapshot(sim)
            return
        char = next((c for c in sim.characters if c.unit_id == self.unit_id), None)
        if char is None:
            return
        amount = char.final_stats().hp * AUTO_HEAL_PCT + AUTO_HEAL_FLAT
        for ally in lowered:
            self._heal_ally(sim, char, ally, amount, source="memosprite")
        # 雨过天晴：无论本次判定有多少目标降低，我方全体额外回复一次
        if self.sunny_turns > 0:
            for ally in sim.characters:
                self._heal_ally(sim, char, ally, amount, source="memosprite")
        self._update_hp_snapshot(sim)

    def _talent_params(self) -> list[float]:
        return self.talent_params_cache

    # ── 雨过天晴 / 秘技生命上限 ───────────────────────
    def _apply_sunny_buffs(self, sim: BattleSimulator, char: CharacterUnit, skill: Skill) -> None:
        self._remove_sunny_buffs(sim)
        self.sunny_turns = int(_p(skill.params, 5, 3))
        self._apply_max_hp_delta(
            sim, char,
            pct=_p(skill.params, 3, 0.15),
            flat=_p(skill.params, 4, 150.0),
            pct_id=SUNNY_HP_PCT_ID,
            flat_id=SUNNY_HP_FLAT_ID,
            turns=self.sunny_turns,
        )

    def _apply_tech_hp_buffs(self, sim: BattleSimulator, char: CharacterUnit, pct: float, turns: int) -> None:
        self._apply_max_hp_delta(
            sim, char,
            pct=pct, flat=0.0,
            pct_id=TECH_HP_PCT_ID, flat_id=TECH_HP_FLAT_ID, turns=turns,
        )

    def _remove_tech_hp_buffs(self, sim: BattleSimulator) -> None:
        self.tech_turns = 0
        self._apply_max_hp_delta(
            sim,
            next((c for c in sim.characters if c.unit_id == self.unit_id), None),
            pct=0.0, flat=0.0,
            pct_id=TECH_HP_PCT_ID, flat_id=TECH_HP_FLAT_ID, turns=0,
            removing=True,
        )

    def _remove_sunny_buffs(self, sim: BattleSimulator) -> None:
        self.sunny_turns = 0
        self._apply_max_hp_delta(
            sim,
            next((c for c in sim.characters if c.unit_id == self.unit_id), None),
            pct=0.0, flat=0.0,
            pct_id=SUNNY_HP_PCT_ID, flat_id=SUNNY_HP_FLAT_ID, turns=0,
            removing=True,
        )

    def _apply_max_hp_delta(
        self,
        sim: BattleSimulator,
        owner: CharacterUnit | None,
        *,
        pct: float,
        flat: float,
        pct_id: str,
        flat_id: str,
        turns: int,
        removing: bool = False,
    ) -> None:
        if owner is None:
            return
        # 先记录旧 max 与旧血量比例，再移除旧 buff，保证生命上限变化时血量比例不变
        old_ratios = {
            ally.unit_id: (ally.current_hp / ally.final_stats().hp if ally.final_stats().hp > 0 else 1.0)
            for ally in sim.characters
        }
        for ally in sim.characters:
            ally.buff_mgr.remove(pct_id)
            ally.buff_mgr.remove(flat_id)
        old_memo_ratio = (
            self.memosprite_hp / self.memosprite_max_hp
            if self.memosprite_max_hp > 0 else 1.0
        )
        if pct or flat:
            for ally in sim.characters:
                ratio = old_ratios[ally.unit_id]
                ally.buff_mgr.add(Buff(
                    id=pct_id, name="生命上限提高", stat="hp_pct", value=pct,
                    duration_type=BuffDuration.PERMANENT,
                    duration_count=-1, source_unit=owner.unit_id,
                    stack_rule=StackRule.NO_STACK_SAME_NAME,
                ))
                ally.buff_mgr.add(Buff(
                    id=flat_id, name="生命上限提高", stat="hp_flat", value=flat,
                    duration_type=BuffDuration.PERMANENT,
                    duration_count=-1, source_unit=owner.unit_id,
                    stack_rule=StackRule.NO_STACK_SAME_NAME,
                ))
                new_max = ally.final_stats().hp
                ally.current_hp = new_max * ratio
        else:
            # 移除生命上限 buff：同样保持剩余生命比例
            for ally in sim.characters:
                new_max = ally.final_stats().hp
                ally.current_hp = new_max * old_ratios[ally.unit_id]
        # 小伊卡生命上限跟随风堇最终生命上限
        if self.memosprite_alive:
            talent = self._talent_params()
            inherit = _p(talent, 1, 0.50) if talent else 0.50
            self.memosprite_max_hp = owner.final_stats().hp * inherit
            self.memosprite_hp = self.memosprite_max_hp * old_memo_ratio

    def _update_hp_snapshot(self, sim: BattleSimulator) -> None:
        self._hp_snapshot = {ally.unit_id: ally.current_hp for ally in sim.characters}
