"""枚举完整性自检。

扫描 tests/fixtures/ 下的列表 JSON，提取所有 baseType / damageType / rank 字段值，
对比 PATH_MAP / ELEMENT_MAP / RARITY_MAP 是否覆盖完整。

作用：防止新增命途/属性/稀有度时遗漏映射表（如之前漏掉 Elation 命途）。
每次跑 pytest 自动执行，新增 fixture 后立即生效。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.api.consts import ELEMENT_MAP, PATH_MAP, RARITY_MAP

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_list(name: str) -> dict[str, dict]:
    """加载列表 fixture。"""
    return json.loads((FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


def _collect_field_values(data: dict[str, dict], field: str) -> set[str]:
    """从列表数据中收集某个字段的所有唯一值。"""
    return {item[field] for item in data.values() if field in item}


# ── 命途（baseType）完整性 ─────────────────────────────────


class TestPathMapCompleteness:
    """所有角色/光锥的 baseType 必须在 PATH_MAP 中有映射。"""

    def test_character_base_types_all_mapped(self):
        data = _load_list("character_list")
        base_types = _collect_field_values(data, "baseType")
        missing = base_types - set(PATH_MAP.keys())
        assert not missing, f"角色 baseType 未在 PATH_MAP 中映射: {missing}"

    def test_lightcone_base_types_all_mapped(self):
        data = _load_list("lightcone_list")
        base_types = _collect_field_values(data, "baseType")
        missing = base_types - set(PATH_MAP.keys())
        assert not missing, f"光锥 baseType 未在 PATH_MAP 中映射: {missing}"

    def test_path_map_has_no_extra_entries(self):
        """PATH_MAP 中的键不应超出数据中实际出现的值太多（防止残留废弃命途）。

        允许 PATH_MAP 比数据多（向前兼容新命途），但多出的会列出提示。
        """
        char_data = _load_list("character_list")
        lc_data = _load_list("lightcone_list")
        actual = _collect_field_values(char_data, "baseType") | _collect_field_values(lc_data, "baseType")
        extra = set(PATH_MAP.keys()) - actual
        if extra:
            pytest.fail(f"PATH_MAP 中存在数据未使用的命途（可能是废弃项）: {extra}")


# ── 属性（damageType）完整性 ───────────────────────────────


class TestElementMapCompleteness:
    """所有角色的 damageType 必须在 ELEMENT_MAP 中有映射。"""

    def test_character_damage_types_all_mapped(self):
        data = _load_list("character_list")
        damage_types = _collect_field_values(data, "damageType")
        missing = damage_types - set(ELEMENT_MAP.keys())
        assert not missing, f"角色 damageType 未在 ELEMENT_MAP 中映射: {missing}"

    def test_element_map_has_no_extra_entries(self):
        data = _load_list("character_list")
        actual = _collect_field_values(data, "damageType")
        extra = set(ELEMENT_MAP.keys()) - actual
        if extra:
            pytest.fail(f"ELEMENT_MAP 中存在数据未使用的属性（可能是废弃项）: {extra}")


# ── 稀有度（rank）完整性 ───────────────────────────────────


class TestRarityMapCompleteness:
    """角色/光锥的 rank 必须在 RARITY_MAP 中有映射。

    注意：怪物的 rank 是另一套体系（BigBoss/Elite/Minion 等），不在此检查范围。
    """

    def test_character_ranks_all_mapped(self):
        data = _load_list("character_list")
        ranks = _collect_field_values(data, "rank")
        missing = ranks - set(RARITY_MAP.keys())
        assert not missing, f"角色 rank 未在 RARITY_MAP 中映射: {missing}"

    def test_lightcone_ranks_all_mapped(self):
        data = _load_list("lightcone_list")
        ranks = _collect_field_values(data, "rank")
        missing = ranks - set(RARITY_MAP.keys())
        assert not missing, f"光锥 rank 未在 RARITY_MAP 中映射: {missing}"


# ── 数据统计报告（信息性测试，不阻断）──────────────────────


class TestEnumCoverageReport:
    """输出枚举覆盖情况报告（info 级别，始终通过）。"""

    def test_report_all_enums(self):
        char_data = _load_list("character_list")
        lc_data = _load_list("lightcone_list")

        char_paths = _collect_field_values(char_data, "baseType")
        lc_paths = _collect_field_values(lc_data, "baseType")
        char_elements = _collect_field_values(char_data, "damageType")
        char_ranks = _collect_field_values(char_data, "rank")
        lc_ranks = _collect_field_values(lc_data, "rank")

        report = (
            f"\n=== 枚举覆盖报告 ===\n"
            f"命途 (PATH_MAP): {len(PATH_MAP)} 个 → {sorted(PATH_MAP.keys())}\n"
            f"  角色使用: {len(char_paths)} 个\n"
            f"  光锥使用: {len(lc_paths)} 个\n"
            f"属性 (ELEMENT_MAP): {len(ELEMENT_MAP)} 个 → {sorted(ELEMENT_MAP.keys())}\n"
            f"  角色使用: {len(char_elements)} 个\n"
            f"稀有度 (RARITY_MAP): {len(RARITY_MAP)} 个 → {sorted(RARITY_MAP.keys())}\n"
            f"  角色使用: {len(char_ranks)} 种\n"
            f"  光锥使用: {len(lc_ranks)} 种"
        )
        # 用 pytest.skip 输出报告文本，不会阻断测试
        print(report)
