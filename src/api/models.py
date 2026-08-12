"""Pydantic 数据模型。

命名约定：
- Nanoka 前缀 = nanoka 原始 JSON 结构（字段名保留原样，如 baseType / damageType）
- 无前缀 = 提纯后的业务模型（字段名用 snake_case，已映射为中文/枚举）

列表项结构轻量（含 zh 字段），详情结构重型（含技能/星魂/属性）。
技能倍率解析（skill.level.param_list）留到阶段 2 的 core/skill.py，
此处的详情模型先用 dict 接收复杂字段。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


# ── 业务枚举 ───────────────────────────────────────────────

class Rarity(int, Enum):
    """角色/光锥稀有度。"""

    THREE = 3
    FOUR = 4
    FIVE = 5


class Path(str, Enum):
    """命途（nanoka 原始字符串）。"""

    KNIGHT = "Knight"      # 存护
    WARRIOR = "Warrior"    # 毁灭
    MAGE = "Mage"          # 智识
    WARLOCK = "Warlock"    # 虚无
    SHAMAN = "Shaman"      # 同谐
    PRIEST = "Priest"      # 丰饶
    ROGUE = "Rogue"        # 巡猎
    MEMORY = "Memory"      # 记忆
    ELATION = "Elation"    # 欢愉


class Element(str, Enum):
    """属性（nanoka 原始字符串）。"""

    PHYSICAL = "Physical"
    FIRE = "Fire"
    ICE = "Ice"
    THUNDER = "Thunder"
    WIND = "Wind"
    QUANTUM = "Quantum"
    IMAGINARY = "Imaginary"


# ── 列表项（轻量）──────────────────────────────────────────

class Character(BaseModel):
    """角色列表项（提纯后）。path/element 保留英文原始值，UI 层用 PATH_MAP 转中文。"""

    id: str
    name_zh: str
    name_en: str
    rarity: Rarity
    path: str          # "Knight" / "Rogue" / ...
    element: str       # "Ice" / "Fire" / ...
    icon_url: str


class Lightcone(BaseModel):
    """光锥列表项（提纯后）。"""

    id: str
    name_zh: str
    name_en: str
    rarity: Rarity
    path: str
    icon_url: str
    atk: int = 0


class RelicSetBonus(BaseModel):
    """遗器套装效果。"""

    desc: str
    param_list: list[float] = Field(default_factory=list)


class RelicSet(BaseModel):
    """遗器套装列表项（提纯后）。"""

    id: str
    name_zh: str
    name_en: str
    icon_url: str
    bonus_2pc: RelicSetBonus | None = None
    bonus_4pc: RelicSetBonus | None = None


class Monster(BaseModel):
    """怪物列表项（提纯后）。"""

    id: str
    name_zh: str
    name_en: str
    icon_url: str
    weaknesses: list[str] = Field(default_factory=list)  # ["Fire", "Thunder"]
    rank: str = ""


# ── 属性表 ─────────────────────────────────────────────────

class StatsRow(BaseModel):
    """单等级基础属性表（对应 stats[level]）。"""

    attack_base: float = 0.0
    attack_add: float = 0.0
    defence_base: float = 0.0
    defence_add: float = 0.0
    hp_base: float = 0.0
    hp_add: float = 0.0
    speed_base: float = 0.0
    critical_chance: float = 0.05
    critical_damage: float = 0.50
    base_aggro: float = 100.0


# ── 详情（重型）────────────────────────────────────────────

class CharacterInfo(BaseModel):
    """角色详情（提纯后）。

    skills / skill_trees / ranks 保留原始 dict 结构，
    倍率解析留到 core/skill.py。
    """

    id: str
    name: str
    desc: str
    rarity: Rarity
    path: str               # "Knight" 等英文原始值
    element: str            # "Ice" 等英文原始值
    sp_need: int = 0        # 能量需求
    icon_url: str
    stats: dict[str, StatsRow] = Field(default_factory=dict)
    skills: dict = Field(default_factory=dict)        # 原始技能树
    skill_trees: dict = Field(default_factory=dict)   # 原始行迹
    ranks: dict = Field(default_factory=dict)         # 原始星魂
    memosprite: dict = Field(default_factory=dict)    # 忆灵（2.x 机制）


class LightconeRefinement(BaseModel):
    """光锥叠影效果。"""

    name: str
    desc: str
    levels: dict[str, list[float]] = Field(default_factory=dict)  # {1: [0.12, 3], ...}


class LightconeInfo(BaseModel):
    """光锥详情（提纯后）。"""

    id: str
    name: str
    desc: str
    rarity: Rarity
    path: str
    icon_url: str
    refinement: LightconeRefinement | None = None
    stats: list = Field(default_factory=list)  # 各等级属性（nanoka 返回数组）


class RelicSetPart(BaseModel):
    """遗器套装的单件。"""

    id: str
    name: str
    desc: str


class RelicSetInfo(BaseModel):
    """遗器套装详情（提纯后）。"""

    id: str
    name: str
    icon_url: str
    parts: dict[str, RelicSetPart] = Field(default_factory=dict)
    bonus_2pc: RelicSetBonus | None = None
    bonus_4pc: RelicSetBonus | None = None
