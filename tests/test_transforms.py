"""transforms.py 提纯函数测试。

用 tests/fixtures/ 下的真实 nanoka JSON 数据校验。
"""

from __future__ import annotations

from src.api.transforms import (
    clean_text,
    interpolate_params,
    parse_rarity,
    strip_rich_text,
    transform_character_detail,
    transform_character_list,
    transform_lightcone_detail,
    transform_lightcone_list,
    transform_monster_list,
    transform_relicset_detail,
    transform_relicset_list,
)


# ── 文本清洗 ───────────────────────────────────────────────


class TestTextCleaning:
    def test_strip_rich_text_removes_color_tags(self):
        assert strip_rich_text("<color=#f29e38ff>50%</color>") == "50%"

    def test_strip_rich_text_removes_unbreak_tags(self):
        assert strip_rich_text("<unbreak>67</unbreak>") == "67"

    def test_strip_rich_text_removes_multiple_tags(self):
        text = "<i>引言</i>正文<u>下划线</u>"
        assert strip_rich_text(text) == "引言正文下划线"

    def test_strip_rich_text_keeps_plain_text(self):
        assert strip_rich_text("普通文本") == "普通文本"

    def test_interpolate_params_replaces_placeholders(self):
        assert interpolate_params("攻击力提高#1[i]%", [0.5]) == "攻击力提高50%"

    def test_interpolate_params_replaces_multiple(self):
        assert interpolate_params("#1[i]%和#2[i]%", [0.12, 0.24]) == "12%和24%"

    def test_interpolate_params_handles_decimal(self):
        assert interpolate_params("#1[i]%", [0.125]) == "12.5%"

    def test_interpolate_params_no_params_keeps_text(self):
        assert interpolate_params("无占位符", []) == "无占位符"

    def test_clean_text_combined(self):
        text = "<color=#fff>提高#1[i]%</color>"
        assert clean_text(text, [0.3]) == "提高30%"


# ── 枚举映射 ───────────────────────────────────────────────


class TestParseRarity:
    def test_character_4_star(self):
        assert parse_rarity("CombatPowerAvatarRarityType4") == 4

    def test_character_5_star(self):
        assert parse_rarity("CombatPowerAvatarRarityType5") == 5

    def test_lightcone_3_star(self):
        assert parse_rarity("CombatPowerLightconeRarity3") == 3

    def test_unknown_rarity_returns_zero(self):
        assert parse_rarity("Unknown") == 0


# ── 角色列表提纯 ───────────────────────────────────────────


class TestCharacterListTransform:
    def test_returns_list(self, character_list_raw):
        result = transform_character_list(character_list_raw)
        assert isinstance(result, list)
        assert len(result) > 0

    def test_first_character_has_correct_fields(self, character_list_raw):
        result = transform_character_list(character_list_raw)
        march7th = next(c for c in result if c.id == "1001")
        assert march7th.name_zh == "三月七"
        assert march7th.name_en == "March 7th"
        assert march7th.rarity == 4
        assert march7th.path == "Knight"
        assert march7th.element == "Ice"
        assert "avatarroundicon/1001.webp" in march7th.icon_url

    def test_all_have_icon_url(self, character_list_raw):
        result = transform_character_list(character_list_raw)
        for char in result:
            assert char.icon_url.startswith("https://")
            assert char.icon_url.endswith(".webp")


# ── 角色详情提纯 ───────────────────────────────────────────


class TestCharacterDetailTransform:
    def test_basic_fields(self, character_detail_raw):
        info = transform_character_detail(character_detail_raw, "1001")
        assert info.id == "1001"
        assert info.name == "三月七"
        assert info.rarity == 4
        assert info.path == "Knight"
        assert info.element == "Ice"
        assert info.sp_need == 120

    def test_desc_cleaned(self, character_detail_raw):
        info = transform_character_detail(character_detail_raw, "1001")
        assert "<unbreak>" not in info.desc
        assert "六十七" in info.desc

    def test_stats_parsed(self, character_detail_raw):
        info = transform_character_detail(character_detail_raw, "1001")
        assert "0" in info.stats
        stats = info.stats["0"]
        assert stats.attack_base == 69.6
        assert stats.hp_base == 144
        assert stats.speed_base == 101

    def test_skills_preserved(self, character_detail_raw):
        info = transform_character_detail(character_detail_raw, "1001")
        assert len(info.skills) > 0
        # 技能 ID 100101 = 极寒的弓矢（普攻）
        assert "100101" in info.skills

    def test_ranks_preserved(self, character_detail_raw):
        info = transform_character_detail(character_detail_raw, "1001")
        assert len(info.ranks) == 6  # 6 个星魂


# ── 光锥列表提纯 ───────────────────────────────────────────


class TestLightconeListTransform:
    def test_returns_list(self, lightcone_list_raw):
        result = transform_lightcone_list(lightcone_list_raw)
        assert len(result) > 0

    def test_first_lightcone(self, lightcone_list_raw):
        result = transform_lightcone_list(lightcone_list_raw)
        lc = next(l for l in result if l.id == "20000")
        assert lc.name_zh == "锋镝"
        assert lc.rarity == 3
        assert lc.path == "Rogue"
        assert lc.atk == 318
        assert "itemfigures/20000.webp" in lc.icon_url


# ── 光锥详情提纯 ───────────────────────────────────────────


class TestLightconeDetailTransform:
    def test_basic_fields(self, lightcone_detail_raw):
        info = transform_lightcone_detail(lightcone_detail_raw, "20000")
        assert info.name == "锋镝"
        assert info.rarity == 3
        assert info.path == "Rogue"

    def test_refinement_parsed(self, lightcone_detail_raw):
        info = transform_lightcone_detail(lightcone_detail_raw, "20000")
        assert info.refinement is not None
        assert info.refinement.name == "危机"
        assert "1" in info.refinement.levels
        assert info.refinement.levels["1"] == [0.12, 3]


# ── 遗器套装列表提纯 ───────────────────────────────────────


class TestRelicSetListTransform:
    def test_returns_list(self, relicset_list_raw):
        result = transform_relicset_list(relicset_list_raw)
        assert len(result) > 0

    def test_first_set_bonus(self, relicset_list_raw):
        result = transform_relicset_list(relicset_list_raw)
        rs = next(r for r in result if r.id == "101")
        assert rs.name_zh == "云无留迹的过客"
        assert rs.bonus_2pc is not None
        assert "治疗量" in rs.bonus_2pc.desc
        assert "10%" in rs.bonus_2pc.desc  # 0.1 → 10%
        assert rs.bonus_4pc is not None
        assert "战技点" in rs.bonus_4pc.desc

    def test_icon_url(self, relicset_list_raw):
        result = transform_relicset_list(relicset_list_raw)
        rs = next(r for r in result if r.id == "101")
        assert "itemfigures/71000.webp" in rs.icon_url


# ── 遗器套装详情提纯 ───────────────────────────────────────


class TestRelicSetDetailTransform:
    def test_basic_fields(self, relicset_detail_raw):
        info = transform_relicset_detail(relicset_detail_raw, "101")
        assert info.name == "云无留迹的过客"
        assert "itemfigures/71000.webp" in info.icon_url

    def test_parts_parsed(self, relicset_detail_raw):
        info = transform_relicset_detail(relicset_detail_raw, "101")
        assert len(info.parts) == 4  # 4 件套
        part = info.parts["31011"]
        assert part.name == "过客的逢春木簪"

    def test_bonus_parsed(self, relicset_detail_raw):
        info = transform_relicset_detail(relicset_detail_raw, "101")
        assert info.bonus_2pc is not None
        assert "治疗量" in info.bonus_2pc.desc


# ── 怪物列表提纯 ───────────────────────────────────────────


class TestMonsterListTransform:
    def test_returns_list(self, monster_list_raw):
        result = transform_monster_list(monster_list_raw)
        assert len(result) > 0

    def test_first_monster(self, monster_list_raw):
        result = transform_monster_list(monster_list_raw)
        mon = next(m for m in result if m.id == "1002011")
        assert mon.name_zh == "冰锋"
        assert "Fire" in mon.weaknesses
        assert "Thunder" in mon.weaknesses
        assert "monster_1002011.webp" in mon.icon_url.lower()
