"""freesr-data.json 角色面板导入（core 层解析与面板计算）。

纯逻辑模块：不导入 api / PySide6，可独立测试。
数值表来自《freesr-data导入功能要求.txt》（用户提供）。

数据格式：
- avatars:  {avatar_id: {avatar_id, data: {rank, skills}, level, promotion, sp_max, sp_value}}
- relics:   [{equip_avatar, level, sub_affixes: [{count, step, sub_affix_id}],
              relic_id, main_affix_id, relic_set_id}]  （relic_id 末位 = 部位 1-6）
- lightcones: [{equip_avatar, item_id, level, promotion, rank}]

副词条公式：最终值 = 最低档×count + (第二档-最低档)×step。
主词条按部位与 main_affix_id 映射，数值表见 RELIC_MAIN_AFFIXES。

待实现（用户明确晚点做）：
- 遗器套装效果（relic_set_id 只记录不计算）
- 星魂效果（rank 只记录）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .character_factory import GROWTH_STEPS, convert_stats80, extract_trace_bonuses
from .skill import SkillType, clamp_skill_level
from .stats import BaseStats, FinalStats, StatBonus, StatCalculator

# ── 副词条数值表 ───────────────────────────────────────────
# {sub_affix_id: (StatBonus 字段名, (最低档, 第二档, 最高档))}
# 百分比词条存百分数（3.456 = 3.456%），计算后换算为小数
RELIC_SUB_AFFIXES: dict[int, tuple[str, tuple[float, float, float]]] = {
    1: ("hp_flat", (33.870, 38.104, 42.338)),
    2: ("atk_flat", (16.935, 19.052, 21.169)),
    3: ("def_flat", (16.935, 19.052, 21.169)),
    4: ("hp_pct", (3.456, 3.888, 4.320)),
    5: ("atk_pct", (3.456, 3.888, 4.320)),
    6: ("def_pct", (4.320, 4.860, 5.400)),
    7: ("spd_flat", (2.0, 2.3, 2.6)),
    8: ("crit_rate", (2.592, 2.916, 3.240)),
    9: ("crit_dmg", (5.184, 5.832, 6.480)),
    10: ("effect_hit", (3.456, 3.888, 4.320)),
    11: ("effect_res", (3.456, 3.888, 4.320)),
    12: ("break_effect", (5.184, 5.832, 6.480)),
}

# 百分比词条集合（写 StatBonus 前需 ÷100）
RELIC_PCT_KEYS: frozenset[str] = frozenset({
    "hp_pct", "atk_pct", "def_pct", "crit_rate", "crit_dmg",
    "break_effect", "effect_hit", "effect_res", "energy_regen",
    "outgoing_heal", "dmg_bonus",
})


# ── 主词条数值表 ───────────────────────────────────────────
# {部位(1-6): {main_affix_id: (StatBonus 字段名, 数值)}}
# 部位：1头部 2手部 3躯干 4脚部 5位面球 6连结绳；百分比存百分数
# 脚部 id1-3、位面球 id1-3、连结绳 id3-5 与躯干同值（用户文档注明）
RELIC_MAIN_AFFIXES: dict[int, dict[int, tuple[str, float]]] = {
    1: {1: ("hp_flat", 705.0)},                            # 头部
    2: {1: ("atk_flat", 352.0)},                           # 手部
    3: {  # 躯干
        1: ("hp_pct", 43.2), 2: ("atk_pct", 43.2), 3: ("def_pct", 54.0),
        4: ("crit_rate", 32.4), 5: ("crit_dmg", 64.8),
        6: ("outgoing_heal", 34.5), 7: ("effect_hit", 43.2),
    },
    4: {  # 脚部（id4 速度固定值）
        1: ("hp_pct", 43.2), 2: ("atk_pct", 43.2), 3: ("def_pct", 54.0),
        4: ("spd_flat", 25.0),
    },
    5: {  # 位面球（id4-10 属性伤害 38.8%，全部进 dmg_bonus）
        1: ("hp_pct", 43.2), 2: ("atk_pct", 43.2), 3: ("def_pct", 54.0),
        4: ("dmg_bonus", 38.8), 5: ("dmg_bonus", 38.8), 6: ("dmg_bonus", 38.8),
        7: ("dmg_bonus", 38.8), 8: ("dmg_bonus", 38.8), 9: ("dmg_bonus", 38.8),
        10: ("dmg_bonus", 38.8),
    },
    6: {  # 连结绳
        1: ("break_effect", 64.8), 2: ("energy_regen", 19.4),
        3: ("hp_pct", 43.2), 4: ("atk_pct", 43.2), 5: ("def_pct", 54.0),
    },
}

# TODO: 位面球 id4-10 的元素顺序（物理/火/冰/雷/风/量子/虚数）待实测校准；
# 因 StatBonus.dmg_bonus 为单值（stats.py TODO），当前全部写入 dmg_bonus 无实际影响，
# 未来"按属性区分增伤"时再按顺序归属。

# 主技能 id 后缀 → SkillType（freesr "1504001" → 普攻）
FREESR_SKILL_SUFFIX: dict[str, SkillType] = {
    "001": SkillType.NORMAL,
    "002": SkillType.SKILL,
    "003": SkillType.ULTRA,
    "004": SkillType.TALENT,
}


# ── 数据模型 ───────────────────────────────────────────────


@dataclass
class FreesrAvatar:
    """freesr 角色配置。"""

    char_id: str
    rank: int = 0
    skill_levels: dict[SkillType, int] = field(default_factory=dict)  # 主技能等级
    sp_max: int = 100
    sp_value: int = 0          # 进战斗初始能量
    level: int = 80
    promotion: int = 6


@dataclass
class FreesrRelic:
    """freesr 遗器（解析后含主/副词条合并加成）。"""

    equip_avatar: str
    slot: int                  # 1-6 部位（relic_id 末位）
    relic_id: int
    relic_set_id: int          # 套装编号（只记录不计算）
    level: int = 15
    main_affix_id: int = 0
    bonus: StatBonus = field(default_factory=StatBonus)   # 主词条+副词条
    sub_affixes: list[tuple[int, int, int]] = field(default_factory=list)  # (id, count, step)
    raw: dict = field(default_factory=dict)               # 原始 JSON（存行数据供套装效果）


@dataclass
class FreesrLightcone:
    """freesr 光锥。"""

    equip_avatar: str
    item_id: int
    level: int = 80
    promotion: int = 6
    rank: int = 1
    raw: dict = field(default_factory=dict)


@dataclass
class FreesrProfile:
    """解析后的完整 freesr 配置。"""

    avatars: dict[str, FreesrAvatar] = field(default_factory=dict)
    relics: dict[str, list[FreesrRelic]] = field(default_factory=dict)      # 按 equip_avatar 聚合
    lightcones: dict[str, list[FreesrLightcone]] = field(default_factory=dict)


# ── 解析函数 ───────────────────────────────────────────────


def to_nanoka_skill_id(freesr_id: str) -> str:
    """freesr 技能 id → nanoka 技能 id（去掉插入的 0）。

    例："1504001" → "150401"。仅对主技能（001-004）有意义，
    秘技/额外能力等固定等级 1，不参与转换。
    """
    if len(freesr_id) == 7 and freesr_id[4] == "0":
        return freesr_id[:4] + freesr_id[5:]
    return freesr_id


def calc_sub_affix(sub_affix_id: int, count: int, step: int) -> float:
    """副词条数值 = 最低档×count + (第二档-最低档)×step。

    百分比词条返回小数（3.456% → 0.03456），固定值原样。
    """
    entry = RELIC_SUB_AFFIXES.get(sub_affix_id)
    if entry is None:
        return 0.0
    field_name, (tier1, tier2, _) = entry
    value = tier1 * count + (tier2 - tier1) * step
    if field_name in RELIC_PCT_KEYS:
        value /= 100.0
    return value


def _add_bonus(bonus: StatBonus, field_name: str, value: float) -> None:
    """累加单条加成到 StatBonus。"""
    setattr(bonus, field_name, getattr(bonus, field_name) + value)


def parse_relic(relic: dict) -> FreesrRelic:
    """单件遗器解析：部位判定（relic_id % 10）+ 主/副词条 → StatBonus。

    未知 main_affix_id / sub_affix_id 忽略（不抛异常）。
    """
    relic_id = int(relic.get("relic_id", 0))
    slot = relic_id % 10 if relic_id else 0
    equip = str(relic.get("equip_avatar", ""))
    bonus = StatBonus()

    # 主词条
    main_id = int(relic.get("main_affix_id", 0))
    slot_table = RELIC_MAIN_AFFIXES.get(slot, {})
    entry = slot_table.get(main_id)
    if entry:
        field_name, value = entry
        if field_name in RELIC_PCT_KEYS:
            value /= 100.0
        _add_bonus(bonus, field_name, value)

    # 副词条
    sub_affixes: list[tuple[int, int, int]] = []
    for sub in relic.get("sub_affixes", []):
        if not isinstance(sub, dict):
            continue
        sub_id = int(sub.get("sub_affix_id", 0))
        count = int(sub.get("count", 0))
        step = int(sub.get("step", 0))
        value = calc_sub_affix(sub_id, count, step)
        entry = RELIC_SUB_AFFIXES.get(sub_id)
        if entry and value:
            _add_bonus(bonus, entry[0], value)
        sub_affixes.append((sub_id, count, step))

    return FreesrRelic(
        equip_avatar=equip,
        slot=slot,
        relic_id=relic_id,
        relic_set_id=int(relic.get("relic_set_id", 0)),
        level=int(relic.get("level", 15)),
        main_affix_id=main_id,
        bonus=bonus,
        sub_affixes=sub_affixes,
        raw=relic,
    )


def calc_relic_bonus(relics: list[FreesrRelic]) -> StatBonus:
    """多件遗器加成合并（StatBonus.add 累加）。"""
    total = StatBonus()
    for relic in relics:
        total = total.add(relic.bonus)
    return total


def extract_skill_levels(char_id: str, skills: dict) -> dict[SkillType, int]:
    """提取主技能等级（freesr 技能 dict → SkillType → 等级，钳制到合法范围）。

    仅识别主技能（char_id + "001"~"004"），其余技能（秘技/额外能力/行迹）不读取。
    """
    result: dict[SkillType, int] = {}
    for freesr_id, level in skills.items():
        suffix = str(freesr_id)[-3:] if len(str(freesr_id)) >= 3 else ""
        skill_type = FREESR_SKILL_SUFFIX.get(suffix)
        if skill_type is not None:
            result[skill_type] = clamp_skill_level(skill_type, int(level))
    return result


def parse_freesr(data: dict) -> FreesrProfile:
    """解析 freesr-data.json 完整结构（avatars/relics/lightcones）。

    规则：
    - avatar data 缺失或为 None → 跳过（空配置）
    - relic/lightcone 的 equip_avatar 无对应 avatar 配置 → 丢弃
    - relic_set_id 只记录不计算（套装效果待实现）
    """
    profile = FreesrProfile()

    avatars_raw = data.get("avatars", {})
    for avatar_id, item in avatars_raw.items():
        if not isinstance(item, dict):
            continue
        item_data = item.get("data")
        if not isinstance(item_data, dict):
            continue  # 空配置跳过
        char_id = str(item.get("avatar_id", avatar_id))
        profile.avatars[char_id] = FreesrAvatar(
            char_id=char_id,
            rank=max(0, min(6, int(item_data.get("rank", 0) or 0))),
            skill_levels=extract_skill_levels(char_id, item_data.get("skills", {})),
            sp_max=int(item.get("sp_max", 100) or 100),
            sp_value=int(item.get("sp_value", 0) or 0),
            level=int(item.get("level", 80) or 80),
            promotion=int(item.get("promotion", 6) or 6),
        )

    for relic in data.get("relics", []):
        if not isinstance(relic, dict):
            continue
        equip = str(relic.get("equip_avatar", ""))
        if equip not in profile.avatars:
            continue  # 无对应角色配置 → 丢弃
        profile.relics.setdefault(equip, []).append(parse_relic(relic))

    for lc in data.get("lightcones", []):
        if not isinstance(lc, dict):
            continue
        equip = str(lc.get("equip_avatar", ""))
        if equip not in profile.avatars:
            continue
        profile.lightcones.setdefault(equip, []).append(FreesrLightcone(
            equip_avatar=equip,
            item_id=int(lc.get("item_id", 0)),
            level=int(lc.get("level", 80) or 80),
            promotion=int(lc.get("promotion", 6) or 6),
            rank=int(lc.get("rank", 1) or 1),
            raw=lc,
        ))

    return profile


# ── 面板计算 ───────────────────────────────────────────────


def lightcone_base_stats(stats80_row: dict) -> BaseStats:
    """光锥 stats 行（promotion=6 的 80 级行）→ 基础值增量。

    公式与角色一致：base + add×79（成长 ×(等级-1)）；光锥只含 HP/ATK/DEF。
    """
    return BaseStats(
        hp_base=float(stats80_row.get("base_hp", 0)) + float(stats80_row.get("base_hp_add", 0)) * GROWTH_STEPS,
        atk_base=float(stats80_row.get("base_attack", 0)) + float(stats80_row.get("base_attack_add", 0)) * GROWTH_STEPS,
        def_base=float(stats80_row.get("base_defence", 0)) + float(stats80_row.get("base_defence_add", 0)) * GROWTH_STEPS,
    )


def compute_panel(
    char_stats80: dict,
    relics: list[FreesrRelic],
    lightcone_stats80: dict | None = None,
    skill_trees_raw: dict | None = None,
) -> FinalStats:
    """最终面板 = 角色 80 级基础 + 光锥基础 + 行迹/遗器加成（StatCalculator）。"""
    base = convert_stats80(char_stats80)
    if lightcone_stats80:
        lc = lightcone_base_stats(lightcone_stats80)
        base.hp_base += lc.hp_base
        base.atk_base += lc.atk_base
        base.def_base += lc.def_base
    bonus = calc_relic_bonus(relics)
    bonus = bonus.add(extract_trace_bonuses(skill_trees_raw))
    return StatCalculator(base=base, bonus=bonus).final()
