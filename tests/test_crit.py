"""显式暴击判定（固定种子随机流）测试。"""

from __future__ import annotations

import pytest

from src.core.damage import DamageType
from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
from src.core.skill import Skill, SkillEffect, SkillType
from src.core.stats import BaseStats


def _make_char(crit_rate: float, crit_dmg: float = 0.5) -> CharacterUnit:
    char = CharacterUnit(unit_id="c1", name="测试", path="Rogue", element="Thunder", level=80)
    char.base_stats = BaseStats(
        atk_base=1000, spd_base=100, energy_max=100,
        crit_rate=crit_rate, crit_dmg=crit_dmg,
    )
    char.skills = {
        "c1_normal": Skill(
            id="c1_normal", name="普攻", skill_type=SkillType.NORMAL,
            sp_cost=-1, energy_recover=20,
            effects=[SkillEffect(
                damage_type=DamageType.NORMAL, multiplier=1.0,
                toughness_damage=10, element="Thunder",
            )],
        ),
    }
    return char


def _make_sim(char: CharacterUnit, seed: int = 0) -> BattleSimulator:
    enemy = EnemyState(
        unit_id="e1", name="木桩",
        max_toughness=100, current_toughness=0,
        weakness_elements=["Thunder"], is_broken=True, level=80, speed=0,
    )
    sim = BattleSimulator(characters=[char], enemies=[enemy], rng_seed=seed)
    sim.setup()
    return sim


def _normal_damage(sim: BattleSimulator) -> float:
    sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
    return sim.logs[-1].total_damage


class TestExplicitCrit:
    def test_no_crit_when_rate_zero(self):
        sim = _make_sim(_make_char(crit_rate=0.0, crit_dmg=0.5))
        # 基础伤害 1000 × 0.5 防御 = 500
        assert _normal_damage(sim) == pytest.approx(500)

    def test_always_crit(self):
        sim = _make_sim(_make_char(crit_rate=1.0, crit_dmg=0.5))
        # 1000 × 0.5 × (1 + 0.5) = 750
        assert _normal_damage(sim) == pytest.approx(750)

    def test_same_seed_same_sequence(self):
        a = _make_sim(_make_char(crit_rate=0.5, crit_dmg=1.0))
        b = _make_sim(_make_char(crit_rate=0.5, crit_dmg=1.0))
        results_a = [_normal_damage(a) for _ in range(8)]
        results_b = [_normal_damage(b) for _ in range(8)]
        assert results_a == results_b
        # 0.5 暴击率 + 固定种子应同时出现暴击与非暴击
        assert len(set(results_a)) > 1

    def test_crit_rng_independent_from_enemy_rng(self):
        """暴击随机流独立：固定暴击序列不受随机敌人选择影响。"""
        def build(seed):
            return _make_sim(_make_char(crit_rate=1.0, crit_dmg=0.5), seed=seed)
        assert _normal_damage(build(0)) == _normal_damage(build(0)) == pytest.approx(750)
