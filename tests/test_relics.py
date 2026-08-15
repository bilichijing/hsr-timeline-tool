"""遗器套装效果测试（freesr 中已出现的六套）。"""

from __future__ import annotations

import pytest

from src.core.relics import get_module_cls
from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState
from src.core.skill import Skill, SkillType
from src.core.stats import BaseStats, StatBonus


def _make_owner(
    set_id: str,
    effects: dict,
    *,
    count: int = 2,
    spd: float = 100.0,
    hp: float = 5000.0,
    unit_id: str = "c1",
) -> tuple[CharacterUnit, BattleSimulator]:
    char = CharacterUnit(
        unit_id=unit_id, name=unit_id, path="Rogue", element="Thunder", level=80,
    )
    char.base_stats = BaseStats(hp_base=hp, atk_base=1000, spd_base=spd, energy_max=120)
    char.bonus_stats = StatBonus()
    char.relic_set_counts = {set_id: count}
    char.relic_set_effects = {set_id: effects}
    enemy = EnemyState(
        unit_id="e1", name="木桩",
        max_hp=100000, current_hp=100000,
        max_toughness=100, current_toughness=100,
        weakness_elements=["Thunder"], speed=1,
    )
    sim = BattleSimulator(characters=[char], enemies=[enemy])
    sim.setup()
    return char, sim


def _relic_module(sim: BattleSimulator, uid: str = "c1"):
    return sim.relic_modules.get(uid, [None])[0]


class TestRegistry:
    @pytest.mark.parametrize("set_id,cls_name", [
        ("110", "EagleModule"),
        ("115", "DukeModule"),
        ("132", "SmithModule"),
        ("308", "VonwacqModule"),
        ("319", "BoneModule"),
        ("326", "CityModule"),
    ])
    def test_registered(self, set_id, cls_name):
        assert get_module_cls(set_id).__name__ == cls_name


class TestEagle:
    def test_wind_damage_bonus(self):
        char, sim = _make_owner("110", {"2": [0.1], "4": [0.25]}, count=4)
        assert char.final_stats().elemental_dmg_bonus["Wind"] == pytest.approx(0.1)

    def test_ultra_action_advance(self):
        char, sim = _make_owner("110", {"2": [0.1], "4": [0.25]}, count=4)
        before = sim.action_queue.get(char.unit_id).current_av
        skill = Skill(id="u", name="终结技", skill_type=SkillType.ULTRA)
        module = _relic_module(sim)
        module.on_skill_end(sim, char, skill, None, sim.enemies[0], None)
        assert sim.action_queue.get(char.unit_id).current_av == pytest.approx(before * 0.75)


class TestDuke:
    def test_follow_up_damage_and_stacks(self):
        char, sim = _make_owner("115", {"2": [0.2], "4": [0.06, 8, 3]}, count=4)
        module = _relic_module(sim)
        enemy = sim.enemies[0]
        assert char.final_stats().follow_up_dmg_bonus == pytest.approx(0.2)
        # 同一行动 8 段 → 8 层
        for token in range(8):
            module.on_attack_hit(sim, char, char, SkillType.FOLLOW_UP, enemy, 10, None, 1)
        assert module.stacks == 8
        assert char.final_stats().atk == pytest.approx(1000 * (1 + 0.06 * 8))
        # 新行动清空并重新从 1 层开始
        module.on_attack_hit(sim, char, char, SkillType.FOLLOW_UP, enemy, 10, None, 2)
        assert module.stacks == 1
        assert char.final_stats().atk == pytest.approx(1000 * (1 + 0.06))


class TestSmith:
    def test_crit_and_assist(self):
        char, sim = _make_owner("132", {"2": [0.12], "4": [0.28, 2, 0.15]}, count=4)
        module = _relic_module(sim)
        enemy = sim.enemies[0]
        assert char.final_stats().hp == pytest.approx(5000 * 1.12)
        enemy.def_reduce = 0.2
        module.on_attack_hit(sim, char, char, SkillType.NORMAL, enemy, 10, None, 1)
        assert enemy.crit_dmg_taken_by_unit["c1"] == pytest.approx(0.28)
        assert char.final_stats().dmg_bonus == pytest.approx(0.15)
        # 同行动不重复触发助燃
        module.on_attack_hit(sim, char, char, SkillType.NORMAL, enemy, 10, None, 1)
        assert char.final_stats().dmg_bonus == pytest.approx(0.15)
        # 减防消失后贡献撤销
        enemy.def_reduce = 0
        module.on_attack_hit(sim, char, char, SkillType.NORMAL, enemy, 10, None, 2)
        assert enemy.crit_dmg_taken_by_unit.get("c1", 0.0) == pytest.approx(0.0)


class TestVonwacq:
    def test_energy_regen_and_pull(self):
        char, sim = _make_owner("308", {"2": [0.05, 120, 0.4]}, count=2, spd=130)
        assert char.final_stats().energy_regen == pytest.approx(0.05)
        assert sim.action_queue.get(char.unit_id).current_av == pytest.approx(
            10000 / 130 * 0.6
        )


class TestBone:
    def test_hp_and_crit(self):
        char, sim = _make_owner("319", {"2": [0.12, 5000, 0.28]}, count=2, hp=6000)
        assert char.final_stats().hp == pytest.approx(6000 * 1.12)
        assert char.final_stats().crit_dmg == pytest.approx(0.5 + 0.28)


class TestCity:
    def test_follow_up_atk_and_kill_crit(self):
        char, sim = _make_owner("326", {"2": [0.24, 2, 0.12]}, count=2)
        module = _relic_module(sim)
        enemy = sim.enemies[0]
        module.on_attack_hit(sim, char, char, SkillType.FOLLOW_UP, enemy, 10, None, 1)
        assert char.final_stats().atk == pytest.approx(1000 * 1.24)
        module.on_enemy_dead(sim, char, enemy)
        assert char.final_stats().crit_dmg == pytest.approx(0.5 + 0.12)
        module.on_enemy_dead(sim, char, enemy)
        assert char.final_stats().crit_dmg == pytest.approx(0.5 + 0.12)
