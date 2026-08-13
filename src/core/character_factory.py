"""角色构造：纯数据 → CharacterUnit。

core 层不依赖 api 模块（api 的 pydantic 模型 / PySide6 均不在此导入），
参数全部用基本类型 / dict，可独立测试。UI 层从 CharacterInfo 解包后调用。

80 级面板公式：
    最终值 = stats["6"].base + add × (等级-1) = base + add × 79
    不死途 1504：ATK = 359.04 + 5.28×79 = 776.16（用户实测校准）；
    速度/暴击率/暴击伤害不随等级成长，直接取 stats["6"] 值。

能量上限（TODO 实测校准）：nanoka 详情无 energy_max 字段，
星铁多数角色能量上限 = 终结技耗能，用 sp_need 近似（0 时兜底 100）。
"""

from __future__ import annotations

from typing import Any

from .simulator import CharacterUnit
from .skill import SkillType, parse_all_skills
from .stats import BaseStats, StatBonus

MAX_LEVEL = 80  # 满级等级
GROWTH_STEPS = MAX_LEVEL - 1  # 成长级数（属性 = 基础 + 每级成长 × (等级-1)）

# 80 级突破等级键（nanoka stats 表的键为突破等级 0-6，"6" = 80 级）
STATS_KEY_80 = "6"

# 行迹属性加成：property_type（nanoka）→ StatBonus 字段名
# 属性伤害（物理/火/冰/雷/风/量子/虚数）全部进单值 dmg_bonus
# （TODO: dmg_bonus 暂不区分属性，stats.py 既有 TODO）
TRACE_PROPERTY_MAP: dict[str, str] = {
    "HPAddedRatio": "hp_pct",
    "AttackAddedRatio": "atk_pct",
    "DefenceAddedRatio": "def_pct",
    "SpeedDelta": "spd_flat",
    "CriticalChanceBase": "crit_rate",
    "CriticalDamageBase": "crit_dmg",
    "BreakDamageAddedRatioBase": "break_effect",
    "EffectHitRateBase": "effect_hit",
    "EffectResistanceBase": "effect_res",
    "HealRatioBase": "outgoing_heal",
    "PhysicalAddedRatio": "dmg_bonus",
    "FireAddedRatio": "dmg_bonus",
    "IceAddedRatio": "dmg_bonus",
    "ThunderAddedRatio": "dmg_bonus",
    "WindAddedRatio": "dmg_bonus",
    "QuantumAddedRatio": "dmg_bonus",
    "ImaginaryAddedRatio": "dmg_bonus",
}


def extract_trace_bonuses(skill_trees_raw: dict | None) -> StatBonus:
    """从 skill_trees 提取行迹属性加成（status_add_list → StatBonus）。

    nanoka 行迹属性强化点（point_type=1，如 point09-18）的 status_add_list
    形如 [{"property_type": "AttackAddedRatio", "value": 0.04}]。
    全部点满（80 级满行迹）时累加，如不死途：攻击 10%、暴击伤害 37.3%、雷伤 14.4%。

    注意：point_type=3 的额外能力（如"罪途"）是机制类行迹（参数字段），
    其加成是战斗内触发条件，不在面板静态加成范围内，不在此处处理。
    """
    bonus = StatBonus()
    if not skill_trees_raw:
        return bonus
    for group in skill_trees_raw.values():
        if not isinstance(group, dict):
            continue
        for point in group.values():
            if not isinstance(point, dict):
                continue
            for entry in point.get("status_add_list", []):
                if not isinstance(entry, dict):
                    continue
                field_name = TRACE_PROPERTY_MAP.get(entry.get("property_type", ""))
                if field_name is None:
                    continue
                value = float(entry.get("value", 0))
                setattr(bonus, field_name, getattr(bonus, field_name) + value)
    return bonus


def convert_stats80(stats_row: dict[str, float]) -> BaseStats:
    """nanoka 详情 stats["6"]（80 级突破行）→ 80 级 BaseStats。

    公式：value = base + add × 79（成长 ×(等级-1)；速度/暴击/仇恨不成长直接取用）。
    缺失字段默认 0。
    """
    return BaseStats(
        hp_base=float(stats_row.get("hp_base", 0)) + float(stats_row.get("hp_add", 0)) * GROWTH_STEPS,
        atk_base=float(stats_row.get("attack_base", 0)) + float(stats_row.get("attack_add", 0)) * GROWTH_STEPS,
        def_base=float(stats_row.get("defence_base", 0)) + float(stats_row.get("defence_add", 0)) * GROWTH_STEPS,
        spd_base=float(stats_row.get("speed_base", 0)),
        crit_rate=float(stats_row.get("critical_chance", 0.05)),
        crit_dmg=float(stats_row.get("critical_damage", 0.50)),
        aggro=float(stats_row.get("base_aggro", 100.0)),
    )


def build_character_unit(
    *,
    unit_id: str,
    name: str,
    path: str,
    element: str,
    stats80: dict[str, float],
    skills_raw: dict[str, Any],
    sp_need: int = 0,
    level: int = 1,
    skill_levels: dict[SkillType, int] | None = None,
    elation_skill_level: int = 1,
    char_id: str = "",
    dmg_bonus: float = 0.0,
    initial_energy: float = 0.0,
    skill_trees_raw: dict | None = None,
) -> CharacterUnit:
    """构造带真实技能与面板的角色单位。

    Args:
        unit_id: 战斗单位 ID（如 "char1"）
        name: 角色名（中文）
        path: 命途英文原始值（如 "Rogue"）
        element: 属性英文原始值（如 "Thunder"）
        stats80: 80 级面板原始 dict（详情 stats["6"]）
        skills_raw: 原始技能 dict（CharacterInfo.skills）
        sp_need: 终结技耗能（→ energy_max，TODO 实测校准）
        level: 技能兜底等级
        skill_levels: 按技能类型分别指定等级（未指定回退 level）
        elation_skill_level: 欢愉技等级（识别逻辑 TODO，仅存储）
        char_id: nanoka 角色 ID（挂载角色技能模块用）
        dmg_bonus: 属性增伤（角色自身属性，UI 表格"属性增伤"列）
        initial_energy: 战斗开始初始能量（freesr sp_value）
        skill_trees_raw: 原始行迹（CharacterInfo.skill_trees），提取行迹属性加成
    """
    base = convert_stats80(stats80)
    base.energy_max = float(sp_need) if sp_need > 0 else 100.0
    # 行迹属性加成（攻击%/暴击伤害/属性伤害等，满行迹常驻）
    bonus = extract_trace_bonuses(skill_trees_raw)
    bonus = bonus.add(StatBonus(dmg_bonus=dmg_bonus))
    skills = parse_all_skills(
        skills_raw,
        level=level,
        ultra_energy_cost=sp_need,
        skill_levels=skill_levels,
    )
    return CharacterUnit(
        unit_id=unit_id,
        name=name,
        path=path,
        element=element,
        level=MAX_LEVEL,
        base_stats=base,
        bonus_stats=bonus,
        skills=skills,
        elation_skill_level=elation_skill_level,
        char_id=char_id,
        initial_energy=initial_energy,
        skill_trees_raw=skill_trees_raw or {},
    )
