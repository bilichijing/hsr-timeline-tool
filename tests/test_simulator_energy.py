"""模拟器能量回复乘区（energy_regen）单元测试。"""

import pytest

from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
from src.core.skill import SkillType
from src.core.stats import BaseStats, StatBonus


def _make_char(energy_regen: float = 0.0) -> CharacterUnit:
    char = CharacterUnit(
        unit_id="c1",
        name="测试",
        path="Rogue",
        element="Thunder",
        level=80,
    )
    char.base_stats = BaseStats(atk_base=1000, spd_base=100, energy_max=100)
    char.bonus_stats = StatBonus(energy_regen=energy_regen)
    # 普攻（回能 20）
    from src.core.damage import DamageType
    from src.core.skill import Skill, SkillEffect

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


def _make_sim(energy_regen: float = 0.0) -> BattleSimulator:
    sim = BattleSimulator(
        characters=[_make_char(energy_regen)],
        enemies=[
            EnemyState(
                unit_id="e1", name="怪",
                max_toughness=100, current_toughness=100,
                weakness_elements=["Thunder"],
            ),
        ],
    )
    sim.setup()
    return sim


class TestActionRecovery:
    def test_recovery_applies_energy_regen(self):
        """普攻行动回复 20，energy_regen=0.5 → +30。"""
        sim = _make_sim(energy_regen=0.5)
        log = sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert log is not None
        assert log.energy_after == pytest.approx(30.0)

    def test_no_regen_default(self):
        """无能量恢复效率时回复原值 20。"""
        sim = _make_sim(energy_regen=0.0)
        log = sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert log.energy_after == pytest.approx(20.0)

    def test_recovery_capped_at_energy_max(self):
        """高回复量钳制到能量上限。"""
        sim = _make_sim(energy_regen=10.0)
        log = sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert log.energy_after == pytest.approx(100.0)  # energy_max


class TestRecoverEnergy:
    def test_recover_energy_applies_regen(self):
        sim = _make_sim(energy_regen=0.5)
        char = sim.characters[0]
        actual = sim.recover_energy(char, 10)
        assert actual == pytest.approx(15.0)
        assert char.energy == pytest.approx(15.0)

    def test_recover_energy_capped(self):
        sim = _make_sim(energy_regen=0.5)
        char = sim.characters[0]
        char.energy = 95
        actual = sim.recover_energy(char, 10)
        assert actual == pytest.approx(5.0)  # 15 只放得下 5
        assert char.energy == 100.0


# ── 面板增伤不双重计数（回归）──────────────────────────────


class TestDmgBonusOnce:
    def test_dmg_bonus_applied_once(self):
        """面板增伤只进一次乘区（attacker_stats），不因 ctx.dmg_bonus 重复叠加。"""
        char = _make_char()
        char.bonus_stats = StatBonus(dmg_bonus=0.3)
        sim = BattleSimulator(
            characters=[char],
            enemies=[
                EnemyState(
                    unit_id="e1", name="怪",
                    max_toughness=100, current_toughness=100,
                    weakness_elements=["Thunder"],
                ),
            ],
        )
        sim.setup()
        log = sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        # 1000 × 1.0 × (1+0.3) × 0.9（未击破）× 0.5（防御 80 级 vs 80 级）
        assert log.damages[0] == pytest.approx(1000 * 1.3 * 0.9 * 0.5)
