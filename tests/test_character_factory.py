"""character_factory 模块单元测试：nanoka 纯数据 → CharacterUnit。"""

import pytest

from src.core.character_factory import (
    STATS_KEY_80,
    build_character_unit,
    convert_stats80,
    extract_trace_bonuses,
)
from src.core.skill import SkillType

# 不死途 1504 真实 80 级数据（nanoka stats["6"]）
ASHVEIL_STATS80 = {
    "attack_base": 359.04, "attack_add": 5.28,
    "defence_base": 179.52, "defence_add": 2.64,
    "hp_base": 394.944, "hp_add": 5.808,
    "speed_base": 106.0, "critical_chance": 0.05,
    "critical_damage": 0.5, "base_aggro": 75.0,
}


def _skills_raw() -> dict:
    """最小技能集（各类型一个）。"""
    return {
        "150401": {
            "id": 150401, "name": "普攻", "type": "Normal", "type_name": "普攻",
            "sp_base": 20, "bp_need": -1, "bp_add": 1,
            "show_stance_list": [30, 0, 0],
            "level": {str(i + 1): {"param_list": [0.5 + 0.1 * i]} for i in range(10)},
        },
        "150402": {
            "id": 150402, "name": "战技", "type": "BPSkill", "type_name": "战技",
            "sp_base": 30, "bp_need": 1,
            "level": {str(i + 1): {"param_list": [1 + i / 9, 1, 0.5, 0.2, 1]} for i in range(10)},
        },
        "150403": {
            "id": 150403, "name": "终结技", "type": "Ultra", "type_name": "终结技",
            "sp_base": 5, "bp_need": -1,
            "level": {str(i + 1): {"param_list": [2 + 2 * i / 9, 3, 4, 1]} for i in range(10)},
        },
        "150404": {
            "id": 150404, "name": "天赋", "type": None, "type_name": "天赋",
            "sp_base": 5, "bp_need": -1,
            "level": {str(i + 1): {"param_list": [2, 3, 1, 1, 2, 12, 8]} for i in range(10)},
        },
    }


# ── 80 级面板转换 ──────────────────────────────────────────


class TestConvertStats80:
    def test_ashveil_real_stats(self):
        """不死途实测：ATK = 359.04 + 5.28×79 = 776.16（成长 ×(等级-1)）。"""
        base = convert_stats80(ASHVEIL_STATS80)
        assert base.atk_base == pytest.approx(359.04 + 5.28 * 79)
        assert base.hp_base == pytest.approx(394.944 + 5.808 * 79)
        assert base.def_base == pytest.approx(179.52 + 2.64 * 79)
        assert base.spd_base == 106.0  # 速度不成长
        assert base.crit_rate == 0.05
        assert base.crit_dmg == 0.5
        assert base.aggro == 75.0

    def test_missing_fields_default_zero(self):
        base = convert_stats80({})
        assert base.atk_base == 0.0
        assert base.hp_base == 0.0
        assert base.crit_rate == 0.05  # 默认值保留
        assert base.crit_dmg == 0.5

    def test_stats_key_80_constant(self):
        assert STATS_KEY_80 == "6"


# ── 角色构造 ────────────────────────────────────────────────


class TestBuildCharacterUnit:
    def _build(self, **kwargs):
        defaults = dict(
            unit_id="char1",
            name="不死途",
            path="Rogue",
            element="Thunder",
            stats80=ASHVEIL_STATS80,
            skills_raw=_skills_raw(),
        )
        defaults.update(kwargs)
        return build_character_unit(**defaults)

    def test_basic_assembly(self):
        char = self._build(sp_need=150, char_id="1504", dmg_bonus=0.3)
        assert char.name == "不死途"
        assert char.char_id == "1504"
        assert char.level == 80
        # 技能解析（含天赋启发式）
        assert len(char.skills) == 4
        types = {s.skill_type for s in char.skills.values()}
        assert types == {SkillType.NORMAL, SkillType.SKILL, SkillType.ULTRA, SkillType.TALENT}
        # 终结技耗能注入
        ultra = next(s for s in char.skills.values() if s.skill_type == SkillType.ULTRA)
        assert ultra.energy_cost == 150
        # 能量上限 = sp_need
        assert char.base_stats.energy_max == 150
        # 属性增伤 → bonus_stats
        assert char.bonus_stats.dmg_bonus == 0.3

    def test_skill_levels_per_type(self):
        """按类型分级：普攻 10 级、战技 2 级。"""
        char = self._build(
            skill_levels={SkillType.NORMAL: 10, SkillType.SKILL: 2},
        )
        normal = next(s for s in char.skills.values() if s.skill_type == SkillType.NORMAL)
        skill = next(s for s in char.skills.values() if s.skill_type == SkillType.SKILL)
        assert normal.params[0] == pytest.approx(1.4)  # L10
        assert skill.params[0] == pytest.approx(1.0 + 1 / 9)  # L2

    def test_unspecified_level_falls_back(self):
        """未指定的类型回退 level 参数。"""
        char = self._build(level=5, skill_levels={SkillType.NORMAL: 10})
        ultra = next(s for s in char.skills.values() if s.skill_type == SkillType.ULTRA)
        assert ultra.params[0] == pytest.approx(2 + 2 * 4 / 9)  # L5

    def test_normal_level_clamped_to_10(self):
        char = self._build(skill_levels={SkillType.NORMAL: 99})
        normal = next(s for s in char.skills.values() if s.skill_type == SkillType.NORMAL)
        assert normal.params[0] == pytest.approx(1.4)  # 钳制到 L10

    def test_elation_level_stored(self):
        char = self._build(path="Elation", elation_skill_level=3)
        assert char.elation_skill_level == 3
        assert char.is_elation is True  # __post_init__ 自动判定

    def test_energy_max_fallback(self):
        """sp_need=0 → 兜底 100。"""
        char = self._build(sp_need=0)
        assert char.base_stats.energy_max == 100.0


# ── 行迹属性加成 ───────────────────────────────────────────


def _ashveil_skill_trees_raw() -> dict:
    """不死途真实行迹属性强化点（point_type=1 的 status_add_list 汇总）。"""
    def point(point_id: int, entries: list[dict]) -> dict:
        return {str(point_id): {"point_id": point_id, "point_type": 1, "status_add_list": entries}}

    return {
        "point09": point(1504201, [{"property_type": "CriticalDamageBase", "value": 0.053, "name": "暴击伤害"}]),
        "point10": point(1504202, [{"property_type": "ThunderAddedRatio", "value": 0.032, "name": "雷属性伤害提高"}]),
        "point11": point(1504203, [{"property_type": "CriticalDamageBase", "value": 0.053, "name": "暴击伤害"}]),
        "point12": point(1504204, [{"property_type": "AttackAddedRatio", "value": 0.04, "name": "攻击力"}]),
        "point13": point(1504205, [{"property_type": "CriticalDamageBase", "value": 0.08, "name": "暴击伤害"}]),
        "point14": point(1504206, [{"property_type": "ThunderAddedRatio", "value": 0.048, "name": "雷属性伤害提高"}]),
        "point15": point(1504207, [{"property_type": "CriticalDamageBase", "value": 0.08, "name": "暴击伤害"}]),
        "point16": point(1504208, [{"property_type": "AttackAddedRatio", "value": 0.06, "name": "攻击力"}]),
        "point17": point(1504209, [{"property_type": "ThunderAddedRatio", "value": 0.064, "name": "雷属性伤害提高"}]),
        "point18": point(1504210, [{"property_type": "CriticalDamageBase", "value": 0.107, "name": "暴击伤害"}]),
    }


class TestTraceBonuses:
    def test_ashveil_trace_aggregation(self):
        """不死途满行迹：攻击 10%、暴击伤害 37.3%、雷伤 14.4%。"""
        bonus = extract_trace_bonuses(_ashveil_skill_trees_raw())
        assert bonus.atk_pct == pytest.approx(0.10)
        assert bonus.crit_dmg == pytest.approx(0.373)
        assert bonus.dmg_bonus == pytest.approx(0.144)

    def test_none_and_empty(self):
        assert extract_trace_bonuses(None).atk_pct == 0.0
        assert extract_trace_bonuses({}).atk_pct == 0.0

    def test_build_character_unit_includes_trace(self):
        char = build_character_unit(
            unit_id="c1", name="不死途", path="Rogue", element="Thunder",
            stats80=ASHVEIL_STATS80, skills_raw=_skills_raw(),
            skill_trees_raw=_ashveil_skill_trees_raw(),
        )
        assert char.bonus_stats.atk_pct == pytest.approx(0.10)
        assert char.bonus_stats.crit_dmg == pytest.approx(0.373)
        assert char.bonus_stats.dmg_bonus == pytest.approx(0.144)
