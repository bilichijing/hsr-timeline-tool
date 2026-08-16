"""技能解析。

从 nanoka 的 skills 结构提取：
- 技能倍率（普攻/战技/终结技/天赋/追加攻击）
- 削韧值
- 能量回复
- SP 消耗/回复

nanoka 新版技能数据结构（详情）：
    {
        "150401": {
            "id": 150401,
            "name": "...",
            "type": "Normal",       # Normal/BPSkill/Ultra/MazeNormal/Maze
            "type_name": "普攻",
            "tag": "SingleAttack",  # 攻击类型（非技能类型）
            "sp_base": 20,          # 该行动类型的能量回复
            "bp_need": -1,          # SP 消耗（普攻 -1 表示回复）
            "bp_add": 1,            # SP 回复量（普攻）
            "show_stance_list": [30, 0, 0],   # 削韧值（第一项）
            "level": {              # 按技能等级的参数表
                "1": {"param_list": [0.5]},
                ...
                "10": {"param_list": [1.4]},
            }
        }
    }

技能类型 type 字段：
- Normal   普攻（+1 SP）
- BPSkill  战技（-1 SP）
- Ultra    终结技（消耗能量）
- 天赋的 type 为 None，靠 type_name 含"天赋"识别
- MazeNormal / Maze 秘技（战前用，模拟器中不建模）
- 追加攻击（FollowUp）为 SkillType 新增维度：追加攻击造成任何伤害类型
  （常规/击破/超击破/持续/欢愉），技能类型与伤害类型是两个独立维度
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .damage import DamageType


class SkillType(Enum):
    """技能类型（与伤害类型 DamageType 是独立维度）。"""

    NORMAL = "Normal"          # 普攻
    SKILL = "Skill"            # 战技
    ULTRA = "Ultra"            # 终结技
    TALENT = "Talent"          # 天赋
    TECHNIQUE = "Technique"    # 秘技
    MEMO_DNSKILL = "MemoDNSkill"  # 忆灵技能
    FOLLOW_UP = "FollowUp"     # 追加攻击（可造成任何伤害类型）
    ADDED = "Added"            # 附加伤害（独立攻击类型，不属于普攻/战技/终结技/追加攻击）


# 新版 type 字段 → 技能类型
_TYPE_FIELD_MAP: dict[str, SkillType] = {
    "Normal": SkillType.NORMAL,
    "BPSkill": SkillType.SKILL,
    "Ultra": SkillType.ULTRA,
    "MazeNormal": SkillType.TECHNIQUE,
    "Maze": SkillType.TECHNIQUE,
    "MemoDNSkill": SkillType.MEMO_DNSKILL,  # 忆灵技（新版 type 字段标识）
}

# 技能等级范围（普攻 10 级封顶，其余 15 级）
SKILL_LEVEL_RANGE: dict[SkillType, tuple[int, int]] = {
    SkillType.NORMAL: (1, 10),
    SkillType.SKILL: (1, 15),
    SkillType.ULTRA: (1, 15),
    SkillType.TALENT: (1, 15),
    SkillType.MEMO_DNSKILL: (1, 15),
}


def clamp_skill_level(skill_type: SkillType, level: int) -> int:
    """将技能等级钳制到合法范围（普攻 1-10，其余 1-15）。"""
    lo, hi = SKILL_LEVEL_RANGE.get(skill_type, (1, 15))
    return min(max(level, lo), hi)

# 旧版 tag 字段 → 技能类型（兼容旧数据结构）
_OLD_TAG_MAP: dict[str, SkillType] = {
    "Normal": SkillType.NORMAL,
    "Skill": SkillType.SKILL,
    "Ultra": SkillType.ULTRA,
    "Talent": SkillType.TALENT,
    "Technique": SkillType.TECHNIQUE,
    "MemoDNSkill": SkillType.MEMO_DNSKILL,
}


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
    fixed_base_value: float | None = None  # 固定基础伤害（如忆灵技：累计治疗×比例）


@dataclass
class Skill:
    """单个技能。

    level 为技能等级（普攻 1-10，战技/终结技/天赋 1-15），
    影响 multiplier 取 level 参数表的哪一行。
    """

    id: str
    name: str
    skill_type: SkillType
    desc: str = ""
    sp_cost: int = 0                  # SP 消耗（普攻 -1 表示回复，战技 1）
    energy_cost: int = 0              # 能量消耗（终结技）
    energy_recover: int = 0           # 能量回复
    effects: list[SkillEffect] = field(default_factory=list)
    params: list[float] = field(default_factory=list)  # 该等级完整 param_list（#N → params[N-1]）
    raw: dict[str, Any] = field(default_factory=dict)  # 原始数据


def parse_skill_level_params(param_list: list[list[float]], level: int) -> list[float]:
    """从 ParamList 提取指定等级的参数（旧版结构）。

    ParamList 结构：[[等级1参数], [等级2参数], ...]
    level 从 1 开始，最大 10。
    """
    if not param_list:
        return []
    idx = min(max(level - 1, 0), len(param_list) - 1)
    return param_list[idx]


def parse_level_params(raw: dict[str, Any], level: int) -> list[float]:
    """从技能原始数据提取指定等级的完整参数。

    新版：raw["level"] 为 {"1": {"param_list": [...]}, ...}，按 str(level) 取，
          等级超出时钳制到最大可用级（战技/终结技/天赋最多 15 级）。
    旧版：回退 ParamList / param_list 列表。
    """
    level_map = raw.get("level")
    if isinstance(level_map, dict):
        levels = sorted(int(k) for k in level_map if str(k).isdigit())
        if not levels:
            return []
        idx = min(max(level, levels[0]), levels[-1])
        row = level_map.get(str(idx), {})
        if isinstance(row, dict):
            return [float(v) for v in row.get("param_list", [])]
        return []

    param_list = raw.get("ParamList") or raw.get("param_list") or []
    if param_list:
        return [float(v) for v in parse_skill_level_params(param_list, level)]
    return []


def _parse_skill_type(raw: dict[str, Any]) -> SkillType:
    """识别技能类型。

    优先级：新版 type 字段映射 → type 缺失/None 的天赋启发式 → 旧版 tag 字段 → NORMAL。
    天赋启发式：新版天赋的 type 为 None，但 type_name 为"天赋"。
    """
    type_field = raw.get("type")
    if isinstance(type_field, str) and type_field in _TYPE_FIELD_MAP:
        return _TYPE_FIELD_MAP[type_field]

    # type 缺失/None：天赋启发式
    type_name = raw.get("type_name", "")
    if not type_field and "天赋" in str(type_name):
        return SkillType.TALENT

    tag = raw.get("tag", "")
    if isinstance(tag, str) and tag in _OLD_TAG_MAP:
        return _OLD_TAG_MAP[tag]
    return SkillType.NORMAL


def parse_skill(raw: dict[str, Any], level: int = 1) -> Skill:
    """从 nanoka 原始技能数据解析为 Skill。

    Args:
        raw: 单个技能的原始 dict（来自 CharacterInfo.skills）
        level: 技能等级（普攻 1-10，战技/终结技/天赋 1-15）
    """
    skill_id = str(raw.get("id", ""))
    name = raw.get("name", "")
    desc = raw.get("desc", "")
    skill_type = _parse_skill_type(raw)

    # SP 消耗/回复：新版用 bp_need / bp_add，旧版用 sp_cost
    # （真实数据中 bp_need/bp_add 可能为 None，or 0 防御）
    # bp_need=-1 语义：普攻 = 回复（数量 bp_add）；其余类型 = 不消耗
    # （如千冶战技"不消耗战技点"、终结技/天赋的 -1）
    sp_cost = int(raw.get("bp_need", raw.get("sp_cost", 0)) or 0)
    bp_add = int(raw.get("bp_add", 0) or 0)
    if skill_type == SkillType.NORMAL:
        sp_cost = -(bp_add or 1)  # 普攻回复 SP
    elif sp_cost < 0:
        sp_cost = 0  # 非普攻的 -1 表示不消耗（不回复）
    elif skill_type == SkillType.SKILL and sp_cost == 0:
        sp_cost = 1

    # 能量
    energy_cost = int(raw.get("energy_cost", 0) or 0)
    if skill_type == SkillType.ULTRA and energy_cost == 0:
        energy_cost = 90  # 默认终结技消耗（真实耗能由 parse_all_skills 注入）
    # 新版 sp_base = 该行动类型的能量回复（真实数据可能为 None）
    energy_recover = int(raw.get("sp_base", 0) or 0) or int(raw.get("energy_recover", 0) or 0)

    # 倍率与完整参数（nanoka 参数均为小数：0.5 = 50%，2.0 = 200%）
    params = parse_level_params(raw, level)
    effects: list[SkillEffect] = []

    # 首段倍率 = 第一个参数（通常为攻击力倍率）
    if params and params[0] != 0:
        effects.append(
            SkillEffect(
                damage_type=DamageType.NORMAL,
                multiplier=params[0],
                element=raw.get("element", ""),
            )
        )

    # 旧版 simple_param.damage 补充
    simple_param = raw.get("simple_param", {})
    damage_list = simple_param.get("damage", []) if isinstance(simple_param, dict) else []
    for d in damage_list:
        if isinstance(d, dict):
            value = d.get("value", 0)
            element = d.get("element", "")
            if value:
                effects.append(
                    SkillEffect(
                        damage_type=DamageType.NORMAL,
                        multiplier=value,
                        element=element,
                    )
                )

    # 削韧值：新版 show_stance_list[0]，旧版 toughness_damage / toughness
    stance = raw.get("show_stance_list") or []
    toughness = 0
    if isinstance(stance, list) and stance:
        toughness = float(stance[0])
    if toughness == 0:
        toughness = float(raw.get("toughness_damage", 0) or raw.get("toughness", 0))

    # 削韧挂在首段效果上；无效果段时创建仅含削韧的效果
    if toughness:
        if effects:
            effects[0].toughness_damage = toughness
        else:
            effects.append(
                SkillEffect(
                    damage_type=DamageType.NORMAL,
                    multiplier=0.0,
                    toughness_damage=toughness,
                    element=raw.get("element", ""),
                )
            )

    return Skill(
        id=skill_id,
        name=name,
        skill_type=skill_type,
        desc=desc,
        sp_cost=sp_cost,
        energy_cost=energy_cost,
        energy_recover=energy_recover,
        effects=effects,
        params=params,
        raw=raw,
    )


def parse_all_skills(
    skills: dict[str, Any],
    level: int = 1,
    *,
    ultra_energy_cost: int = 0,
    skill_levels: dict[SkillType, int] | None = None,
) -> dict[str, Skill]:
    """解析角色所有技能。

    Args:
        skills: CharacterInfo.skills 字段
        level: 技能兜底等级（未在 skill_levels 指定的类型使用）
        ultra_energy_cost: 终结技能量消耗（角色详情顶层 sp_need，技能 dict 内不含此字段）
        skill_levels: 按技能类型分别指定等级（如 {NORMAL: 10, ULTRA: 15}），
                      未指定的类型回退 level；等级自动钳制到合法范围

    注：欢愉技等级不走本函数（识别逻辑 TODO：可能位于 memosprite 字段或
    type_name 含"欢愉"），由调用方经 CharacterUnit.elation_skill_level 传递。
    """
    result: dict[str, Skill] = {}
    skill_levels = skill_levels or {}
    for skill_id, raw in skills.items():
        if isinstance(raw, dict):
            skill_type = _parse_skill_type(raw)
            lv = clamp_skill_level(skill_type, skill_levels.get(skill_type, level))
            skill = parse_skill(raw, level=lv)
            # 技能 dict 内不含 energy_cost 字段时注入详情顶层 sp_need
            if ultra_energy_cost > 0 and "energy_cost" not in raw and skill.skill_type == SkillType.ULTRA:
                skill.energy_cost = ultra_energy_cost
            result[skill_id] = skill
    return result


def get_skill_by_type(skills: dict[str, Skill], skill_type: SkillType) -> Skill | None:
    """按类型获取技能。"""
    for s in skills.values():
        if s.skill_type == skill_type:
            return s
    return None
