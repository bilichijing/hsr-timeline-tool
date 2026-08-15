"""数据提纯：nanoka 原始 JSON → 业务模型。

纯函数，无 IO，可独立测试。
对应 wuwa-afyg-tool 的 src/lib/api/utils.ts。
"""

from __future__ import annotations

import re

from src.api.consts import (
    ELEMENT_MAP,
    PATH_MAP,
    RARITY_MAP,
    character_icon_url,
    lightcone_icon_url,
    monster_icon_url,
    relicset_icon_url,
)
from src.api.models import (
    Character,
    CharacterInfo,
    Lightcone,
    LightconeInfo,
    LightconeRefinement,
    Monster,
    RelicSet,
    RelicSetBonus,
    RelicSetInfo,
    RelicSetPart,
    StatsRow,
)


# ── 文本清洗 ───────────────────────────────────────────────

# nanoka 富文本标签：<color=#xxx> <unbreak> <i> <u> <te href=...> <highlight> 等
_RICH_TAG_RE = re.compile(r"<[^>]+>")


def strip_rich_text(text: str) -> str:
    """去除 nanoka 富文本标签。

    示例：'<color=#f29e38ff>50%</color>' → '50%'
    """
    return _RICH_TAG_RE.sub("", text)


# nanoka 参数占位符：#1[i]（整数）、#2[f1]（浮点，1 位小数）
# 注意：不匹配后面的 %，让 % 保留在原文（如 #1[i]% 的 % 是描述自带）
_PARAM_PLACEHOLDER_RE = re.compile(r"#(\d+)\[([if])(\d*)\]")


def interpolate_params(text: str, params: list[float]) -> str:
    """替换 #1[i] / #2[f1] 等占位符为实际参数值。

    示例：
        interpolate_params('攻击力提高#1[i]%', [0.5]) → '攻击力提高50%'
        interpolate_params('每有#1[i]层【婪酣】', [1]) → '每有1层【婪酣】'
        interpolate_params('恢复#2[f1]点能量', [30, 1.5]) → '恢复1.5点能量'

    格式说明：
    - [i] 整数：去尾零（1.0 → 1、1.5 → 1.5）
    - [fN] 浮点：保留 N 位小数（[f1]：1.5 → 1.5、2.0 → 2.0）
    - 占位符后紧跟 % 的按百分比显示（0.5 → 50）
    """
    def replacer(m: re.Match) -> str:
        idx = int(m.group(1)) - 1  # #1 对应 params[0]
        fmt = m.group(2)           # "i" 或 "f"
        digits = m.group(3)        # "" 或 "1"/"2"
        if 0 <= idx < len(params):
            val = params[idx]
            # 占位符后是否紧跟 %（决定百分比/原值显示）
            after = text[m.end():m.end() + 1]
            if after == "%":
                val = val * 100
            if fmt == "f" and digits:
                return f"{val:.{int(digits)}f}"
            # 整数格式 [i]：去尾零（0.5 → 50 已在上面 ×100 处理）
            if val == int(val):
                return str(int(val))
            return f"{val:g}"
        return m.group(0)

    return _PARAM_PLACEHOLDER_RE.sub(replacer, text)


def clean_text(text: str | None, params: list[float] | None = None) -> str:
    """完整文本清洗：去标签 + 替换占位符。None 输入返回空字符串。"""
    if not text:
        return ""
    result = strip_rich_text(text)
    if params:
        result = interpolate_params(result, params)
    return result


# ── 枚举映射辅助 ───────────────────────────────────────────


def parse_rarity(rank_str: str) -> int:
    """'CombatPowerAvatarRarityType4' → 4。"""
    return RARITY_MAP.get(rank_str, 0)


# ── 列表提纯 ───────────────────────────────────────────────


def transform_character_list(raw: dict[str, dict]) -> list[Character]:
    """角色列表提纯。

    输入：{id: {en, zh, rank, baseType, damageType, icon, ...}}
    输出：[Character(id, name_zh, name_en, rarity, path, element, icon_url), ...]
    """
    result = []
    for char_id, item in raw.items():
        rarity = parse_rarity(item.get("rank", ""))
        if rarity == 0:
            continue  # 跳过无效稀有度

        name_zh = item.get("zh", item.get("en", char_id))
        name_en = item.get("en", "")
        path = item.get("baseType", "")

        # 主角名字为 {NICKNAME}，替换为"{命途}主"格式（如"欢愉主"）
        if "{NICKNAME}" in name_zh:
            path_zh = PATH_MAP.get(path, path)
            name_zh = f"{path_zh}主"
        if "{NICKNAME}" in name_en:
            name_en = f"{path}Main"

        result.append(
            Character(
                id=char_id,
                name_zh=name_zh,
                name_en=name_en,
                rarity=rarity,
                path=path,
                element=item.get("damageType", ""),
                icon_url=character_icon_url(char_id),
            )
        )
    return result


def transform_lightcone_list(raw: dict[str, dict]) -> list[Lightcone]:
    """光锥列表提纯。"""
    result = []
    for lc_id, item in raw.items():
        rarity = parse_rarity(item.get("rank", ""))
        if rarity == 0:
            continue

        result.append(
            Lightcone(
                id=lc_id,
                name_zh=item.get("zh", item.get("en", lc_id)),
                name_en=item.get("en", ""),
                rarity=rarity,
                path=item.get("baseType", ""),
                icon_url=lightcone_icon_url(lc_id),
                atk=item.get("atk", 0),
            )
        )
    return result


def transform_relicset_list(raw: dict[str, dict]) -> list[RelicSet]:
    """遗器套装列表提纯。

    输入 set 字段示例：
        {"2": {"zh": "治疗量提高#1[i]%。", "ParamList": [0.1]}, "4": {...}}
    """
    result = []
    for set_id, item in raw.items():
        set_data = item.get("set", {})
        bonus_2pc = _parse_set_bonus(set_data.get("2"))
        bonus_4pc = _parse_set_bonus(set_data.get("4"))

        result.append(
            RelicSet(
                id=set_id,
                name_zh=item.get("zh", item.get("en", set_id)),
                name_en=item.get("en", ""),
                icon_url=relicset_icon_url(item.get("icon", "")),
                bonus_2pc=bonus_2pc,
                bonus_4pc=bonus_4pc,
            )
        )
    return result


def _parse_set_bonus(raw: dict | None) -> RelicSetBonus | None:
    """解析套装效果。

    适配两种字段名：
    - 列表 set 字段：{"zh": "...", "ParamList": [...]}（大写 P）
    - 详情 require_num 字段：{"desc": "...", "param_list": [...]}（小写 p）
    """
    if not raw:
        return None
    # desc 优先取 zh → desc → en
    desc = raw.get("zh", raw.get("desc", raw.get("en", "")))
    # param_list 优先取 ParamList → param_list
    params = raw.get("ParamList", raw.get("param_list", []))
    return RelicSetBonus(
        desc=clean_text(desc, params),
        param_list=params,
    )


def transform_monster_list(raw: dict[str, dict]) -> list[Monster]:
    """怪物列表提纯。"""
    result = []
    for mon_id, item in raw.items():
        weaknesses = [w for w in item.get("weak", []) if w]
        result.append(
            Monster(
                id=mon_id,
                name_zh=item.get("zh", item.get("en", mon_id)),
                name_en=item.get("en", ""),
                icon_url=monster_icon_url(item.get("icon", "")),
                weaknesses=weaknesses,
                rank=item.get("rank", ""),
            )
        )
    return result


# ── 详情提纯 ───────────────────────────────────────────────


def transform_character_detail(raw: dict, char_id: str) -> CharacterInfo:
    """角色详情提纯。

    skills / skill_trees / ranks 保留原始 dict，倍率解析留到 core/skill.py。
    """
    stats_raw = raw.get("stats", {})
    stats = {
        level: StatsRow(**row) for level, row in stats_raw.items() if isinstance(row, dict)
    }

    return CharacterInfo(
        id=char_id,
        name=raw.get("name", ""),
        desc=clean_text(raw.get("desc", "")),
        rarity=parse_rarity(raw.get("rarity", "")),
        path=raw.get("base_type", ""),
        element=raw.get("damage_type", ""),
        sp_need=raw.get("sp_need", 0),
        icon_url=character_icon_url(char_id),
        stats=stats,
        skills=raw.get("skills", {}),
        skill_trees=raw.get("skill_trees", {}),
        ranks=raw.get("ranks", {}),
        memosprite=raw.get("memosprite", {}),
    )


def transform_lightcone_detail(raw: dict, lc_id: str) -> LightconeInfo:
    """光锥详情提纯。"""
    refinement_raw = raw.get("refinements", {})
    refinement = None
    if refinement_raw:
        levels_raw = refinement_raw.get("level", {})
        levels = {
            lv: row.get("param_list", []) for lv, row in levels_raw.items()
        }
        refinement = LightconeRefinement(
            name=refinement_raw.get("name", ""),
            desc=clean_text(refinement_raw.get("desc", "")),
            levels=levels,
        )

    return LightconeInfo(
        id=lc_id,
        name=raw.get("name", ""),
        desc=clean_text(raw.get("desc", "")),
        rarity=parse_rarity(raw.get("rarity", "")),
        path=raw.get("base_type", ""),
        icon_url=lightcone_icon_url(lc_id),
        refinement=refinement,
        stats=raw.get("stats", {}),
    )


def pick_lightcone_stats80(info: LightconeInfo) -> dict:
    """光锥详情 → 80 级 stats 行（promotion==6 优先，缺省取最大 promotion）。

    返回 {"base_hp", "base_hp_add", "base_attack", "base_attack_add",
          "base_defence", "base_defence_add"}。
    """
    rows = info.stats
    if not rows:
        return {}
    pick = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("promotion") == 6:
            pick = row
            break
        if pick is None or row.get("promotion", 0) > pick.get("promotion", 0):
            pick = row
    if not pick:
        return {}
    return {
        k: pick.get(k, 0)
        for k in ("base_hp", "base_hp_add", "base_attack", "base_attack_add",
                  "base_defence", "base_defence_add")
    }


def transform_relicset_detail(raw: dict, set_id: str) -> RelicSetInfo:
    """遗器套装详情提纯。"""
    parts_raw = raw.get("parts", {})
    parts = {
        part_id: RelicSetPart(
            id=part_id,
            name=part.get("name", "") or "",
            desc=part.get("desc", "") or "",
        )
        for part_id, part in parts_raw.items()
        if isinstance(part, dict)
    }

    require_num = raw.get("require_num", {})
    bonus_2pc = _parse_set_bonus(require_num.get("2"))
    bonus_4pc = _parse_set_bonus(require_num.get("4"))

    return RelicSetInfo(
        id=set_id,
        name=raw.get("name", ""),
        icon_url=relicset_icon_url(raw.get("icon", "")),
        parts=parts,
        bonus_2pc=bonus_2pc,
        bonus_4pc=bonus_4pc,
    )
