"""常量、枚举映射与图标 URL 生成。

所有对 nanoka 数据的"字符串 → 业务枚举"转换都在这里查表。
图标 URL 拼接规则也集中在此模块。
"""

from __future__ import annotations

import re

# ── 数据源基址 ──────────────────────────────────────────────
NANOKA_BASE = "https://static.nanoka.cc"
DATA_BASE = f"{NANOKA_BASE}/hsr"
ASSET_BASE = f"{NANOKA_BASE}/assets/hsr"
MANIFEST_URL = f"{NANOKA_BASE}/manifest.json"


# ── 枚举映射表（nanoka 原始字符串 → 业务值）─────────────────

# 稀有度：CombatPowerAvatarRarityType4 → 4
RARITY_MAP: dict[str, int] = {
    "CombatPowerAvatarRarityType4": 4,
    "CombatPowerAvatarRarityType5": 5,
    "CombatPowerLightconeRarity3": 3,
    "CombatPowerLightconeRarity4": 4,
    "CombatPowerLightconeRarity5": 5,
}

# 命途：Knight → 存护
PATH_MAP: dict[str, str] = {
    "Knight": "存护",
    "Rogue": "毁灭",
    "Mage": "智识",
    "Warlock": "虚无",
    "Shaman": "丰饶",
    "Priest": "同谐",
    "Warrior": "巡猎",
    "Memory": "记忆",
    "Elation": "欢愉",
}

# 属性：Ice → 冰
ELEMENT_MAP: dict[str, str] = {
    "Physical": "物理",
    "Fire": "火",
    "Ice": "冰",
    "Thunder": "雷",
    "Wind": "风",
    "Quantum": "量子",
    "Imaginary": "虚数",
}


# ── 缓存 TTL（秒）──────────────────────────────────────────

class CacheTTL:
    """diskcache 过期时间常量。"""

    VERSION = 3600       # manifest 版本号：1 小时
    LIST = 600           # 列表数据：10 分钟
    DETAIL = 3600        # 详情数据：1 小时
    ZH_NAMES = 86400     # 中文名映射：1 天（列表已含 zh 字段，此项备用）


# ── 图标 URL 生成 ──────────────────────────────────────────
# 实测确认的 URL 模式：
#   角色：  https://static.nanoka.cc/assets/hsr/avatardrawcard/{id}.webp
#   光锥：  https://static.nanoka.cc/assets/hsr/itemfigures/{id}.webp
#   遗器：  https://static.nanoka.cc/assets/hsr/itemfigures/{数字ID}.webp
#   怪物：  https://static.nanoka.cc/assets/hsr/monsterfigure/{文件名}.webp


def character_icon_url(char_id: str | int) -> str:
    """角色头像图标 URL（用数字 ID，非 icon 字段的简短名）。"""
    return f"{ASSET_BASE}/avatardrawcard/{char_id}.webp"


def lightcone_icon_url(lightcone_id: str | int) -> str:
    """光锥图标 URL（用数字 ID）。"""
    return f"{ASSET_BASE}/itemfigures/{lightcone_id}.webp"


def relicset_icon_url(icon_field: str) -> str:
    """遗器套装图标 URL。

    icon_field 示例：'SpriteOutput/ItemIcon/71000.png'
    提取其中的数字 ID 拼接 itemfigures 路径。
    """
    match = re.search(r"/(\d+)\.png$", icon_field)
    if not match:
        return ""
    return f"{ASSET_BASE}/itemfigures/{match.group(1)}.webp"


def monster_icon_url(icon_field: str) -> str:
    """怪物图标 URL。

    icon_field 示例：'SpriteOutput/MonsterFigure/Monster_1002011.png'
    取文件名（保留大小写）换 .webp 扩展名。
    """
    match = re.search(r"/([^/]+)\.png$", icon_field)
    if not match:
        return ""
    return f"{ASSET_BASE}/monsterfigure/{match.group(1)}.webp"
