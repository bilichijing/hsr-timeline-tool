"""stats 模块单元测试。"""

import pytest

from src.core.stats import BaseStats, StatBonus, StatCalculator, compute_final_stats


class TestStatBonus:
    def test_add(self):
        a = StatBonus(atk_pct=0.2, hp_flat=100)
        b = StatBonus(atk_pct=0.1, atk_flat=50)
        c = a.add(b)
        assert c.atk_pct == pytest.approx(0.3)
        assert c.hp_flat == 100
        assert c.atk_flat == 50

    def test_scale(self):
        a = StatBonus(atk_pct=0.2, hp_flat=100)
        b = a.scale(2.0)
        assert b.atk_pct == pytest.approx(0.4)
        assert b.hp_flat == 200


class TestStatCalculator:
    def test_basic(self):
        base = BaseStats(hp_base=1000, atk_base=200, def_base=100, spd_base=100)
        calc = StatCalculator(base=base)
        final = calc.final()
        assert final.hp == 1000
        assert final.atk == 200
        assert final.spd == 100
        assert final.crit_rate == 0.05  # 默认 5%

    def test_with_pct_bonus(self):
        base = BaseStats(hp_base=1000, atk_base=200)
        bonus = StatBonus(hp_pct=0.5, atk_pct=0.3)
        final = compute_final_stats(base, bonus)
        assert final.hp == 1500  # 1000 × 1.5
        assert final.atk == pytest.approx(260)  # 200 × 1.3

    def test_with_flat_bonus(self):
        base = BaseStats(hp_base=1000, atk_base=200)
        bonus = StatBonus(hp_flat=200, atk_flat=50)
        final = compute_final_stats(base, bonus)
        assert final.hp == 1200
        assert final.atk == 250

    def test_combined_bonus(self):
        base = BaseStats(hp_base=1000, atk_base=200, spd_base=100)
        bonus = StatBonus(hp_pct=0.2, hp_flat=100, atk_pct=0.1, spd_flat=20)
        final = compute_final_stats(base, bonus)
        assert final.hp == 1300  # 1000 × 1.2 + 100
        assert final.atk == pytest.approx(220)  # 200 × 1.1
        assert final.spd == 120  # 100 + 20

    def test_multiple_bonuses(self):
        base = BaseStats(atk_base=200)
        b1 = StatBonus(atk_pct=0.1)
        b2 = StatBonus(atk_pct=0.2)
        b3 = StatBonus(atk_flat=30)
        final = compute_final_stats(base, b1, b2, b3)
        assert final.atk == pytest.approx(290)  # 200 × 1.3 + 30

    def test_crit_stacks(self):
        base = BaseStats(crit_rate=0.05, crit_dmg=0.5)
        bonus = StatBonus(crit_rate=0.08, crit_dmg=0.5)
        final = compute_final_stats(base, bonus)
        assert final.crit_rate == pytest.approx(0.13)  # 5% + 8%
        assert final.crit_dmg == pytest.approx(1.0)    # 50% + 50%


# ── 能量恢复效率 / 治疗量加成 ──────────────────────────────


class TestEnergyRegenAndHeal:
    def test_final_stats_chain(self):
        """BaseStats + StatBonus → FinalStats 相加正确。"""
        base = BaseStats(energy_regen=0.1, outgoing_heal=0.05)
        bonus = StatBonus(energy_regen=0.2, outgoing_heal=0.1)
        final = compute_final_stats(base, bonus)
        assert final.energy_regen == pytest.approx(0.3)
        assert final.outgoing_heal == pytest.approx(0.15)

    def test_add_and_scale_include_new_fields(self):
        """StatBonus.add / scale 覆盖新字段。"""
        b1 = StatBonus(energy_regen=0.1, outgoing_heal=0.2)
        b2 = StatBonus(energy_regen=0.05)
        total = b1.add(b2)
        assert total.energy_regen == pytest.approx(0.15)
        assert total.outgoing_heal == pytest.approx(0.2)
        scaled = b1.scale(2.0)
        assert scaled.energy_regen == pytest.approx(0.2)
        assert scaled.outgoing_heal == pytest.approx(0.4)

    def test_defaults_zero(self):
        final = compute_final_stats(BaseStats(), StatBonus())
        assert final.energy_regen == 0.0
        assert final.outgoing_heal == 0.0
