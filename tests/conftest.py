"""pytest 共享 fixtures。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    path = FIXTURES_DIR / f"{name}.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture
def character_list_raw() -> dict:
    """角色列表原始 JSON。"""
    return _load_fixture("character_list")


@pytest.fixture
def character_detail_raw() -> dict:
    """角色详情原始 JSON（三月七 1001）。"""
    return _load_fixture("character_1001")


@pytest.fixture
def lightcone_list_raw() -> dict:
    """光锥列表原始 JSON。"""
    return _load_fixture("lightcone_list")


@pytest.fixture
def lightcone_detail_raw() -> dict:
    """光锥详情原始 JSON（锋镝 20000）。"""
    return _load_fixture("lightcone_20000")


@pytest.fixture
def relicset_list_raw() -> dict:
    """遗器套装列表原始 JSON。"""
    return _load_fixture("relicset_list")


@pytest.fixture
def relicset_detail_raw() -> dict:
    """遗器套装详情原始 JSON（云无留迹的过客 101）。"""
    return _load_fixture("relicset_101")


@pytest.fixture
def monster_list_raw() -> dict:
    """怪物列表原始 JSON。"""
    return _load_fixture("monster_list")
