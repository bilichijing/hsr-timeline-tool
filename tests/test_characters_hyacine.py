"""风堇（char_id=1409）技能与轻量忆灵小伊卡测试。"""

from __future__ import annotations

import pytest

from src.core.characters import HyacineModule, get_module_cls
from src.core.simulator import BattleSimulator, CharacterUnit, EnemyState, PlayerAction
from src.core.skill import SkillType, parse_all_skills
from src.core.stats import BaseStats, StatBonus


def _lv(params, count=15):
    return {str(i + 1): {"param_list": list(params)} for i in range(count)}


def _skills_raw() -> dict:
    return {
        "140901": {
            "id": 140901, "name": "普攻", "type": "Normal", "type_name": "普攻",
            "sp_base": 20, "bp_need": -1, "bp_add": 1,
            "show_stance_list": [30, 0, 0], "level": _lv([0.25], 10),
        },
        "140902": {
            "id": 140902, "name": "战技", "type": "BPSkill", "type_name": "战技",
            "sp_base": 30, "bp_need": 1,
            "show_stance_list": [0, 0, 0],
            "level": _lv([0.04, 40, 0.05, 50]),
        },
        "140903": {
            "id": 140903, "name": "终结技", "type": "Ultra", "type_name": "终结技",
            "sp_base": 5, "bp_need": -1,
            "show_stance_list": [0, 0, 0],
            "level": _lv([0.05, 50, 0.15, 150, 3, 0.06, 60]),
        },
        "140904": {
            "id": 140904, "name": "天赋", "type": None, "type_name": "天赋",
            "sp_base": None, "bp_need": -1,
            "level": _lv([0.5, 1, 0.4, 2, 3]),
        },
        "140907": {
            "id": 140907, "name": "秘技", "type": "Maze", "type_name": "秘技",
            "level": {"1": {"param_list": [0.3, 600, 0.2, 2]}},
        },
    }


def _memosprite_raw() -> dict:
    return {
        "skills": {
            "1140901": {
                "name": "乌云乌云快走开！", "type": "Servant", "type_name": "忆灵技",
                "level": _lv([0.1, 0.5], 10),
            },
            "1140903": {
                "name": "牵起晴空的手", "type": None, "type_name": "忆灵天赋",
                "level": {"1": {"param_list": [0.04, 0.01, 10, 0.01, 10]}},
            },
            "1140905": {
                "name": "展翼，奔向日辉", "type": None, "type_name": "忆灵天赋",
                "level": {"1": {"param_list": [15, 30]}},
            },
        }
    }


def _make_hyacine(outgoing_heal: float = 0.0) -> CharacterUnit:
    char = CharacterUnit(
        unit_id="hyacine", name="风堇", path="Memory", element="Wind", level=80,
        char_id="1409",
    )
    char.base_stats = BaseStats(
        hp_base=10000, atk_base=1000, spd_base=100, energy_max=140,
        outgoing_heal=outgoing_heal, crit_rate=0.0,
    )
    char.bonus_stats = StatBonus()
    char.skills = parse_all_skills(_skills_raw(), level=1, ultra_energy_cost=140)
    char.memosprite_raw = _memosprite_raw()
    char.memo_skill_level = 1
    return char


def _make_sim(char: CharacterUnit) -> BattleSimulator:
    enemy = EnemyState(
        unit_id="e1", name="木桩",
        max_hp=100000, current_hp=100000,
        max_toughness=100, current_toughness=100,
        weakness_elements=["Wind"], speed=0,
    )
    sim = BattleSimulator(characters=[char], enemies=[enemy])
    sim.setup()
    return sim


def _module(sim: BattleSimulator) -> HyacineModule:
    return sim.char_modules["hyacine"]


class TestRegistration:
    def test_registered(self):
        assert get_module_cls("1409") is HyacineModule


class TestHealing:
    def test_outgoing_and_incoming_additive(self):
        char = _make_hyacine(outgoing_heal=0.2)
        ally = CharacterUnit(unit_id="ally", name="队友", path="Rogue", element="Thunder", level=80)
        ally.base_stats = BaseStats(hp_base=5000, spd_base=90, energy_max=100, incoming_heal=0.5)
        enemy = EnemyState(
            unit_id="e1", name="木桩", max_hp=100000, current_hp=100000,
            max_toughness=100, current_toughness=100, weakness_elements=["Wind"], speed=0,
        )
        sim = BattleSimulator(characters=[char, ally], enemies=[enemy])
        sim.setup()
        ally.current_hp = 1000
        actual, raw = sim.heal(char, ally, 100)
        # (1 + 0.2 + 0.5) = 1.7，加算
        assert raw == pytest.approx(170)
        assert actual == pytest.approx(170)
        assert ally.current_hp == pytest.approx(1170)


class TestHyacineSkills:
    def test_skill_summons_and_heals(self):
        char = _make_hyacine()
        sim = _make_sim(char)
        module = _module(sim)
        char.current_hp = 5000
        sim.step(PlayerAction(unit_id="hyacine", skill_type=SkillType.SKILL, target_id="e1"))
        assert module.memosprite_alive
        assert module.memosprite_max_hp == pytest.approx(12000 * 0.5)
        assert char.current_hp == pytest.approx(5000 + 0.04 * 12000 + 40)
        assert module.cumulative_healing > 0

    def test_ultra_sunny_max_hp_and_memo_turn(self):
        char = _make_hyacine()
        sim = _make_sim(char)
        module = _module(sim)
        sim.step(PlayerAction(unit_id="hyacine", skill_type=SkillType.SKILL, target_id="e1"))
        char.current_hp = 3000
        char.energy = 140
        sim.execute_ultra(0, target_id="e1")
        assert module.sunny_turns == 3
        # 终结技先治疗 550，随后生命上限提高并保持治疗后的血量比例
        base_after_tech = 10000 * 1.2
        after_heal = 3000 + (0.05 * base_after_tech + 50)
        new_max = 10000 * (1 + 0.2 + 0.15) + 150
        assert char.final_stats().hp == pytest.approx(new_max)
        assert char.current_hp == pytest.approx(new_max * (after_heal / base_after_tech))
        # 终结技后小伊卡额外回合自动忆灵技
        memo_logs = [l for l in sim.logs if l.action_type == "memo_skill"]
        assert memo_logs

    def test_auto_heal_once_per_detection_and_sunny_extra(self):
        char = _make_hyacine()
        sim = _make_sim(char)
        module = _module(sim)
        # 手动召唤小伊卡
        module._summon_memosprite(sim, char)
        module._update_hp_snapshot(sim)
        char.current_hp -= 1000
        module._check_auto_heal(sim)
        expected_cost = module.memosprite_max_hp * 0.04
        assert module.memosprite_hp == pytest.approx(module.memosprite_max_hp - expected_cost)
        assert char.current_hp > 9000  # 已回复
        module.sunny_turns = 1
        hp_before_extra = char.current_hp
        char.current_hp -= 1000
        module._check_auto_heal(sim)
        # 非晴天仍按一个目标治疗；晴天额外回复一次
        assert char.current_hp > hp_before_extra - 1000

    def test_memo_dies_and_leaves(self):
        char = _make_hyacine()
        sim = _make_sim(char)
        module = _module(sim)
        module._summon_memosprite(sim, char)
        module._update_hp_snapshot(sim)
        module.memosprite_hp = 1
        char.current_hp -= 1000
        module._check_auto_heal(sim)
        assert not module.memosprite_alive
        assert module.memosprite_hp == 0


class TestTechniqueBuffExpiry:
    def test_tech_hp_buff_expiry_preserves_ratio(self):
        """秘技生命上限 2 回合后消失，当前生命按剩余比例同步降低。"""
        char = _make_hyacine()
        sim = _make_sim(char)
        module = _module(sim)
        assert char.final_stats().hp == pytest.approx(12000)
        char.current_hp = 6000  # 50%
        module.on_turn_start(sim, char)
        module.on_turn_start(sim, char)
        assert char.final_stats().hp == pytest.approx(10000)
        assert char.current_hp == pytest.approx(5000)


class TestBattleStartAV:
    def test_hyacine_first_av_uses_final_speed(self):
        """风堇第一动行动值应按进战最终速度计算（10000/260≈38.46）。"""
        char = _make_hyacine()
        char.base_stats.spd_base = 110
        # 光锥第一句速度 18% 已计入面板；遗器 125/320 各 +6% 由套装模块在进战挂载
        char.bonus_stats = StatBonus(spd_pct=0.18, spd_flat=117.0)
        char.lightcone_id = "23042"
        char.lightcone_rank = 1
        char.lightcone_params = [0.18, 0.01, 0, 0.18, 2, 2.5]
        char.relic_set_counts = {"125": 4, "320": 2}
        char.relic_set_effects = {
            "125": {"2": [0.06], "4": [0.06, 0.15, 2]},
            "320": {"2": [0.06, 135, 180, 0.12, 0.2]},
        }
        sim = _make_sim(char)
        assert char.final_stats().spd == pytest.approx(260)
        actor = sim.action_queue.next_actor()
        assert actor.unit_id == "hyacine"
        assert actor.speed == pytest.approx(260)
        assert actor.current_av == pytest.approx(10000 / 260)
