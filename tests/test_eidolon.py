"""星魂数据解析与通用技能等级加成测试。"""

from __future__ import annotations

import pytest

from src.core.eidolon import (
    Eidolon,
    get_rank_param,
    parse_eidolons,
    rank_skill_level_bonuses,
)
from src.core.skill import SkillType


RAW_RANKS = {
    "1": {
        "id": 101,
        "name": "一魂",
        "desc": "终结技等级+2，最多不超过<unbreak>15</unbreak>级。",
        "param_list": [],
    },
    "3": {
        "id": 103,
        "name": "三魂",
        "desc": "战技等级+2，最多不超过<unbreak>15</unbreak>级；普攻等级+1，最多不超过<unbreak>10</unbreak>级。",
        "param_list": [],
    },
    "4": {
        "id": 104,
        "name": "四魂",
        "desc": "伤害提高<unbreak>#1[i]%</unbreak>。",
        "param_list": [0.5],
    },
}


class TestParseEidolons:
    def test_parse(self):
        eidolons = parse_eidolons(RAW_RANKS)
        assert set(eidolons) == {1, 3, 4}
        assert isinstance(eidolons[1], Eidolon)
        assert eidolons[4].name == "四魂"

    def test_clean_desc_removes_tags(self):
        eidolon = parse_eidolons(RAW_RANKS)[1]
        assert "<unbreak>" not in eidolon.clean_desc()
        assert "终结技等级+2" in eidolon.clean_desc()

    def test_empty_or_invalid(self):
        assert parse_eidolons(None) == {}
        assert parse_eidolons({"x": {"name": "bad"}}) == {}
        assert parse_eidolons({"2": None}) == {}


class TestRankSkillLevelBonuses:
    def test_rank0_no_bonus(self):
        assert rank_skill_level_bonuses(RAW_RANKS, 0) == {}

    def test_e1_ultra_bonus(self):
        assert rank_skill_level_bonuses(RAW_RANKS, 1) == {SkillType.ULTRA: 2}

    def test_multiple_bonus_accumulates(self):
        bonuses = rank_skill_level_bonuses(RAW_RANKS, 3)
        assert bonuses == {
            SkillType.ULTRA: 2,
            SkillType.SKILL: 2,
            SkillType.NORMAL: 1,
        }


class TestGetRankParam:
    def test_param(self):
        assert get_rank_param(RAW_RANKS, 4, 0, 0.0) == pytest.approx(0.5)

    def test_missing_rank_or_index(self):
        assert get_rank_param(RAW_RANKS, 2, 0, 0.0) == pytest.approx(0.0)
        assert get_rank_param(RAW_RANKS, 4, 3, 9.0) == pytest.approx(9.0)
