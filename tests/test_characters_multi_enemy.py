"""多敌人环境下角色技能模块（全体 / 随机 / 相邻）的单元测试。

复用各角色测试文件的角色构造 helper（跨测试文件 import 已在项目中使用）。
"""

from __future__ import annotations

import pytest

from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
from src.core.skill import SkillType
from src.core.stats import BaseStats

from test_characters_mortenax import _make_mortenax
from test_characters_tribbie import (
    A2_RATIO,
    EXTRA_MULT,
    FIELD_VULN,
    NORMAL_MULT,
    ULTRA_MULT,
    _dmg,
    _make_tribbie,
)

FIRE = "Fire"
QUANTUM = "Quantum"


def _make_enemies(n: int, *, element: str, broken: bool = True) -> list[EnemyState]:
    return [
        EnemyState(
            unit_id=f"e{i + 1}", name=f"木桩{i + 1}",
            max_toughness=100, current_toughness=0 if broken else 100,
            weakness_elements=[element], is_broken=broken, level=80, speed=0,
        )
        for i in range(n)
    ]


def _mortenax_sim(n: int, broken: bool = True) -> tuple[BattleSimulator, list[EnemyState]]:
    char = _make_mortenax()
    enemies = _make_enemies(n, element=FIRE, broken=broken)
    sim = BattleSimulator(characters=[char], enemies=enemies, max_av=100000)
    sim.setup()
    return sim, enemies


def _open_rage_freeze(sim: BattleSimulator) -> None:
    """千冶开结界并冻结倒计时（结界内多次行动用）。"""
    sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.ULTRA, target_id="e1"))
    mod = sim.char_modules["mortenax"]
    if mod.countdown_unit_id:
        entry = sim.action_queue.get(mod.countdown_unit_id)
        if entry is not None:
            entry.current_av = 999999.0


def _def_factor(def_reduce: float) -> float:
    return 100 / (100 + 100 * (1 - def_reduce))


# ── 千冶·刃：全体 / 随机 ──────────────────────────────────


class TestMortenaxMultiEnemy:
    def test_skill_aoe_hits_all_enemies(self):
        """战技「刃下，归葬」全体主伤害打到所有敌人（随机段总伤害不变）。"""
        sim, enemies = _mortenax_sim(2)
        _open_rage_freeze(sim)
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.SKILL, target_id="e1"))
        df = _def_factor(0.2)
        # 全体 2 敌 × 3600 + 4 随机 × 1200，× 易伤 1.3 × 防御系数
        assert sim.logs[-1].total_damage == pytest.approx(
            (3600 * 2 + 4 * 1200) * 1.3 * df
        )
        # 全体煞火缠身（开结界）对两敌均生效
        assert enemies[0].def_reduce == pytest.approx(0.2)
        assert enemies[1].def_reduce == pytest.approx(0.2)

    def test_skill_aoe_reduces_toughness_all_enemies(self):
        """战技全体主伤害的削韧作用于所有敌人（各 -15）。"""
        sim, enemies = _mortenax_sim(2, broken=False)
        _open_rage_freeze(sim)
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.SKILL, target_id="e1"))
        # 全体首段各削 10；后续 4 次弹射各削 5。
        # 两敌总削韧 = 2×10 + 4×5 = 40。
        assert all(e.current_toughness <= 90 for e in enemies)
        assert sum(e.current_toughness for e in enemies) == pytest.approx(200 - 40)

    def test_skill_aoe_applies_blaze_to_each_enemy(self):
        """全体攻击命中谁就给谁上煞火缠身，充能仍按行动只计 1 点。"""
        sim, enemies = _mortenax_sim(2)
        _open_rage_freeze(sim)  # 终结技 → 全体煞火缠身
        mod = sim.char_modules["mortenax"]
        # e2 的煞火缠身到期（2 个敌方回合后撤销）
        for _ in range(2):
            mod.on_enemy_act(sim, enemies[1], sim.logs[0])
        assert enemies[0].def_reduce == pytest.approx(0.2)  # e1 仍在
        assert enemies[1].def_reduce == pytest.approx(0.0)  # e2 已撤销
        # 全体战技：e1/e2 各自重新陷入煞火缠身；充能只 +1
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.SKILL, target_id="e1"))
        assert enemies[0].def_reduce == pytest.approx(0.2)
        assert enemies[1].def_reduce == pytest.approx(0.2)
        assert enemies[1].vulnerability == pytest.approx(0.3)
        assert mod.charge == pytest.approx(1)

    def test_enhanced_ultra_aoe(self):
        """强化终结技「千冶铸一，万劫烬灭」210% 全体：每个敌人独立承受。"""
        sim, _ = _mortenax_sim(2)
        _open_rage_freeze(sim)
        char = sim.characters[0]
        char.energy = 160
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.ULTRA, target_id="e1"))
        df = _def_factor(0.2)
        # 21000 × 2 敌 × 易伤 1.3 × 防御系数
        assert sim.logs[-1].total_damage == pytest.approx(21000 * 2 * 1.3 * df)

    def test_talent_extra_skill_aoe(self):
        """天赋额外战技：全体首段 + 随机段（视为追加攻击，独立日志）。"""
        sim, _ = _mortenax_sim(2)
        _open_rage_freeze(sim)
        mod = sim.char_modules["mortenax"]
        mod.charge = 8
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.NORMAL, target_id="e1"))
        fu = [l for l in sim.logs if l.action_type == "follow_up"]
        assert fu and "追加战技" in fu[-1].notes
        df = _def_factor(0.2)
        assert fu[-1].total_damage == pytest.approx((3600 * 2 + 4 * 1200) * 1.3 * df)


# ── 缇宝：全体 / 相邻 ─────────────────────────────────────


class TestTribbieMultiEnemy:
    def test_ultra_aoe_hits_all_enemies(self):
        """终结技「猜猜这里住着谁」全体 15%：每个敌人独立承受 + 1 段附加伤害。"""
        char = _make_tribbie()
        enemies = _make_enemies(2, element=QUANTUM)
        sim = BattleSimulator(characters=[char], enemies=enemies, max_av=100000)
        sim.setup()
        char.energy = char.base_stats.energy_max
        sim.execute_ultra(0)
        hp = 10000 * (1 + A2_RATIO)  # A2：单角色 HP = 10000 × 1.09
        # 全体 2 敌 × 本体 15% + 1 段附加 6%
        assert sim.logs[-1].total_damage == pytest.approx(
            2 * _dmg(hp, ULTRA_MULT, 1 + FIELD_VULN) + _dmg(hp, EXTRA_MULT, 1 + FIELD_VULN)
        )

    def test_normal_adjacent_targets(self):
        """普攻「一百层的小火箭」相邻目标伤害：主目标左右各一名。"""
        char = _make_tribbie()
        enemies = _make_enemies(3, element=QUANTUM)
        sim = BattleSimulator(characters=[char], enemies=enemies, max_av=100000)
        sim.setup()
        # 主目标 e2：相邻 = e1（左）+ e3（右）
        sim.step(PlayerAction(unit_id="tribbie", skill_type=SkillType.NORMAL, target_id="e2"))
        # 主目标 15% + 相邻 2 × 7.5%
        assert sim.logs[-1].total_damage == pytest.approx(
            _dmg(10000, NORMAL_MULT) + 2 * _dmg(10000, NORMAL_MULT / 2)
        )

    def test_normal_adjacent_edge_only_right(self):
        """主目标在最左侧（e1）时仅命中右邻 e2。"""
        char = _make_tribbie()
        enemies = _make_enemies(3, element=QUANTUM)
        sim = BattleSimulator(characters=[char], enemies=enemies, max_av=100000)
        sim.setup()
        sim.step(PlayerAction(unit_id="tribbie", skill_type=SkillType.NORMAL, target_id="e1"))
        # 主目标 15% + 右邻 7.5%（无左邻）
        assert sim.logs[-1].total_damage == pytest.approx(
            _dmg(10000, NORMAL_MULT) + _dmg(10000, NORMAL_MULT / 2)
        )


# ── 随机目标可复现 ─────────────────────────────────────────


class TestRandomTarget:
    def test_random_enemy_deterministic_same_seed(self):
        """同一 rng_seed 下，随机单体目标序列可复现。"""

        def sequence() -> list[str]:
            char = CharacterUnit(unit_id="c1", name="测试", path="Rogue", element=FIRE, level=80)
            char.base_stats = BaseStats(spd_base=100, energy_max=100)
            enemies = _make_enemies(3, element=FIRE)
            sim = BattleSimulator(characters=[char], enemies=enemies, rng_seed=42)
            sim.setup()
            return [sim.random_enemy().unit_id for _ in range(20)]

        assert sequence() == sequence()

    def test_random_enemy_only_returns_enemies(self):
        """random_enemy 只从场上敌人中选取。"""
        char = CharacterUnit(unit_id="c1", name="测试", path="Rogue", element=FIRE, level=80)
        char.base_stats = BaseStats(spd_base=100, energy_max=100)
        enemies = _make_enemies(4, element=FIRE)
        sim = BattleSimulator(characters=[char], enemies=enemies, rng_seed=7)
        sim.setup()
        ids = {e.unit_id for e in enemies}
        for _ in range(100):
            assert sim.random_enemy().unit_id in ids


# ── 敌方 debuff 展示（enemy_buffs 钩子）──────────────────────


class TestEnemyBuffDisplay:
    def test_ashveil_bait_shows_bait_debuff(self):
        """不死途饲饵目标在敌方 buff 中显示饲饵条目。"""
        from test_characters_ashveil import _make_ashveil

        ash = _make_ashveil()
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=["Thunder"], is_broken=True, level=80, speed=0,
        )
        sim = BattleSimulator(characters=[ash], enemies=[enemy])
        sim.setup()
        buffs = sim.char_modules["ashveil"].enemy_buffs(sim, enemy)
        assert any(name == "饲饵" for name, _ in buffs)
        assert any("不死途的饲饵目标" in desc for _, desc in buffs)

    def test_non_bait_enemy_no_bait_debuff(self):
        """非饲饵目标不显示饲饵标记，但仍显示饲饵的全体减防。"""
        from test_characters_ashveil import _make_ashveil

        ash = _make_ashveil()
        enemies = _make_enemies(2, element="Thunder")
        sim = BattleSimulator(characters=[ash], enemies=enemies)
        sim.setup()
        # 战斗开始饲饵 = e1；e2 不显示"饲饵"标记，但显示全体减防
        buffs = sim.char_modules["ashveil"].enemy_buffs(sim, enemies[1])
        assert not any(name == "饲饵" for name, _ in buffs)
        assert any(name == "饲饵·防御降低" for name, _ in buffs)
        assert any("防御降低" in desc for _, desc in buffs)

    def test_mortenax_blaze_shows_debuff(self):
        """千冶煞火缠身目标显示煞火缠身条目。"""
        char = _make_mortenax()
        enemy = EnemyState(
            unit_id="e1", name="木桩",
            max_toughness=100, current_toughness=0,
            weakness_elements=[FIRE], is_broken=True, level=80, speed=0,
        )
        sim = BattleSimulator(characters=[char], enemies=[enemy], max_av=100000)
        sim.setup()
        sim.step(PlayerAction(unit_id="mortenax", skill_type=SkillType.ULTRA, target_id="e1"))
        buffs = sim.char_modules["mortenax"].enemy_buffs(sim, enemy)
        assert any(name == "煞火缠身" for name, _ in buffs)


# ── 敌人 HP 相关选取（饲饵取生命最低 / 附加伤害取生命最高）──────


class TestHpBasedSelection:
    def _enemy(self, unit_id: str, hp: float, element: str) -> EnemyState:
        return EnemyState(
            unit_id=unit_id, name=unit_id,
            max_toughness=100, current_toughness=0,
            weakness_elements=[element], is_broken=True, level=80, speed=0,
            max_hp=100000, current_hp=hp,
        )

    def test_ashveil_bait_is_lowest_hp(self):
        """战斗开始时，饲饵 = 当前生命值最低的敌人。"""
        from test_characters_ashveil import _make_ashveil

        ash = _make_ashveil()
        enemies = [self._enemy("e1", 80000, "Thunder"), self._enemy("e2", 10000, "Thunder")]
        sim = BattleSimulator(characters=[ash], enemies=enemies)
        sim.setup()
        assert sim.char_modules["ashveil"].bait_unit_id == "e2"

    def test_tribbie_added_damage_targets_highest_hp(self):
        """结界附加伤害命中被攻击目标中生命值最高者。"""
        char = _make_tribbie()
        enemies = [self._enemy("e1", 80000, QUANTUM), self._enemy("e2", 20000, QUANTUM)]
        sim = BattleSimulator(characters=[char], enemies=enemies, max_av=100000)
        sim.setup()
        char.energy = char.base_stats.energy_max
        sim.execute_ultra(0)  # 终结技（全体）→ 附加伤害命中 HP 更高的 e1
        added = [
            r for r in sim.logs[-1].damage_records
            if r.skill_type == SkillType.ADDED
        ]
        assert len(added) == 1
        assert added[0].target_id == "e1"
