"""damage 模块单元测试。"""

import pytest

from src.core.damage import (
    BREAK_BASE_COEFF,
    BREAK_ELEMENT_MULTIPLIER,
    DamageContext,
    DamageType,
    DefenseContext,
    ELATION_BASE_LEVEL_80,
    calc_break_damage,
    calc_damage_reduction,
    calc_defense,
    calc_dot_damage,
    calc_elation_damage,
    calc_laugh_zone,
    calc_normal_damage,
    calc_resistance,
    calc_super_break_damage,
    calculate_damage,
)
from src.core.stats import FinalStats


def make_stats(
    atk: float = 1000,
    crit_rate: float = 0.0,
    crit_dmg: float = 0.0,
    dmg_bonus: float = 0.0,
    break_effect: float = 0.0,
    elation_dmg: float = 0.0,
    laugh_bonus: float = 0.0,
    laugh_point: float = 0.0,
    good_joke: float = 0.0,
) -> FinalStats:
    return FinalStats(
        hp=10000,
        atk=atk,
        defense=500,
        spd=100,
        crit_rate=crit_rate,
        crit_dmg=crit_dmg,
        dmg_bonus=dmg_bonus,
        break_effect=break_effect,
        effect_hit=0,
        effect_res=0,
        energy_max=100,
        aggro=100,
        elation_dmg=elation_dmg,
        laugh_bonus=laugh_bonus,
        laugh_point=laugh_point,
        good_joke=good_joke,
    )


def make_ctx(**kwargs) -> DamageContext:
    defaults = dict(
        damage_type=DamageType.NORMAL,
        element="Fire",
        base_value=1000,
        attacker_stats=make_stats(),
        is_weakness=True,
        is_broken=True,
    )
    defaults.update(kwargs)
    return DamageContext(**defaults)


class TestResistance:
    def test_weakness_default(self):
        ctx = make_ctx(is_weakness=True, resistance=None)
        assert calc_resistance(ctx) == 1.0  # 弱点抗性 0%

    def test_non_weakness_default(self):
        ctx = make_ctx(is_weakness=False, resistance=None)
        assert calc_resistance(ctx) == 0.8  # 非弱点 20% 抗性

    def test_explicit_resistance(self):
        ctx = make_ctx(resistance=0.4)
        assert calc_resistance(ctx) == 0.6  # 1 - 0.4

    def test_resistance_clamp_high(self):
        ctx = make_ctx(resistance=1.5)
        assert calc_resistance(ctx) == pytest.approx(0.1)  # 钳制到 90% -> 1 - 0.9

    def test_resistance_clamp_low(self):
        ctx = make_ctx(resistance=-1.5)
        assert calc_resistance(ctx) == 2.0  # 钳制到 -100% -> 1 - (-1)


class TestDefense:
    def test_character_attack_enemy(self):
        ctx = make_ctx(defense_ctx=DefenseContext(
            attacker_level=80,
            defender_level=80,
        ))
        # (80+20) / [(80+20) + (80+20) × 1] = 100/200 = 0.5
        assert calc_defense(ctx, attacker_to_defender=True) == pytest.approx(0.5)

    def test_def_reduce(self):
        ctx = make_ctx(defense_ctx=DefenseContext(
            attacker_level=80,
            defender_level=80,
            def_reduce=0.3,
        ))
        # 100 / [100 + 100 × (1 - 0.3)] = 100/170
        assert calc_defense(ctx, attacker_to_defender=True) == pytest.approx(100/170)

    def test_def_ignore(self):
        ctx = make_ctx(defense_ctx=DefenseContext(
            attacker_level=80,
            defender_level=80,
            def_ignore=0.5,
        ))
        # 100 / [100 + 100 × (1 - 0.5)] = 100/150
        assert calc_defense(ctx, attacker_to_defender=True) == pytest.approx(100/150)

    def test_piggy(self):
        ctx = make_ctx(defense_ctx=DefenseContext(
            attacker_level=80,
            defender_level=80,
            is_piggy=True,
        ))
        # 100 / [100 + (1.5 × 80 + 30)] = 100 / [100 + 150] = 100/250
        assert calc_defense(ctx, attacker_to_defender=True) == pytest.approx(100/250)

    def test_enemy_attack_character(self):
        ctx = make_ctx(defense_ctx=DefenseContext(
            attacker_level=80,
            defender_level=80,
            defender_defense=1000,
        ))
        # (10 × 80 + 200) / (10 × 80 + 200 + 1000) = 1000/2000 = 0.5
        assert calc_defense(ctx, attacker_to_defender=False) == pytest.approx(0.5)


class TestDamageReduction:
    def test_no_reduction(self):
        ctx = make_ctx(is_broken=True, damage_reductions=[])
        assert calc_damage_reduction(ctx) == 1.0

    def test_unbroken_10_percent(self):
        ctx = make_ctx(is_broken=False, damage_reductions=[])
        assert calc_damage_reduction(ctx) == pytest.approx(0.9)

    def test_multiple_multiply(self):
        ctx = make_ctx(is_broken=True, damage_reductions=[0.5, 0.5])
        # (1-0.5) × (1-0.5) = 0.25
        assert calc_damage_reduction(ctx) == pytest.approx(0.25)

    def test_floor_one_percent(self):
        ctx = make_ctx(is_broken=True, damage_reductions=[0.99, 0.99])
        # 0.01 × 0.01 = 0.0001, 下限 0.01
        assert calc_damage_reduction(ctx) == pytest.approx(0.01)


class TestNormalDamage:
    def test_basic(self):
        ctx = make_ctx(base_value=1000, is_broken=True, is_weakness=True)
        # 1000 × 1 × 1 × 1 × 1 × 1 × 1 × 1 × 1 = 1000
        dmg = calc_normal_damage(ctx)
        assert dmg == pytest.approx(1000)

    def test_with_crit(self):
        ctx = make_ctx(
            base_value=1000,
            is_crit=True,
            crit_dmg=0.5,
            is_broken=True,
        )
        # 1000 × 1 × 1.5 = 1500
        assert calc_normal_damage(ctx) == pytest.approx(1500)

    def test_with_dmg_bonus(self):
        ctx = make_ctx(
            base_value=1000,
            attacker_stats=make_stats(dmg_bonus=0.5),
            is_broken=True,
        )
        # 1000 × 1.5 = 1500
        assert calc_normal_damage(ctx) == pytest.approx(1500)

    def test_with_vulnerability(self):
        ctx = make_ctx(base_value=1000, vulnerability=0.3, is_broken=True)
        # 1000 × 1 × 1.3 = 1300
        assert calc_normal_damage(ctx) == pytest.approx(1300)

    def test_with_weakness(self):
        ctx = make_ctx(base_value=1000, weakness=0.5, is_broken=True)
        # 1000 × (1 - 0.5) = 500
        assert calc_normal_damage(ctx) == pytest.approx(500)

    def test_unbroken_10_percent_reduction(self):
        ctx = make_ctx(base_value=1000, is_broken=False)
        # 1000 × 0.9 = 900
        assert calc_normal_damage(ctx) == pytest.approx(900)


class TestBreakDamage:
    def test_basic(self):
        ctx = make_ctx(
            damage_type=DamageType.BREAK,
            element="Fire",
            is_broken=True,
            toughness_max=60,
            attacker_stats=make_stats(),
        )
        # 击破基础值 = 3767.55 × (60/40 + 0.5) = 3767.55 × 2 = 7535.1
        # 属性倍率 = 2.0（火）
        # 7535.1 × 2 = 15070.2
        dmg = calc_break_damage(ctx)
        assert dmg == pytest.approx(15070.2, rel=0.01)

    def test_quantum_half_multiplier(self):
        ctx = make_ctx(
            damage_type=DamageType.BREAK,
            element="Quantum",
            is_broken=True,
            toughness_max=40,
            attacker_stats=make_stats(),
        )
        # 击破基础值 = 3767.55 × (40/40 + 0.5) = 3767.55 × 1.5 = 5651.325
        # 属性倍率 = 0.5（量子）
        # 5651.325 × 0.5 = 2825.6625
        dmg = calc_break_damage(ctx)
        assert dmg == pytest.approx(2825.6625, rel=0.01)

    def test_with_break_effect(self):
        ctx = make_ctx(
            damage_type=DamageType.BREAK,
            element="Fire",
            is_broken=True,
            toughness_max=40,
            attacker_stats=make_stats(break_effect=0.5),
        )
        # 击破基础值 = 3767.55 × 1.5 = 5651.325
        # 属性倍率 = 2.0
        # (1 + 0.5) = 1.5
        # 5651.325 × 2 × 1.5 = 16953.975
        dmg = calc_break_damage(ctx)
        assert dmg == pytest.approx(16953.975, rel=0.01)


class TestSuperBreakDamage:
    def test_basic(self):
        ctx = make_ctx(
            damage_type=DamageType.SUPER_BREAK,
            element="Fire",
            is_broken=True,
            actual_toughness_reduced=30,
            super_break_multiplier=0.6,
            attacker_stats=make_stats(),
        )
        # 超击破基础值 = 3767.55 × 30 / 10 = 11302.65
        # × 0.6（超击破倍率）= 6781.59
        dmg = calc_super_break_damage(ctx)
        assert dmg == pytest.approx(6781.59, rel=0.01)


class TestDotDamage:
    def test_basic(self):
        ctx = make_ctx(
            damage_type=DamageType.DOT,
            base_value=500,
            is_broken=True,
            is_crit=True,  # 持续伤害不暴击
            crit_dmg=0.5,
        )
        # 500 × 1 × 1 × 1 × 1 × 1 × 1 × 1 × 1（持续伤害暴击区=1）= 500
        assert calc_dot_damage(ctx) == pytest.approx(500)


class TestElationDamage:
    def test_laugh_zone(self):
        # 笑点 = 0 时为 1
        assert calc_laugh_zone(0) == 1.0
        # 笑点 = 240：1 + 240 × 5 / 480 = 1 + 2.5 = 3.5
        assert calc_laugh_zone(240) == pytest.approx(3.5)
        # 笑点 = 360：1 + 360 × 5 / 600 = 1 + 3 = 4
        assert calc_laugh_zone(360) == pytest.approx(4.0)

    def test_basic_elation_skill(self):
        """欢愉技用笑点区。"""
        ctx = make_ctx(
            damage_type=DamageType.ELATION,
            element="Fire",
            base_value=ELATION_BASE_LEVEL_80,
            elation_multiplier=1.0,
            is_elation_skill=True,
            is_broken=True,
            attacker_stats=make_stats(laugh_point=240),
        )
        # 基础值 = 1.0 × 7535.107 = 7535.107
        # 欢愉度 = 0 → 1
        # 增笑 = 0 → 1
        # 笑点区 = 3.5
        # 其他乘区 = 1
        # 7535.107 × 1 × 1 × 3.5 × 1 × 1 × 1 × 1 × 1 = 26372.87
        dmg = calc_elation_damage(ctx)
        assert dmg == pytest.approx(26372.87, rel=0.01)

    def test_non_elation_skill_uses_good_joke(self):
        """非欢愉技用好活当赏区。"""
        ctx = make_ctx(
            damage_type=DamageType.ELATION,
            element="Fire",
            base_value=ELATION_BASE_LEVEL_80,
            elation_multiplier=1.0,
            is_elation_skill=False,
            is_broken=True,
            attacker_stats=make_stats(good_joke=240),
        )
        # 好活当赏区 = 3.5
        dmg = calc_elation_damage(ctx)
        assert dmg == pytest.approx(26372.87, rel=0.01)

    def test_with_elation_dmg_bonus(self):
        ctx = make_ctx(
            damage_type=DamageType.ELATION,
            element="Fire",
            base_value=ELATION_BASE_LEVEL_80,
            elation_multiplier=1.0,
            is_elation_skill=True,
            is_broken=True,
            attacker_stats=make_stats(laugh_point=240, elation_dmg=0.5),
        )
        # 7535.107 × 1.5（欢愉度）× 1 × 3.5 = 39559.31
        dmg = calc_elation_damage(ctx)
        assert dmg == pytest.approx(39559.31, rel=0.01)

    def test_with_laugh_bonus(self):
        ctx = make_ctx(
            damage_type=DamageType.ELATION,
            element="Fire",
            base_value=ELATION_BASE_LEVEL_80,
            elation_multiplier=1.0,
            is_elation_skill=True,
            is_broken=True,
            attacker_stats=make_stats(laugh_point=240, laugh_bonus=0.3),
        )
        # 7535.107 × 1 × 1.3 × 3.5 = 34284.73
        dmg = calc_elation_damage(ctx)
        assert dmg == pytest.approx(34284.73, rel=0.01)


class TestCalculateDamageDispatch:
    def test_dispatch_normal(self):
        ctx = make_ctx(damage_type=DamageType.NORMAL, base_value=1000, is_broken=True)
        assert calculate_damage(ctx) == pytest.approx(1000)

    def test_dispatch_break(self):
        ctx = make_ctx(
            damage_type=DamageType.BREAK,
            element="Fire",
            is_broken=True,
            toughness_max=40,
        )
        assert calculate_damage(ctx) > 0

    def test_dispatch_unknown_raises(self):
        ctx = make_ctx(damage_type="unknown")  # type: ignore
        with pytest.raises(ValueError):
            calculate_damage(ctx)
