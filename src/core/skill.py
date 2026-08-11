"""技能解析。

从 nanoka 的 skill_trees 结构提取：
- 技能倍率（普攻/战技/终结技/天赋）
- 削韧值
- 能量回复
- SP 消耗/回复

nanoka 技能数据结构（简化）：
    {
        "1001": {
            "id": "1001",
            "name": "...",
            "tag": "Normal",   # Normal/Skill/Ultra/Talent/Technique/MemoDNSkill
            "ParamList": [[...levels...]],
            ...
        }
    }

技能类型 tag：
- Normal   普攻（+1 SP）
- Skill    战技（-1 SP）
- Ultra    终结技（消耗能量）
- Talent   天赋（被动/触发）
- Technique 秘技（战前用）
- MemoDNSkill 忆灵技能
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .damage import DamageType


class SkillType(Enum):
    """技能类型。"""

    NORMAL = "Normal"          # 普攻
    SKILL = "Skill"            # 战技
    ULTRA = "Ultra"            # 终结技
    TALENT = "Talent"          # 天赋
    TECHNIQUE = "Technique"    # 秘技
    MEMO_DNSKILL = "MemoDNSkill"  # 忆灵技能


@dataclass
class SkillEffect:
    """技能效果（一次技能可含多个效果）。

    单个技能可能造成多种伤害（如战技打 3 段），每段是一个 SkillEffect。
    """

    damage_type: DamageType = DamageType.NORMAL
    multiplier: float = 0.0           # 伤害倍率（小数，1.2 = 120% 攻击力）
    base_stat: str = "atk"            # 基础属性（atk/hp/def）
    toughness_damage: float = 0.0     # 削韧值
    energy_recover: float = 0.0       # 能量回复
    hits: int = 1                     # 命中次数
    element: str = ""                 # 属性（覆盖角色属性）


@dataclass
class Skill:
    """单个技能。

    level 为技能等级（1-10），影响 multiplier 取 ParamList 的哪一行。
    """

    id: str
    name: str
    skill_type: SkillType
    desc: str = ""
    sp_cost: int = 0                  # SP 消耗（普攻 -1 表示回复，战技 1）
    energy_cost: int = 0              # 能量消耗（终结技）
    energy_recover: int = 0           # 能量回复
    effects: list[SkillEffect] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)  # 原始数据


def parse_skill_level_params(param_list: list[list[float]], level: int) -> list[float]:
    """从 ParamList 提取指定等级的参数。

    ParamList 结构：[[等级1参数], [等级2参数], ...]
    level 从 1 开始，最大 10。
    """
    if not param_list:
        return []
    idx = min(max(level - 1, 0), len(param_list) - 1)
    return param_list[idx]


def parse_skill(raw: dict[str, Any], level: int = 1) -> Skill:
    """从 nanoka 原始技能数据解析为 Skill。

    Args:
        raw: 单个技能的原始 dict（来自 CharacterInfo.skills）
        level: 技能等级（1-10）
    """
    skill_id = str(raw.get("id", ""))
    name = raw.get("name", "")
    tag = raw.get("tag", "Normal")
    desc = raw.get("desc", "")
    try:
        skill_type = SkillType(tag)
    except ValueError:
        skill_type = SkillType.NORMAL

    # SP 消耗
    sp_cost = int(raw.get("sp_cost", 0))
    if skill_type == SkillType.NORMAL:
        sp_cost = -1  # 普攻回复 1 SP
    elif skill_type == SkillType.SKILL and sp_cost == 0:
        sp_cost = 1

    # 能量
    energy_cost = int(raw.get("energy_cost", 0))
    if skill_type == SkillType.ULTRA and energy_cost == 0:
        energy_cost = 90  # 默认终结技消耗
    energy_recover = int(raw.get("energy_recover", 0))

    # 解析倍率
    effects: list[SkillEffect] = []
    param_list = raw.get("ParamList") or raw.get("param_list") or []
    simple_param = raw.get("simple_param", {})
    damage_list = simple_param.get("damage", []) if isinstance(simple_param, dict) else []

    if param_list:
        params = parse_skill_level_params(param_list, level)
        # 第一个参数通常是倍率
        if params:
            multiplier = params[0] / 100.0 if params[0] > 1 else params[0]
            effects.append(
                SkillEffect(
                    damage_type=DamageType.NORMAL,
                    multiplier=multiplier,
                    element=raw.get("element", ""),
                )
            )

    # 从 damage_list 补充
    for d in damage_list:
        if isinstance(d, dict):
            value = d.get("value", 0)
            element = d.get("element", "")
            if value:
                mult = value / 100.0 if value > 1 else value
                effects.append(
                    SkillEffect(
                        damage_type=DamageType.NORMAL,
                        multiplier=mult,
                        element=element,
                    )
                )

    # 削韧值（如有）
    toughness = raw.get("toughness_damage", 0) or raw.get("toughness", 0)

    return Skill(
        id=skill_id,
        name=name,
        skill_type=skill_type,
        desc=desc,
        sp_cost=sp_cost,
        energy_cost=energy_cost,
        energy_recover=energy_recover,
        effects=effects,
        raw=raw,
    )


def parse_all_skills(skills: dict[str, Any], level: int = 1) -> dict[str, Skill]:
    """解析角色所有技能。

    Args:
        skills: CharacterInfo.skills 字段
        level: 技能等级（普攻/战技/终结技默认 1-10）
    """
    result: dict[str, Skill] = {}
    for skill_id, raw in skills.items():
        if isinstance(raw, dict):
            skill = parse_skill(raw, level=level)
            result[skill_id] = skill
    return result


def get_skill_by_type(skills: dict[str, Skill], skill_type: SkillType) -> Skill | None:
    """按类型获取技能。"""
    for s in skills.values():
        if s.skill_type == skill_type:
            return s
    return None
