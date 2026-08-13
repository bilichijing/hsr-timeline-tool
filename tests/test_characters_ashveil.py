"""不死途（Ashveil, char_id=1504）技能模块单元测试。

技能数据取自 nanoka 真实数据（version 4.4.55），测试统一用 L10 参数。
"""

import pytest

from src.core.characters import AshveilModule, get_module_cls
from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
from src.core.skill import SkillType


# ── 技能原始数据（L1-L10，取自 nanoka 1504）──────────────────


def _levels_linear(first: list[float], last: list[float], count: int = 10) -> list[list[float]]:
    """按首尾线性插值构造 count 级参数表（测试用，仅 L10 数值参与断言）。"""
    rows = []
    for i in range(count):
        t = i / (count - 1)
        rows.append(
            [a + (b - a) * t for a, b in zip(first, last)]
        )
    return rows


def _ashveil_skills_raw():
    """不死途四个技能的 nanoka 原始结构（新版 type + level）。"""
    return {
        "150401": {
            "id": 150401, "name": "利爪，授以礼仪", "type": "Normal", "type_name": "普攻",
            "sp_base": 20, "bp_need": -1, "bp_add": 1,
            "show_stance_list": [30, 0, 0],
            "level": {str(i + 1): {"param_list": [0.5 + 0.1 * i]} for i in range(10)},
        },
        "150402": {
            "id": 150402, "name": "鞭哨，逐尽恶兽", "type": "BPSkill", "type_name": "战技",
            "sp_base": 30, "bp_need": 1,
            "show_stance_list": [60, 0, 0],
            "level": {
                str(i + 1): {"param_list": [1 + i / 9, 1, 0.5 + 0.5 * i / 9, 0.2 + 0.2 * i / 9, 1]}
                for i in range(10)
            },
        },
        "150403": {
            "id": 150403, "name": "飨宴，自始无终", "type": "Ultra", "type_name": "终结技",
            "sp_base": 5, "bp_need": -1,
            "show_stance_list": [90, 0, 0],
            "level": {
                str(i + 1): {"param_list": [2 + 2 * i / 9, 3, 4, 1 + i / 9]}
                for i in range(10)
            },
        },
        "150404": {
            "id": 150404, "name": "宿怨，切齿奉还", "type": None, "type_name": "天赋",
            "sp_base": 5, "bp_need": -1,
            "show_stance_list": [15, 0, 0],
            "level": {
                str(i + 1): {"param_list": [2, 3, 1, 1 + i / 9, 2, 12, 8]}
                for i in range(10)
            },
        },
        "150407": {
            "id": 150407, "name": "吃吧，可憎的手", "type": "Maze", "type_name": "秘技",
            "level": {
                str(i + 1): {"param_list": [10.0, 1.0, 1.0]}
                for i in range(10)
            },
        },
        # 迷宫普攻（同为 Technique 类型但无参数，真实数据存在，秘技查找必须避开它）
        "150406": {
            "id": 150406, "name": "利爪，授以礼仪", "type": "MazeNormal", "type_name": "",
            "level": {"1": {"param_list": []}},
        },
    }


def _make_ashveil() -> CharacterUnit:
    """构造不死途角色（L10 技能，终结技耗能 150）。"""
    from src.core.skill import parse_all_skills

    char = CharacterUnit(
        unit_id="ashveil",
        name="不死途",
        path="Rogue",
        element="Thunder",
        level=80,
        char_id="1504",
    )
    from src.core.stats import BaseStats, StatBonus

    char.base_stats = BaseStats(atk_base=1000, spd_base=100, energy_max=100)
    char.bonus_stats = StatBonus()
    char.skills = parse_all_skills(_ashveil_skills_raw(), level=10, ultra_energy_cost=150)
    return char


def _make_teammate() -> CharacterUnit:
    """构造预设队友（普攻/战技/终结技）。"""
    char = CharacterUnit(
        unit_id="mate",
        name="队友",
        path="Rogue",
        element="Thunder",
        level=80,
    )
    from src.core.stats import BaseStats, StatBonus

    # 速度 50：保证不死途（100）在行动队列中先行动
    char.base_stats = BaseStats(atk_base=1000, spd_base=50, energy_max=100)
    char.bonus_stats = StatBonus()
    char.skills = {
        "mate_normal": _make_preset_skill("mate_normal", "普攻", SkillType.NORMAL, 1.0),
        "mate_skill": _make_preset_skill("mate_skill", "战技", SkillType.SKILL, 1.5),
        "mate_ultra": _make_preset_skill("mate_ultra", "终结技", SkillType.ULTRA, 2.0),
    }
    return char


def _make_preset_skill(skill_id: str, name: str, skill_type: SkillType, mult: float):
    from src.core.damage import DamageType
    from src.core.skill import Skill, SkillEffect

    return Skill(
        id=skill_id,
        name=name,
        skill_type=skill_type,
        sp_cost=-1 if skill_type == SkillType.NORMAL else (1 if skill_type == SkillType.SKILL else 0),
        energy_cost=100 if skill_type == SkillType.ULTRA else 0,
        effects=[SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=mult,
            toughness_damage=10,
            element="Thunder",
        )],
    )


def _make_battle() -> BattleSimulator:
    """构造战斗：不死途 + 队友 vs 2 敌人。

    速度设置：不死途 100、队友/敌人 50——不死途在行动队列中始终先行动，
    step 驱动的战技/终结技测试无需担心行动者切换。
    """
    sim = BattleSimulator(
        characters=[_make_ashveil(), _make_teammate()],
        enemies=[
            EnemyState(
                unit_id="enemy_a", name="敌人A",
                max_toughness=300, current_toughness=300,
                weakness_elements=["Thunder"],
                speed=50,
            ),
            EnemyState(
                unit_id="enemy_b", name="敌人B",
                max_toughness=300, current_toughness=300,
                weakness_elements=["Thunder"],
                speed=50,
            ),
        ],
    )
    sim.setup()
    return sim


def _allied_attack(sim: BattleSimulator, unit_id: str, target_id: str) -> None:
    """队友/任意角色攻击指定目标（走公共打伤害 API，触发攻击命中钩子）。

    不经过行动队列调度，直接结算一段普攻伤害。
    """
    char = next(c for c in sim.characters if c.unit_id == unit_id)
    target = next(e for e in sim.enemies if e.unit_id == target_id)
    effect = next(
        s.effects[0] for s in char.skills.values()
        if s.skill_type == SkillType.NORMAL and s.effects
    )
    # 不创建日志（log=None），仅结算伤害并触发攻击命中钩子
    sim.deal_damage(char, target, effect, skill_type=SkillType.NORMAL, log=None)


# ── 战斗开始 ────────────────────────────────────────────────


class TestBattleStart:
    def test_charge_initialized_from_talent(self):
        """初始充能 = 天赋 #1(2) + 秘技进战充能 #3(1) = 3。"""
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        assert module.charge == 3

    def test_first_enemy_becomes_bait(self):
        """战斗开始：首个敌人直接成为饲饵 → 敌方全体减防 0.4。"""
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        assert module.bait_unit_id == "enemy_a"
        assert all(e.def_reduce == pytest.approx(0.4) for e in sim.enemies)

    def test_technique_battle_start_damage(self):
        """秘技进战：对敌方全体造成攻击力 100% 雷伤（技能类型=秘技）。"""
        sim = _make_battle()
        techniques = [l for l in sim.logs if l.action_type == "technique"]
        assert len(techniques) == 2  # 敌方全体（2 个敌人）
        for log in techniques:
            assert log.actor_id == "ashveil"
            assert len(log.damage_records) == 1
            assert log.damage_records[0].skill_type.value == "Technique"
            # 1000 × 1.0 × 未击破 0.9 × 防御系数（减防 0.4 已生效）
            assert log.total_damage == pytest.approx(1000 * 1.0 * 0.9 * 100 / 160)

    def test_module_mounted_by_char_id(self):
        sim = _make_battle()
        assert isinstance(sim.char_modules["ashveil"], AshveilModule)
        assert "mate" not in sim.char_modules  # 预设队友无 char_id 不挂载


# ── 饲饵标记 ────────────────────────────────────────────────


class TestBaitMarking:
    def test_skill_marks_target_as_bait(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))
        assert module.bait_unit_id == "enemy_a"
        # 有饲饵 → 敌方全体减防 = 战技 #4（L10 = 0.4）
        assert all(e.def_reduce == pytest.approx(0.4) for e in sim.enemies)

    def test_skill_on_existing_bait_extra_damage_and_sp(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        # 先标记 enemy_a 为饲饵
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))
        sp_before = sim.sp.current
        # 再战技同一目标：额外段伤害 + 回 1 SP（战技本身消耗 1，净变化 0）
        log = sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))
        # 伤害顺序：额外段（on_skill_cast 先结算，L10 倍率 1.0）+ 战技首段（L10 倍率 2.0）
        assert len(log.damages) == 2
        assert log.damages[0] == pytest.approx(log.damages[1] / 2)
        assert sim.sp.current == sp_before

    def test_skill_switches_bait_to_newest_target(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_b"))
        # 仅最新目标生效
        assert module.bait_unit_id == "enemy_b"

    def test_skill_extra_damage_only_when_target_is_bait(self):
        sim = _make_battle()
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))
        # 战技打非饲饵目标：无额外段
        log = sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_b"))
        assert len(log.damages) == 1


# ── 天赋追加攻击 ────────────────────────────────────────────


class TestTalentTrigger:
    def _setup_bait(self, sim: BattleSimulator) -> None:
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))

    def test_allied_attack_on_bait_triggers_follow_up(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        self._setup_bait(sim)

        _allied_attack(sim, "mate", "enemy_a")

        # 不死途的追加攻击日志
        follow_ups = [l for l in sim.logs if l.action_type == "follow_up" and l.actor_id == "ashveil"]
        assert len(follow_ups) == 1
        log = follow_ups[0]
        assert log.target_id == "enemy_a"
        # 双维度：技能类型 FOLLOW_UP × 伤害类型 NORMAL
        assert len(log.damage_records) == 1
        assert log.damage_records[0].skill_type == SkillType.FOLLOW_UP
        assert log.damage_records[0].damage_type.value == "normal"
        # 伤害 = 1000 × 天赋 #4（L10 = 2.0）× 未击破减伤 0.9
        #         × 防御系数（80级 vs 80级，饲饵存在时敌方减防 0.4 已生效）
        assert log.total_damage == pytest.approx(1000 * 2.0 * 0.9 * 100 / 160)

    def test_charge_consumed_and_greed_gained(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        self._setup_bait(sim)
        assert module.charge == 3  # 初始 2 + 秘技进战 1

        _allied_attack(sim, "mate", "enemy_a")

        assert module.charge == 2  # 消耗 1 点充能
        assert module.greed == 2   # 获得 2 层婪酣

    def test_energy_recovered_on_bait_hit(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        self._setup_bait(sim)
        ash = sim.characters[0]
        energy_before = ash.energy

        _allied_attack(sim, "mate", "enemy_a")

        # 天赋 #7 固定回能 8 + 追加攻击回能 5（天赋 sp_base）= 13
        assert ash.energy - energy_before == pytest.approx(13.0)

    def test_attack_on_non_bait_does_not_trigger(self):
        sim = _make_battle()
        self._setup_bait(sim)
        # 队友攻击非饲饵目标
        _allied_attack(sim, "mate", "enemy_b")
        assert all(l.action_type != "follow_up" for l in sim.logs)

    def test_own_attack_on_bait_does_not_trigger(self):
        """防自激：不死途自己的攻击（含追打自身）不触发天赋（无 8 点固定回能）。"""
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        self._setup_bait(sim)
        charge_before = module.charge
        ash = sim.characters[0]
        energy_before = ash.energy

        _allied_attack(sim, "ashveil", "enemy_a")

        assert module.charge == charge_before
        assert ash.energy == energy_before  # 天赋 #7 固定回能不触发
        follow_ups = [l for l in sim.logs if l.action_type == "follow_up"]
        assert len(follow_ups) == 0

    def test_no_follow_up_when_charge_empty(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        self._setup_bait(sim)
        module.charge = 0
        ash = sim.characters[0]
        energy_before = ash.energy

        _allied_attack(sim, "mate", "enemy_a")

        # 只回能，不追打
        assert ash.energy - energy_before == 8
        assert all(l.action_type != "follow_up" for l in sim.logs)

    def test_greed_capped_at_max(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        self._setup_bait(sim)
        module.greed = 11  # 接近上限 12

        _allied_attack(sim, "mate", "enemy_a")

        assert module.greed == 12


# ── 终结技 ──────────────────────────────────────────────────


class TestUltraChain:
    def _prepare(self, sim: BattleSimulator, greed: int = 0) -> AshveilModule:
        """设置饲饵并直接调整模块状态，聚焦终结技链本身。"""
        module = sim.char_modules["ashveil"]
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))
        module.greed = greed
        return module

    def test_ultra_requires_energy(self):
        sim = _make_battle()
        ash = sim.characters[0]
        # 能量不足：execute_ultra 返回 None
        assert sim.execute_ultra(0) is None

        ash.energy = 149
        assert sim.execute_ultra(0) is None

    def test_ultra_marks_bait_and_deals_first_hit(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        ash = sim.characters[0]
        ash.energy = 150
        module.greed = 0

        log = sim.execute_ultra(0)

        assert log is not None
        assert module.bait_unit_id == "enemy_a"
        # 终结技首段（L10 倍率 4.0）：饲饵先标记 → 敌方减防 0.4 已生效
        # 伤害 = 1000 × 4.0 × 未击破减伤 0.9 × 防御系数（80级 vs 80级 + 减防0.4）
        assert log.damages[0] == pytest.approx(1000 * 4.0 * 0.9 * 100 / 160)
        # 耗能 150 后：终结技回能 5（sp_base）+ 强化追打回能 5（天赋 sp_base）= 10
        assert ash.energy == pytest.approx(10.0)

    def test_ultra_gives_charge_capped(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        ash = sim.characters[0]
        ash.energy = 150
        assert module.charge == 3  # 初始 2 + 秘技进战 1

        sim.execute_ultra(0)

        # 获得 #2=3 点，钳制到上限 3（已满则不变）
        assert module.charge == 3

    def test_ultra_free_strike_does_not_consume_charge(self):
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        ash = sim.characters[0]
        ash.energy = 150
        sim.execute_ultra(0)

        follow_ups = [l for l in sim.logs if l.action_type == "follow_up"]
        assert len(follow_ups) == 1  # 仅免费强化追打
        assert module.charge == 3    # 未消耗充能

    def test_ultra_consumes_greed_per_4(self):
        sim = _make_battle()
        module = self._prepare(sim, greed=4)
        ash = sim.characters[0]
        ash.energy = 150

        sim.execute_ultra(0)

        # 免费 1 段 + 消耗 4 层额外 1 段 = 2 段追打
        follow_ups = [l for l in sim.logs if l.action_type == "follow_up"]
        assert len(follow_ups) == 2
        assert module.greed == 0

    def test_ultra_greed_9_consumes_twice(self):
        sim = _make_battle()
        module = self._prepare(sim, greed=9)
        ash = sim.characters[0]
        ash.energy = 150

        sim.execute_ultra(0)

        # 9 // 4 = 2 段，剩 1 层
        follow_ups = [l for l in sim.logs if l.action_type == "follow_up"]
        assert len(follow_ups) == 3
        assert module.greed == 1

    def test_ultra_greed_below_cost_only_free_strike(self):
        sim = _make_battle()
        module = self._prepare(sim, greed=3)
        ash = sim.characters[0]
        ash.energy = 150

        sim.execute_ultra(0)

        follow_ups = [l for l in sim.logs if l.action_type == "follow_up"]
        assert len(follow_ups) == 1
        assert module.greed == 3

    def test_ultra_greed_strikes_no_energy(self):
        """婪酣额外攻击不提供追加攻击回能：仅终结技 5 + 免费强化追打 5 = 10。"""
        sim = _make_battle()
        module = self._prepare(sim, greed=8)  # 2 段额外攻击
        ash = sim.characters[0]
        ash.energy = 150

        sim.execute_ultra(0)

        follow_ups = [l for l in sim.logs if l.action_type == "follow_up"]
        assert len(follow_ups) == 3  # 免费 + 2 段婪酣
        # 婪酣段不回能 → 能量 = 150 - 150 + 5 + 5 = 10
        assert ash.energy == pytest.approx(10.0)

    def test_ultra_chain_follow_up_double_dimension(self):
        sim = _make_battle()
        module = self._prepare(sim, greed=4)
        ash = sim.characters[0]
        ash.energy = 150

        sim.execute_ultra(0)

        for l in sim.logs:
            if l.action_type == "follow_up":
                assert all(r.skill_type == SkillType.FOLLOW_UP for r in l.damage_records)
                assert all(r.damage_type.value == "normal" for r in l.damage_records)


# ── 注册表 ──────────────────────────────────────────────────


class TestRegistry:
    def test_get_module_by_char_id(self):
        assert get_module_cls("1504") is AshveilModule

    def test_unknown_char_id_returns_none(self):
        assert get_module_cls("9999") is None


# ── 固定回能不乘能量恢复效率 ───────────────────────────────


class TestFixedEnergyRecover:
    def test_talent_fixed_energy_ignores_energy_regen(self):
        """天赋 #7 固定 8 点回能不受 energy_regen 影响（追加攻击 5 点正常吃乘区）。"""
        sim = _make_battle()
        module = sim.char_modules["ashveil"]
        sim.step(PlayerAction(unit_id="ashveil", skill_type=SkillType.SKILL, target_id="enemy_a"))
        ash = sim.characters[0]
        ash.bonus_stats.energy_regen = 0.5
        energy_before = ash.energy

        _allied_attack(sim, "mate", "enemy_a")

        # 固定 8（不乘 1.5）+ 追加攻击 5 × 1.5 = 8 + 7.5 = 15.5
        assert ash.energy - energy_before == pytest.approx(15.5)


# ── 手动推进与插队终结技的 AV 位置 ─────────────────────────


class TestUltraInterruptTiming:
    def _step_first_action(self, sim: BattleSimulator) -> None:
        """首个行动者行动（setup 后已推进到第一个行动者）。"""
        actor = sim.action_queue.next_actor()
        sim.step(PlayerAction(
            unit_id=actor.unit_id,
            skill_type=SkillType.SKILL if actor.unit_id == "ashveil" else SkillType.NORMAL,
            target_id="enemy_a",
        ))

    def test_action_does_not_advance_automatically(self):
        """释放技能后不自动推进：total_av 停在行动者位置，需手动 advance_av。"""
        sim = _make_battle()
        av_before = sim.total_av  # setup 后已推进到第一个行动者
        self._step_first_action(sim)
        # 行动后未推进：total_av 不变
        assert sim.total_av == pytest.approx(av_before)

    def test_interrupt_after_action_stays_at_actor_position(self):
        """行动后插队终结技：位置停在行动者位置（B 行动后 = 200）。"""
        sim = _make_battle()
        self._step_first_action(sim)
        actor_pos = sim.total_av  # 行动者位置（未推进）
        sim.characters[0].energy = 150

        log = sim.execute_ultra(0)

        assert log.total_av == pytest.approx(actor_pos)
        assert sim.total_av == pytest.approx(actor_pos)

    def test_advance_then_interrupt_at_new_position(self):
        """推进后插队终结技：位置在下个行动者的行动位置（轮到 C = 250）。"""
        sim = _make_battle()
        self._step_first_action(sim)
        advanced = sim.advance_av()
        assert advanced > 0  # 推进到下个行动者
        new_pos = sim.total_av
        sim.characters[0].energy = 150

        log = sim.execute_ultra(0)

        assert log.total_av == pytest.approx(new_pos)

    def test_advance_av_idempotent(self):
        """重复推进不重复累加。"""
        sim = _make_battle()
        first = sim.advance_av()
        assert sim.advance_av() == 0.0  # 已推进到当前行动者
        assert sim.total_av == pytest.approx(first)

    def test_advance_after_action_reaches_next_actor(self):
        """行动后推进：total_av 到达下个行动者的位置。"""
        sim = _make_battle()
        self._step_first_action(sim)
        actor = sim.action_queue.next_actor()
        expected = sim.total_av + actor.current_av

        sim.advance_av()

        assert sim.total_av == pytest.approx(expected)
        assert sim.pending_av_actor == actor.unit_id

    def test_snapshot_restore_preserves_pending(self):
        """快照/回溯保留推进标记。"""
        sim = _make_battle()
        snap_before = sim.snapshot()
        sim.advance_av()
        assert sim.pending_av_actor is not None
        sim.restore(snap_before)
        assert sim.pending_av_actor is None
        assert sim.total_av == 0.0
