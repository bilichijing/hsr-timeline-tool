"""skill 模块单元测试：新版 nanoka 技能结构解析。"""

import pytest

from src.core.damage import DamageType
from src.core.skill import (
    SkillType,
    clamp_skill_level,
    parse_all_skills,
    parse_level_params,
    parse_skill,
    parse_skill_level_params,
)


# ── 新版结构样例（以不死途 1504 真实数据为蓝本）──────────────


def _make_raw_new(
    skill_id: int,
    type_field: str,
    type_name: str,
    *,
    levels: list[list[float]],
    stance: int = 0,
    sp_base: int = 0,
    bp_need: int = 0,
    bp_add: int = 0,
) -> dict:
    """构造新版技能原始 dict。"""
    return {
        "id": skill_id,
        "name": "测试技能",
        "desc": "描述",
        "type": type_field,
        "type_name": type_name,
        "tag": "SingleAttack",
        "sp_base": sp_base,
        "bp_need": bp_need,
        "bp_add": bp_add,
        "show_stance_list": [stance, 0, 0],
        "level": {str(i + 1): {"param_list": row} for i, row in enumerate(levels)},
    }


# ── 新版 type 字段映射 ──────────────────────────────────────


class TestTypeFieldMapping:
    def test_normal_type_maps_to_normal(self):
        skill = parse_skill(_make_raw_new(1, "Normal", "普攻", levels=[[0.5]]))
        assert skill.skill_type == SkillType.NORMAL

    def test_bpskill_type_maps_to_skill(self):
        skill = parse_skill(_make_raw_new(2, "BPSkill", "战技", levels=[[1.0]]))
        assert skill.skill_type == SkillType.SKILL

    def test_ultra_type_maps_to_ultra(self):
        skill = parse_skill(_make_raw_new(3, "Ultra", "终结技", levels=[[2.0]]))
        assert skill.skill_type == SkillType.ULTRA

    def test_maze_types_map_to_technique(self):
        for type_field, type_name in [("MazeNormal", "普攻"), ("Maze", "秘技")]:
            skill = parse_skill(_make_raw_new(4, type_field, type_name, levels=[]))
            assert skill.skill_type == SkillType.TECHNIQUE, type_field

    def test_talent_heuristic_when_type_none(self):
        """新版天赋 type=None，靠 type_name 含'天赋'识别。"""
        raw = {
            "id": 5,
            "name": "天赋",
            "type": None,
            "type_name": "天赋",
            "tag": "SingleAttack",
            "level": {"1": {"param_list": [1.0]}},
        }
        skill = parse_skill(raw)
        assert skill.skill_type == SkillType.TALENT

    def test_unknown_type_falls_back_to_normal(self):
        skill = parse_skill(_make_raw_new(6, "UnknownType", "未知", levels=[]))
        assert skill.skill_type == SkillType.NORMAL


# ── level 参数提取 ──────────────────────────────────────────


class TestLevelParams:
    def test_extract_specific_level(self):
        raw = _make_raw_new(1, "Normal", "普攻", levels=[[0.5], [0.6], [0.7]])
        assert parse_level_params(raw, 1) == [0.5]
        assert parse_level_params(raw, 3) == [0.7]

    def test_level_clamped_to_max_available(self):
        """战技 15 级表，请求 10 级取第 10 行；请求 99 级钳制到最后一行。"""
        levels = [[float(i)] for i in range(1, 16)]
        raw = _make_raw_new(2, "BPSkill", "战技", levels=levels)
        assert parse_level_params(raw, 10) == [10.0]
        assert parse_level_params(raw, 99) == [15.0]

    def test_no_level_data_returns_empty(self):
        assert parse_level_params({"id": 1, "name": "x"}, 1) == []

    def test_old_param_list_fallback(self):
        raw = {"id": 1, "name": "x", "ParamList": [[0.5], [0.6]]}
        assert parse_level_params(raw, 2) == [0.6]

    def test_legacy_parse_skill_level_params(self):
        assert parse_skill_level_params([[0.5], [0.6]], 2) == [0.6]
        assert parse_skill_level_params([[0.5], [0.6]], 99) == [0.6]  # 钳制
        assert parse_skill_level_params([], 1) == []


# ── 字段提取 ────────────────────────────────────────────────


class TestFieldExtraction:
    def test_normal_sp_recovery(self):
        """普攻回复 SP：bp_add=1 → sp_cost=-1。"""
        skill = parse_skill(_make_raw_new(1, "Normal", "普攻", levels=[[0.5]], bp_add=1))
        assert skill.sp_cost == -1

    def test_skill_sp_cost(self):
        skill = parse_skill(_make_raw_new(2, "BPSkill", "战技", levels=[[1.0]], bp_need=1))
        assert skill.sp_cost == 1

    def test_energy_recover_from_sp_base(self):
        skill = parse_skill(_make_raw_new(1, "Normal", "普攻", levels=[[0.5]], sp_base=20))
        assert skill.energy_recover == 20

    def test_toughness_from_show_stance_list(self):
        skill = parse_skill(_make_raw_new(1, "Normal", "普攻", levels=[[0.5]], stance=30))
        assert skill.effects[0].toughness_damage == 30

    def test_first_param_is_multiplier(self):
        """首段倍率 = params[0]（nanoka 参数为小数：0.5 = 50%，2.0 = 200%）。"""
        skill = parse_skill(_make_raw_new(1, "Normal", "普攻", levels=[[0.5]]))
        assert len(skill.effects) == 1
        assert skill.effects[0].multiplier == 0.5
        assert skill.effects[0].damage_type == DamageType.NORMAL

        skill2 = parse_skill(_make_raw_new(3, "Ultra", "终结技", levels=[[2.0]]))
        assert skill2.effects[0].multiplier == 2.0

    def test_full_params_preserved(self):
        """params 保存完整 param_list（#N → params[N-1]，供角色模块读取条件倍率）。"""
        raw = _make_raw_new(2, "BPSkill", "战技", levels=[[1.0, 1.0, 0.5, 0.2, 1.0]])
        skill = parse_skill(raw)
        assert skill.params == [1.0, 1.0, 0.5, 0.2, 1.0]

    def test_level_selects_params_row(self):
        raw = _make_raw_new(2, "BPSkill", "战技", levels=[[1.0, 0.5], [2.0, 1.0]])
        skill10 = parse_skill(raw, level=2)
        assert skill10.params == [2.0, 1.0]
        assert skill10.effects[0].multiplier == 2.0


# ── parse_all_skills ────────────────────────────────────────


class TestParseAllSkills:
    def test_ultra_energy_cost_injected(self):
        """角色详情顶层 sp_need=150 注入终结技（技能 dict 内无 energy_cost 字段）。"""
        skills = {
            "150403": _make_raw_new(150403, "Ultra", "终结技", levels=[[2.0]]),
        }
        result = parse_all_skills(skills, ultra_energy_cost=150)
        assert result["150403"].energy_cost == 150

    def test_ultra_energy_cost_not_overridden_when_explicit(self):
        """显式给出 energy_cost 的终结技不被注入。"""
        raw = _make_raw_new(150403, "Ultra", "终结技", levels=[[2.0]])
        raw["energy_cost"] = 90
        result = parse_all_skills({"150403": raw}, ultra_energy_cost=150)
        assert result["150403"].energy_cost == 90

    def test_non_ultra_ignores_injection(self):
        raw = _make_raw_new(150401, "Normal", "普攻", levels=[[0.5]])
        result = parse_all_skills({"150401": raw}, ultra_energy_cost=150)
        assert result["150401"].energy_cost == 0

    def test_default_ultra_cost_without_injection(self):
        raw = _make_raw_new(150403, "Ultra", "终结技", levels=[[2.0]])
        result = parse_all_skills({"150403": raw})
        assert result["150403"].energy_cost == 90


# ── 旧版结构兼容 ────────────────────────────────────────────


class TestOldFormatCompat:
    def test_old_tag_mapping(self):
        """旧版 tag 字段各类型。"""
        for tag, expected in [
            ("Normal", SkillType.NORMAL),
            ("Skill", SkillType.SKILL),
            ("Ultra", SkillType.ULTRA),
            ("Talent", SkillType.TALENT),
            ("Technique", SkillType.TECHNIQUE),
            ("MemoDNSkill", SkillType.MEMO_DNSKILL),
        ]:
            skill = parse_skill({"id": "1", "name": "x", "tag": tag, "ParamList": [[0.5]]})
            assert skill.skill_type == expected, tag

    def test_old_param_list_multiplier(self):
        skill = parse_skill({"id": "1", "name": "x", "tag": "Normal", "ParamList": [[0.5]]})
        assert skill.effects[0].multiplier == 0.5

    def test_old_sp_cost_fields(self):
        """旧版 sp_cost 字段直接取用。"""
        raw = {"id": "1", "name": "x", "tag": "Skill", "sp_cost": 1}
        assert parse_skill(raw).sp_cost == 1

    def test_old_toughness_fields(self):
        raw = {"id": "1", "name": "x", "tag": "Normal", "toughness_damage": 30}
        assert parse_skill(raw).effects[0].toughness_damage == 30

    def test_skill_type_enum_includes_follow_up(self):
        """追加攻击是技能类型维度（与伤害类型独立）。"""
        assert SkillType.FOLLOW_UP.value == "FollowUp"


# ── 技能等级分级 ────────────────────────────────────────────


class TestSkillLevelGrading:
    def _multi_skills(self) -> dict:
        return {
            "n": _make_raw_new(1, "Normal", "普攻", levels=[[0.5 + 0.1 * i] for i in range(10)]),
            "s": _make_raw_new(2, "BPSkill", "战技", levels=[[1 + i / 9] for i in range(10)]),
            "u": _make_raw_new(3, "Ultra", "终结技", levels=[[2 + 2 * i / 9] for i in range(10)]),
        }

    def test_per_type_levels(self):
        result = parse_all_skills(
            self._multi_skills(),
            skill_levels={SkillType.NORMAL: 10, SkillType.SKILL: 2},
        )
        assert result["n"].params[0] == pytest.approx(1.4)  # L10
        assert result["s"].params[0] == pytest.approx(1 + 1 / 9)  # L2
        assert result["u"].params[0] == pytest.approx(2.0)  # 未指定回退 level=1

    def test_unspecified_falls_back_to_level(self):
        result = parse_all_skills(self._multi_skills(), level=5, skill_levels={SkillType.NORMAL: 10})
        assert result["u"].params[0] == pytest.approx(2 + 2 * 4 / 9)  # L5

    def test_normal_level_clamped_to_10(self):
        result = parse_all_skills(self._multi_skills(), skill_levels={SkillType.NORMAL: 99})
        assert result["n"].params[0] == pytest.approx(1.4)

    def test_skill_levels_none_uses_default(self):
        result = parse_all_skills(self._multi_skills())
        assert result["n"].params[0] == pytest.approx(0.5)  # L1

    def test_memo_dnskill_type_field(self):
        """新版 type="MemoDNSkill" → MEMO_DNSKILL。"""
        raw = _make_raw_new(7, "MemoDNSkill", "忆灵技", levels=[[0.5]])
        skill = parse_skill(raw)
        assert skill.skill_type == SkillType.MEMO_DNSKILL
        assert clamp_skill_level(SkillType.MEMO_DNSKILL, 99) == 15
