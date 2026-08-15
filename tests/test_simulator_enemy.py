"""怪物配置（数量 / 木桩速度 0 / 非弱点抗性）单元测试。"""

from __future__ import annotations

import pytest

from src.core.damage import (
    ALL_ELEMENTS,
    DEFAULT_RESISTANCE_NON_WEAK,
    DamageType,
    build_enemy_resistance,
)
from src.core.simulator import (
    BattleEndReason,
    BattleSimulator,
    CharacterUnit,
    EnemyAttack,
    EnemyState,
    PlayerAction,
)
from src.core.skill import Skill, SkillEffect, SkillType
from src.core.stats import BaseStats


# ── 抗性表构造 ─────────────────────────────────────────────


class TestBuildEnemyResistance:
    def test_weakness_elements_zero(self):
        """弱点对应属性抗性为 0，其余用非弱点抗性默认值。"""
        res = build_enemy_resistance(["Fire", "Ice"])
        assert res["Fire"] == 0.0
        assert res["Ice"] == 0.0
        assert res["Thunder"] == pytest.approx(DEFAULT_RESISTANCE_NON_WEAK)

    def test_non_weak_uses_config(self):
        """非弱点属性使用传入的非弱点抗性配置。"""
        res = build_enemy_resistance(["Fire"], non_weak_resistance=0.4)
        assert res["Fire"] == 0.0
        assert res["Thunder"] == pytest.approx(0.4)
        assert res["Quantum"] == pytest.approx(0.4)

    def test_default_covers_all_elements(self):
        """默认覆盖全部 7 属性，且无弱点时全部为非弱点抗性。"""
        res = build_enemy_resistance([])
        assert set(res.keys()) == set(ALL_ELEMENTS)
        assert all(v == pytest.approx(DEFAULT_RESISTANCE_NON_WEAK) for v in res.values())

    def test_custom_elements(self):
        """可传入自定义属性集合。"""
        res = build_enemy_resistance(["A"], non_weak_resistance=0.1, all_elements=["A", "B"])
        assert res == {"A": 0.0, "B": 0.1}


# ── 木桩（速度 0）行动队列行为 ──────────────────────────────


def _make_char() -> CharacterUnit:
    char = CharacterUnit(
        unit_id="c1",
        name="测试",
        path="Rogue",
        element="Thunder",
        level=80,
    )
    char.base_stats = BaseStats(atk_base=1000, spd_base=100, energy_max=100)
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


class TestSpeedZeroEnemy:
    def test_speed_zero_enemy_not_in_queue(self):
        """速度 0 的怪物不进入行动队列，角色仍在队列。"""
        sim = BattleSimulator(
            characters=[_make_char()],
            enemies=[EnemyState(
                unit_id="e1", name="木桩",
                max_toughness=60, current_toughness=60,
                weakness_elements=["Thunder"], speed=0.0,
            )],
        )
        sim.setup()
        assert sim.action_queue.get("e1") is None
        assert sim.action_queue.get("c1") is not None

    def test_speed_zero_enemy_stays_broken(self):
        """木桩永不行动，击破后不恢复韧性。"""
        sim = BattleSimulator(
            characters=[_make_char()],
            enemies=[EnemyState(
                unit_id="e1", name="木桩",
                max_toughness=10, current_toughness=10,
                weakness_elements=["Thunder"], speed=0.0,
            )],
        )
        sim.setup()
        log = sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert log is not None
        assert log.enemy_broken
        assert sim.enemies[0].is_broken
        sim.run()
        assert sim.enemies[0].is_broken

    def test_multiple_enemies_none_in_queue(self):
        """多只木桩均在 enemies 中，且都不进入行动队列。"""
        enemies = [
            EnemyState(
                unit_id=f"e{i}", name="木桩",
                max_toughness=60, current_toughness=60,
                weakness_elements=["Thunder"], speed=0.0,
            )
            for i in range(1, 4)
        ]
        sim = BattleSimulator(characters=[_make_char()], enemies=enemies)
        sim.setup()
        assert len(sim.enemies) == 3
        assert all(sim.action_queue.get(e.unit_id) is None for e in enemies)

    def test_non_weak_resistance_applied_in_damage(self):
        """非弱点抗性配置经 damage 路径生效。"""
        char = _make_char()  # 属性 Thunder
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=100,
            weakness_elements=["Fire"], speed=0.0,
            resistance=build_enemy_resistance(["Fire"], 0.4),
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy])
        sim.setup()
        log = sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert log is not None
        # 1000 × 1.0 × 0.9(未击破减伤) × 0.5(80级防御) × 0.6(非弱点抗性 40%)
        assert log.damages[0] == pytest.approx(1000 * 0.9 * 0.5 * 0.6)


# ── HP 模型 / 死亡离场 ─────────────────────────────────────


class TestEnemyHp:
    def test_enemy_hp_initialized_to_max(self):
        """current_hp 默认满血（取 max_hp）。"""
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=60, current_toughness=60,
            weakness_elements=[], max_hp=500,
        )
        assert enemy.current_hp == 500
        assert not enemy.is_dead

    def test_enemy_hp_reduced_by_damage(self):
        """伤害扣血：1000 × 1.0 × 0.5（防御）= 500。"""
        char = _make_char()
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
            max_hp=100000,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy])
        sim.setup()
        sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert enemy.current_hp == pytest.approx(100000 - 500)
        assert not enemy.is_dead

    def test_enemy_death_removes_from_field(self):
        """HP 归零判定死亡并离场。"""
        char = _make_char()
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
            max_hp=100,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy])
        sim.setup()
        sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert enemy.is_dead
        assert enemy not in sim.enemies

    def test_all_enemies_dead_ends_battle(self):
        """全部敌人死亡时战斗强制结束。"""
        char = _make_char()
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
            max_hp=100,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy])
        sim.setup()
        result = sim.run(actions=[
            PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"),
        ])
        assert result.end_reason == BattleEndReason.ALL_ENEMIES_DEAD
        assert sim.enemies == []

    def test_partial_death_keeps_others(self):
        """击杀一个敌人后其余敌人仍在场。"""
        char = _make_char()
        enemies = [
            EnemyState(
                unit_id="e1", name="木桩1",
                max_toughness=100, current_toughness=0,
                weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
                max_hp=100,
            ),
            EnemyState(
                unit_id="e2", name="木桩2",
                max_toughness=100, current_toughness=0,
                weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
                max_hp=100000,
            ),
        ]
        sim = BattleSimulator(characters=[char], enemies=enemies)
        sim.setup()
        sim.step(PlayerAction(unit_id="c1", skill_type=SkillType.NORMAL, target_id="e1"))
        assert [e.unit_id for e in sim.enemies] == ["e2"]
        assert sim.enemies[0].current_hp == pytest.approx(100000)


# ── 我方角色 HP 管理 ───────────────────────────────────────


class TestCharacterHp:
    def test_character_hp_initialized_to_full(self):
        """我方角色 HP 在战斗开始时初始化为面板生命上限。"""
        char = _make_char()
        char.base_stats = BaseStats(atk_base=1000, spd_base=100, energy_max=100, hp_base=5000)
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy])
        sim.setup()
        assert char.current_hp == pytest.approx(5000)


# ── 敌方攻击配置（木桩按总行动值强制攻击）────────────────────


class TestEnemyAttack:
    def test_enemy_attack_forced_at_total_av(self):
        """木桩速度 0，行动值推进到配置值即强制攻击（扣血 + 回能）。"""
        char = _make_char()
        char.base_stats = BaseStats(
            atk_base=1000, spd_base=100, energy_max=100, hp_base=5000, def_base=500,
        )
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
        )
        attack = EnemyAttack(
            total_av=50, source_enemy_index=0, attack=1000, target_indices=[0], energy_recover=30,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy], enemy_attacks=[attack])
        sim.setup()
        sim.run()  # 默认逻辑（普攻优先，无技能则无伤害）
        logs = [l for l in sim.logs if l.action_type == "enemy_attack"]
        assert len(logs) == 1
        assert logs[0].total_av == pytest.approx(50)
        assert logs[0].actor_id == "e1"  # 释放来源 = 场上第 1 个敌人
        assert logs[0].damage_records[0].target_id == "c1"
        # 敌人攻击角色防御系数 = (10×80+200) / (10×80+200+500) = 1000/1500
        def_coeff = (10 * 80 + 200) / (10 * 80 + 200 + 500)
        assert char.current_hp == pytest.approx(5000 - 1000 * def_coeff)
        assert char.energy == pytest.approx(30)

    def test_enemy_attack_energy_recover_applies_regen(self):
        """敌方攻击回能应吃角色的能量恢复效率加成。"""
        char = _make_char()
        char.base_stats = BaseStats(
            atk_base=1000, spd_base=100, energy_max=100, hp_base=5000,
            def_base=500, energy_regen=0.5,
        )
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
        )
        attack = EnemyAttack(
            total_av=50, source_enemy_index=0, attack=0,
            target_indices=[0], energy_recover=30,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy], enemy_attacks=[attack])
        sim.setup()
        sim.run()
        assert char.energy == pytest.approx(45.0)  # 30 × (1 + 0.5)

    def test_deal_true_damage_bypasses_formula(self):
        """真实伤害只按传入值扣血，并记录 DamageType.TRUE。"""
        char = _make_char()
        char.base_stats = BaseStats(
            atk_base=1000, spd_base=100, energy_max=100, hp_base=5000,
            def_base=500,
        )
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_hp=100000, current_hp=100000,
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy])
        sim.setup()
        log = sim.make_follow_up_log(char, enemy, notes="真实伤害测试")
        amount = sim.deal_true_damage(char, enemy, 100.0, log=log)
        assert amount == 100.0
        assert enemy.current_hp == pytest.approx(100000 - 100)
        assert log.damage_records[-1].damage_type == DamageType.TRUE
        assert log.total_damage == pytest.approx(100.0)

    def test_enemy_attack_multi_target(self):
        """敌方攻击可多选角色：一次攻击命中多个目标。"""
        char1 = _make_char()
        char1.base_stats = BaseStats(
            atk_base=1000, spd_base=100, energy_max=100, hp_base=5000, def_base=500,
        )
        char2 = _make_char()
        char2.unit_id = "c2"
        char2.base_stats = BaseStats(
            atk_base=1000, spd_base=120, energy_max=100, hp_base=4000, def_base=400,
        )
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0.0,
        )
        attack = EnemyAttack(
            total_av=50, source_enemy_index=0, attack=1000,
            target_indices=[0, 1], energy_recover=0,
        )
        sim = BattleSimulator(
            characters=[char1, char2], enemies=[enemy], enemy_attacks=[attack],
        )
        sim.setup()
        sim.run()
        logs = [l for l in sim.logs if l.action_type == "enemy_attack"]
        assert len(logs) == 1
        # 两个目标都被扣血
        def_coeff1 = (10 * 80 + 200) / (10 * 80 + 200 + 500)
        def_coeff2 = (10 * 80 + 200) / (10 * 80 + 200 + 400)
        assert char1.current_hp == pytest.approx(5000 - 1000 * def_coeff1)
        assert char2.current_hp == pytest.approx(4000 - 1000 * def_coeff2)
        # 两条伤害记录
        assert len(logs[0].damage_records) == 2
