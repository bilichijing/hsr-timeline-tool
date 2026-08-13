"""freesr-data.json 解析与面板计算单元测试。

数据来源：项目根目录 freesr-data.json（不死途 1504 真实配置）。
"""

import json
from pathlib import Path

import pytest

from src.core.character_factory import build_character_unit, convert_stats80
from src.core.freesr import (
    calc_relic_bonus,
    calc_sub_affix,
    compute_panel,
    extract_skill_levels,
    lightcone_base_stats,
    parse_freesr,
    parse_relic,
    to_nanoka_skill_id,
)
from src.core.simulator import BattleSimulator, EnemyState
from src.core.skill import SkillType

# 真实 freesr-data.json（项目根目录）
FREESR_PATH = Path(__file__).parent.parent / "freesr-data.json"


def _load_freesr() -> dict:
    return json.loads(FREESR_PATH.read_text(encoding="utf-8"))


# ── 解析 ───────────────────────────────────────────────────


class TestParseFreesr:
    def test_avatar_parsed(self):
        profile = parse_freesr(_load_freesr())
        av = profile.avatars["1504"]
        assert av.rank == 2
        assert av.sp_max == 150
        assert av.sp_value == 75
        assert av.level == 80
        assert av.promotion == 6

    def test_skill_levels_mapped(self):
        profile = parse_freesr(_load_freesr())
        av = profile.avatars["1504"]
        assert av.skill_levels == {
            SkillType.NORMAL: 6,
            SkillType.SKILL: 10,
            SkillType.ULTRA: 10,
            SkillType.TALENT: 10,
        }

    def test_skill_levels_ignore_other_skills(self):
        """秘技/额外能力（1504007、1504101 等）不映射。"""
        levels = extract_skill_levels("1504", {"1504001": 6, "1504007": 1, "1504101": 1})
        assert set(levels) == {SkillType.NORMAL}

    def test_to_nanoka_skill_id(self):
        assert to_nanoka_skill_id("1504001") == "150401"
        assert to_nanoka_skill_id("1504004") == "150404"

    def test_relics_aggregated(self):
        profile = parse_freesr(_load_freesr())
        relics = profile.relics["1504"]
        assert len(relics) == 6
        # 部位 1-6（relic_id 末位）
        assert [r.slot for r in relics] == [1, 2, 3, 4, 5, 6]
        assert {r.relic_set_id for r in relics} == {115, 326}
        assert relics[0].main_affix_id == 1

    def test_lightcones_aggregated(self):
        profile = parse_freesr(_load_freesr())
        lcs = profile.lightcones["1504"]
        assert len(lcs) == 1
        assert lcs[0].item_id == 23056
        assert lcs[0].rank == 1

    def test_empty_avatar_skipped(self):
        data = {"avatars": {"9999": {"avatar_id": 9999, "data": None}, "1504": _load_freesr()["avatars"]["1504"]}}
        profile = parse_freesr(data)
        assert "9999" not in profile.avatars
        assert "1504" in profile.avatars

    def test_relic_without_avatar_dropped(self):
        data = {"avatars": {}, "relics": _load_freesr()["relics"]}
        profile = parse_freesr(data)
        assert profile.relics == {}


# ── 副词条计算 ─────────────────────────────────────────────


class TestCalcSubAffix:
    def test_fixed_value_no_step(self):
        """攻击力 count2 step0 → 16.935×2 = 33.87。"""
        assert calc_sub_affix(2, 2, 0) == pytest.approx(33.87)

    def test_fixed_value_with_step(self):
        """防御力 count2 step2 → 16.935×2 + 2.117×2 = 38.104。"""
        assert calc_sub_affix(3, 2, 2) == pytest.approx(38.104)

    def test_pct_value(self):
        """攻击% count2 step4 → (3.456×2 + 0.432×4)/100 = 0.0864。"""
        assert calc_sub_affix(5, 2, 4) == pytest.approx(0.0864)

    def test_real_relic_sample(self):
        """真实第 6 件遗器：防御 count4 step8 → 16.935×4 + 2.117×8 = 84.676。"""
        assert calc_sub_affix(3, 4, 8) == pytest.approx(84.676)

    def test_unknown_id_returns_zero(self):
        assert calc_sub_affix(99, 2, 2) == 0.0


# ── 主词条解析 ─────────────────────────────────────────────


class TestMainAffix:
    def _relic(self, relic_id: int, main_affix_id: int) -> dict:
        return {"equip_avatar": 1504, "relic_id": relic_id, "main_affix_id": main_affix_id, "sub_affixes": []}

    def test_head_hp_flat(self):
        assert parse_relic(self._relic(61151, 1)).bonus.hp_flat == pytest.approx(705.0)

    def test_hand_atk_flat(self):
        assert parse_relic(self._relic(61152, 1)).bonus.atk_flat == pytest.approx(352.0)

    def test_body_crit_rate(self):
        assert parse_relic(self._relic(61153, 4)).bonus.crit_rate == pytest.approx(0.324)

    def test_body_outgoing_heal(self):
        assert parse_relic(self._relic(61153, 6)).bonus.outgoing_heal == pytest.approx(0.345)

    def test_feet_speed(self):
        assert parse_relic(self._relic(61154, 4)).bonus.spd_flat == pytest.approx(25.0)

    def test_feet_hp_pct(self):
        assert parse_relic(self._relic(61154, 1)).bonus.hp_pct == pytest.approx(0.432)

    def test_orb_atk_pct(self):
        assert parse_relic(self._relic(63265, 2)).bonus.atk_pct == pytest.approx(0.432)

    def test_orb_dmg_bonus(self):
        assert parse_relic(self._relic(63265, 5)).bonus.dmg_bonus == pytest.approx(0.388)

    def test_rope_energy_regen(self):
        assert parse_relic(self._relic(63266, 2)).bonus.energy_regen == pytest.approx(0.194)

    def test_rope_break_effect(self):
        assert parse_relic(self._relic(63266, 1)).bonus.break_effect == pytest.approx(0.648)


# ── 遗器聚合与面板计算 ─────────────────────────────────────


class TestPanel:
    def test_calc_relic_bonus_aggregates(self):
        """6 件遗器主/副词条合并（数值经真实数据验证）。

        hp_flat = 头部主 705 + 遗器2 id1 生命(count2 step2=76.208)
                  + 遗器4 id1 生命(count4 step3=148.182)
        atk_flat = 手部主 352 + 攻击副词条(33.87 + 35.987 + 42.338)
        spd_flat = 速度副词条(遗器2 count2 step2=4.6 + 遗器5 count2 step0=4.0)
        atk_pct = 脚部/位面球/连结绳 攻击%主词条 ×3 + 遗器1 攻击%副词条 0.0864
        crit_rate = 躯干暴击主词条 0.324 + 遗器2 暴击副词条 0.06156
        """
        profile = parse_freesr(_load_freesr())
        total = calc_relic_bonus(profile.relics["1504"])
        assert total.hp_flat == pytest.approx(705.0 + 76.208 + 148.182)
        assert total.atk_flat == pytest.approx(352.0 + 33.87 + 35.987 + 42.338)
        assert total.spd_flat == pytest.approx(8.6)
        assert total.atk_pct == pytest.approx(0.432 * 3 + 0.0864)
        assert total.crit_rate == pytest.approx(0.38556)
        assert total.dmg_bonus == 0.0  # 样本位面球主词条为攻击%，无增伤

    def test_lightcone_base_stats(self):
        row = {"base_hp": 100.0, "base_hp_add": 5.0, "base_attack": 50.0,
               "base_attack_add": 2.0, "base_defence": 30.0, "base_defence_add": 1.0}
        base = lightcone_base_stats(row)
        assert base.hp_base == pytest.approx(100 + 5 * 79)
        assert base.atk_base == pytest.approx(50 + 2 * 79)
        assert base.def_base == pytest.approx(30 + 1 * 79)

    def test_compute_panel_with_lightcone(self):
        profile = parse_freesr(_load_freesr())
        stats80 = {
            "attack_base": 359.04, "attack_add": 5.28,
            "defence_base": 179.52, "defence_add": 2.64,
            "hp_base": 394.944, "hp_add": 5.808,
            "speed_base": 106.0, "critical_chance": 0.05,
            "critical_damage": 0.5, "base_aggro": 75.0,
        }
        lc_row = {"base_hp": 100.0, "base_hp_add": 5.0, "base_attack": 50.0,
                  "base_attack_add": 2.0, "base_defence": 30.0, "base_defence_add": 1.0}
        final = compute_panel(stats80, profile.relics["1504"], lc_row)
        # 攻击 = (角色 776.16 + 光锥 208) × (1 + 攻击% 1.3824) + 固定 464.195
        assert final.atk == pytest.approx((776.16 + 208) * (1 + 1.3824) + 464.195)
        # 速度 = 106 + 副词条 8.6（无速度主词条）
        assert final.spd == pytest.approx(106 + 8.6)
        # 暴击率 = 0.05 + 躯干暴击主 0.324 + 副词条 0.06156
        assert final.crit_rate == pytest.approx(0.05 + 0.38556)

    def test_compute_panel_without_lightcone(self):
        profile = parse_freesr(_load_freesr())
        stats80 = {
            "attack_base": 359.04, "attack_add": 5.28,
            "defence_base": 179.52, "defence_add": 2.64,
            "hp_base": 394.944, "hp_add": 5.808,
            "speed_base": 106.0, "critical_chance": 0.05,
            "critical_damage": 0.5, "base_aggro": 75.0,
        }
        final = compute_panel(stats80, profile.relics["1504"])
        assert final.atk == pytest.approx(776.16 * (1 + 1.3824) + 464.195)


# ── 初始能量 ───────────────────────────────────────────────


class TestInitialEnergy:
    def _char(self, initial_energy: float = 0.0):
        return build_character_unit(
            unit_id="c1", name="测试", path="Rogue", element="Thunder",
            stats80={
                "attack_base": 359.04, "attack_add": 5.28,
                "defence_base": 179.52, "defence_add": 2.64,
                "hp_base": 394.944, "hp_add": 5.808,
                "speed_base": 106.0, "critical_chance": 0.05,
                "critical_damage": 0.5, "base_aggro": 75.0,
            },
            skills_raw={},
            sp_need=150,
            initial_energy=initial_energy,
        )

    def test_build_passthrough(self):
        assert self._char(75).initial_energy == 75

    def test_setup_applies_initial_energy(self):
        sim = BattleSimulator(
            characters=[self._char(75)],
            enemies=[EnemyState(unit_id="e1", name="怪", max_toughness=100, current_toughness=100, weakness_elements=[])],
        )
        sim.setup()
        assert sim.characters[0].energy == pytest.approx(75.0)

    def test_initial_energy_capped(self):
        sim = BattleSimulator(
            characters=[self._char(999)],
            enemies=[EnemyState(unit_id="e1", name="怪", max_toughness=100, current_toughness=100, weakness_elements=[])],
        )
        sim.setup()
        assert sim.characters[0].energy == pytest.approx(150.0)  # 钳制到 energy_max

    def test_default_zero_regression(self):
        sim = BattleSimulator(
            characters=[self._char(0)],
            enemies=[EnemyState(unit_id="e1", name="怪", max_toughness=100, current_toughness=100, weakness_elements=[])],
        )
        sim.setup()
        assert sim.characters[0].energy == 0.0
