"""星魂（Eidolon）数据解析与通用效果。

nanoka 角色详情的 ranks 字段结构：
    "ranks": {
        "1": {"id": 100101, "name": "...", "desc": "...",
              "param_list": [...], "extra": {}},
        ...
    }

这里只做与 UI/模拟器无关的纯数据解析，并提供全角色通用的
“星魂技能等级加成”识别（E3/E5 常见效果）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .skill import SkillType

# nanoka 富文本标签（core 层不依赖 api.transforms，这里做最小清洗）
_RICH_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class Eidolon:
    """单条星魂的提纯数据。"""

    rank: int
    id: str
    name: str
    desc: str
    param_list: list[float] = field(default_factory=list)

    def clean_desc(self) -> str:
        """去除富文本标签后的描述（不含参数插值）。"""
        return _RICH_TAG_RE.sub("", self.desc)


def parse_eidolons(raw: dict | None) -> dict[int, Eidolon]:
    """解析 nanoka ranks 原始 dict → {1..6: Eidolon}。"""
    result: dict[int, Eidolon] = {}
    if not isinstance(raw, dict):
        return result
    for key, item in raw.items():
        if not isinstance(item, dict):
            continue
        try:
            rank = int(key)
        except (TypeError, ValueError):
            continue
        if not 1 <= rank <= 6:
            continue
        params: list[float] = []
        for value in item.get("param_list") or []:
            try:
                params.append(float(value))
            except (TypeError, ValueError):
                continue
        result[rank] = Eidolon(
            rank=rank,
            id=str(item.get("id", "")),
            name=str(item.get("name", "")),
            desc=str(item.get("desc", "")),
            param_list=params,
        )
    return result


# 技能类型关键字 → 技能类型。
# 常见星魂文案：终结技等级+2 / 战技等级+2 / 天赋等级+2 / 普攻等级+1
_SKILL_LEVEL_PATTERNS: tuple[tuple[str, SkillType], ...] = (
    ("终结技等级", SkillType.ULTRA),
    ("战技等级", SkillType.SKILL),
    ("天赋等级", SkillType.TALENT),
    ("普攻等级", SkillType.NORMAL),
)
_SKILL_LEVEL_BONUS_RE = re.compile(r"(终结技|战技|天赋|普攻)等级\+(\d+)")


def rank_skill_level_bonuses(raw: dict | None, rank: int) -> dict[SkillType, int]:
    """统计已激活星魂中的技能等级加成。

    例：3 魂“终结技等级+2，普攻等级+1” → {ULTRA: 2, NORMAL: 1}
    未识别或 rank 为 0 时返回空 dict。
    """
    result: dict[SkillType, int] = {}
    if rank <= 0:
        return result

    eidolons = parse_eidolons(raw)
    for level, eidolon in eidolons.items():
        if level > rank:
            continue
        text = eidolon.clean_desc()
        for match in _SKILL_LEVEL_BONUS_RE.finditer(text):
            keyword = match.group(1)
            bonus = int(match.group(2))
            for pattern, skill_type in _SKILL_LEVEL_PATTERNS:
                if pattern.startswith(keyword):
                    result[skill_type] = result.get(skill_type, 0) + bonus
                    break
    return result


def has_rank(raw: dict | None, rank: int) -> bool:
    """判断原始 ranks 中是否存在指定星魂条目。"""
    return isinstance(raw, dict) and str(rank) in raw


def get_rank_param(
    raw: dict | None,
    rank: int,
    param_index: int,
    default: float,
) -> float:
    """读取指定星魂的第 param_index 个参数（#1 → 0）。"""
    eidolon = parse_eidolons(raw).get(rank)
    if eidolon is None or not (0 <= param_index < len(eidolon.param_list)):
        return default
    return eidolon.param_list[param_index]
