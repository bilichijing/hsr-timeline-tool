"""三张已实现光锥的效果测试。"""

from __future__ import annotations

import pytest

from src.core.lightcones import get_module_cls
from src.core.lightcones.blaze_23059 import BlazeRebornModule
from src.core.lightcones.flower_23038 import FlowerOfTimeModule
from src.core.lightcones.lie_23056 import LieFinaleModule
from src.core.simulator import ActionEntry, BattleSimulator, CharacterUnit, EnemyState
from src.core.skill import Skill, SkillType
from src.core.stats import BaseStats, StatBonus


def _make_owner(
    lc_id: str,
    params: list[float],
    *,
    unit_id: str = "c1",
    energy_max: float = 200.0,
) -> tuple[CharacterUnit, BattleSimulator]:
    char = CharacterUnit(
        unit_id=unit_id,
        name=unit_id,
        path="Rogue",
        element="Thunder",
        level=80,
        char_id="",
    )
    char.base_stats = BaseStats(
        hp_base=5000, atk_base=1000, spd_base=100,
        energy_max=energy_max, crit_rate=0.05, crit_dmg=0.5,
    )
    char.bonus_stats = StatBonus()
    char.lightcone_id = lc_id
    char.lightcone_rank = 1
    char.lightcone_params = list(params)
    enemy = EnemyState(
        unit_id="e1", name="木桩",
        max_hp=100000, current_hp=100000,
        max_toughness=100, current_toughness=100,
        weakness_elements=["Thunder"], speed=1,
    )
    sim = BattleSimulator(characters=[char], enemies=[enemy])
    sim.setup()
    return char, sim


class TestRegistry:
    def test_registered(self):
        assert get_module_cls("23056") is LieFinaleModule
        assert get_module_cls("23059") is BlazeRebornModule
        assert get_module_cls("23038") is FlowerOfTimeModule


class TestLieFinale:
    PARAMS = [0.18, 4, 3, 0.4, 0.2]

    def test_battle_start_shadow(self):
        char, sim = _make_owner("23056", self.PARAMS)
        module = sim.lightcone_modules[char.unit_id]
        assert char.final_stats().crit_rate == pytest.approx(0.05 + 0.18)
        assert any(b.id == "lc23056_shadow_atk" for b in char.buff_mgr.buffs)
        assert module.shadow_active
        assert sim.enemies[0].vulnerability == pytest.approx(0.2)

    def test_follow_up_grants_shadow_every_4(self):
        char, sim = _make_owner("23056", self.PARAMS)
        module = sim.lightcone_modules[char.unit_id]
        enemy = sim.enemies[0]
        module.shadow_active = False
        module._sync_vuln(sim)
        assert enemy.vulnerability == 0.0
        for token in range(1, 4):
            module.on_attack_hit(
                sim, char, char, SkillType.FOLLOW_UP, enemy, 100, None, token,
            )
        assert module.follow_up_count == 3
        module.on_attack_hit(
            sim, char, char, SkillType.FOLLOW_UP, enemy, 100, None, 4,
        )
        assert module.follow_up_count == 0
        assert module.shadow_active
        assert enemy.vulnerability == pytest.approx(0.2)

    def test_duplicate_vuln_does_not_stack(self):
        chars = []
        for uid in ("c1", "c2"):
            char = CharacterUnit(
                unit_id=uid, name=uid, path="Rogue", element="Thunder", level=80,
            )
            char.base_stats = BaseStats(hp_base=5000, atk_base=1000, spd_base=100)
            char.bonus_stats = StatBonus()
            char.lightcone_id = "23056"
            char.lightcone_rank = 1
            char.lightcone_params = list(self.PARAMS)
            chars.append(char)
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_hp=100000, current_hp=100000,
            max_toughness=100, current_toughness=100,
            weakness_elements=["Thunder"], speed=1,
        )
        sim = BattleSimulator(characters=chars, enemies=[enemy])
        sim.setup()
        assert sim.enemies[0].vulnerability == pytest.approx(0.2)


class TestBlazeReborn:
    PARAMS = [0.3, 20, 2, 0.3, 0.3]

    def test_hp_and_energy_once(self):
        char, sim = _make_owner("23059", self.PARAMS)
        module = sim.lightcone_modules[char.unit_id]
        assert char.final_stats().hp == pytest.approx(5000 * 1.3)
        char.energy = 0
        module.on_turn_start(sim, char)
        assert char.energy == 20
        module.on_turn_start(sim, char)
        assert char.energy == 20

    def test_purgatory_crit_damage_taken(self):
        char, sim = _make_owner("23059", self.PARAMS)
        module = sim.lightcone_modules[char.unit_id]
        enemy = sim.enemies[0]
        skill = Skill(id="s", name="战技", skill_type=SkillType.SKILL)
        module.on_skill_end(sim, char, skill, None, enemy, None)
        assert enemy.crit_dmg_taken == pytest.approx(0.3)
        assert enemy.crit_dmg_taken_by_unit["c1"] == pytest.approx(0.3)
        # 敌方行动 1 次：剩余 1 回合
        module.on_enemy_act(sim, char, enemy, None)
        assert enemy.crit_dmg_taken == pytest.approx(0.3)
        # 敌方行动 2 次：炼狱消失
        module.on_enemy_act(sim, char, enemy, None)
        assert enemy.crit_dmg_taken == pytest.approx(0.0)
        assert enemy.crit_dmg_taken_by_unit.get("c1", 0.0) == pytest.approx(0.0)


class TestFlowerOfTime:
    PARAMS = [0.36, 12, 2, 0.48, 21, 2]

    def test_battle_start_energy_oracle_and_team_crit(self):
        char, sim = _make_owner("23038", self.PARAMS)
        module = sim.lightcone_modules[char.unit_id]
        assert char.energy == pytest.approx(21)
        assert char.final_stats().crit_dmg == pytest.approx(0.5 + 0.36 + 0.48)
        assert module.oracle_active

    def test_follow_up_energy_and_refresh(self):
        char, sim = _make_owner("23038", self.PARAMS)
        module = sim.lightcone_modules[char.unit_id]
        enemy = sim.enemies[0]
        before = char.energy
        module.on_attack_hit(
            sim, char, char, SkillType.FOLLOW_UP, enemy, 100, None, 1,
        )
        assert char.energy == pytest.approx(before + 12)
        # 重复同一行动不重复回能
        module.on_attack_hit(
            sim, char, char, SkillType.FOLLOW_UP, enemy, 100, None, 1,
        )
        assert char.energy == pytest.approx(before + 12)
