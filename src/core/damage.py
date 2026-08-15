"""伤害公式（6 类）。

依据开发文档 6.4 节实现：
- 6.4.1 抗性系数：1 - 抗性，抗性范围 [-100%, 90%]
- 6.4.2 防御系数：分角色攻击敌人 / 敌人攻击角色两种
- 6.4.3 常规伤害
- 6.4.4 击破伤害
- 6.4.5 超击破伤害
- 6.4.6 持续伤害
- 6.4.7 欢愉伤害

所有百分比均用小数表示（0.2 = 20%）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .stats import FinalStats


# ── 属性击破倍率（开发文档 6.4.4）─────────────────────────

BREAK_ELEMENT_MULTIPLIER: dict[str, float] = {
    "Physical": 2.0,
    "Fire": 2.0,
    "Wind": 1.5,
    "Ice": 1.0,
    "Thunder": 1.0,
    "Quantum": 0.5,
    "Imaginary": 0.5,
}

# 击破基础值系数
BREAK_BASE_COEFF = 3767.55

# 欢愉伤害 80 级基础值
ELATION_BASE_LEVEL_80 = 7535.107

# 默认抗性
DEFAULT_RESISTANCE_WEAK = 0.0     # 弱点属性默认抗性
DEFAULT_RESISTANCE_NON_WEAK = 0.20  # 非弱点属性默认抗性

# 星铁全部 7 种属性（构造怪物属性抗性表用）
ALL_ELEMENTS: list[str] = [
    "Physical", "Fire", "Ice", "Thunder", "Wind", "Quantum", "Imaginary",
]

# 抗性钳制范围
RESISTANCE_MIN = -1.0   # -100%
RESISTANCE_MAX = 0.90   # 90%

# 未击破减伤
UNBROKEN_DAMAGE_REDUCTION = 0.10  # 10%

# 减伤乘算下限
DAMAGE_REDUCTION_FLOOR = 0.01     # 1%


class DamageType(Enum):
    """伤害类型。"""

    NORMAL = "normal"           # 常规伤害
    BREAK = "break"             # 击破伤害
    SUPER_BREAK = "super_break"  # 超击破伤害
    DOT = "dot"                 # 持续伤害
    ELATION = "elation"         # 欢愉伤害
    TRUE = "true"               # 真实伤害（无视防御/抗性/增伤/暴击）


@dataclass
class DefenseContext:
    """防御计算上下文。"""

    attacker_level: int          # 攻击者等级
    defender_level: int          # 防御者等级
    def_ignore: float = 0.0      # 无视防御
    def_reduce: float = 0.0      # 减防
    defender_defense: float = 0  # 防御者防御力（敌人攻击角色时用）
    is_piggy: bool = False       # 是否扑满（特殊防御公式）


@dataclass
class DamageContext:
    """伤害计算上下文（一次伤害的完整输入）。

    所有百分比均为小数（0.2 = 20%）。
    """

    damage_type: DamageType
    element: str                    # 属性（"Fire" / "Ice" / ...）
    base_value: float               # 基础值（攻击力×倍率，或固定值）
    attacker_stats: FinalStats      # 攻击者最终面板
    is_weakness: bool = True        # 是否弱点击中
    is_broken: bool = True          # 目标是否处于击破状态
    resistance: float | None = None  # 显式抗性（None 则按弱点推断）
    res_pen: float = 0.0             # 全属性抗性穿透（最终抗性 = 抗性 - 穿透）

    # 各乘区加成（默认 0）
    dmg_bonus: float = 0.0          # 增伤
    vulnerability: float = 0.0      # 易伤
    weakness: float = 0.0           # 虚弱
    damage_reductions: list[float] = field(default_factory=list)  # 减伤列表（乘算）
    special_multiplier: float = 1.0  # 特殊独立乘区

    # 暴击（默认不暴击）
    is_crit: bool = False
    crit_rate: float = 0.0          # 暴击率（用于期望伤害）
    crit_dmg: float = 0.0           # 暴击伤害

    # 击破专用
    break_effect: float = 0.0       # 击破特攻
    break_dmg_bonus: float = 0.0    # 击破增伤
    toughness_max: float = 0.0      # 韧性上限（击破伤害用）
    actual_toughness_reduced: float = 0.0  # 实际削韧值（超击破用）
    super_break_multiplier: float = 1.0    # 超击破倍率

    # 欢愉专用
    elation_multiplier: float = 1.0  # 欢愉倍率
    is_elation_skill: bool = False   # 是否欢愉技（决定用笑点还是好活当赏）

    # 防御上下文
    defense_ctx: DefenseContext | None = None


# ── 抗性系数（6.4.1）───────────────────────────────────────


def calc_resistance(ctx: DamageContext) -> float:
    """计算抗性系数 = 1 - 抗性。

    最终抗性 = 抗性 - 抗性穿透，范围钳制在 [-100%, 90%]。
    未显式指定时：弱点 0%，非弱点 20%。
    """
    if ctx.resistance is not None:
        res = ctx.resistance
    else:
        res = DEFAULT_RESISTANCE_WEAK if ctx.is_weakness else DEFAULT_RESISTANCE_NON_WEAK
    res = res - ctx.res_pen
    res = max(RESISTANCE_MIN, min(RESISTANCE_MAX, res))
    return 1 - res


def build_enemy_resistance(
    weakness_elements: list[str],
    non_weak_resistance: float = DEFAULT_RESISTANCE_NON_WEAK,
    all_elements: list[str] | None = None,
) -> dict[str, float]:
    """构造怪物属性抗性表 {属性: 抗性}。

    规则：怪物持有弱点的对应属性抗性为 0，
    其余属性使用"非弱点属性抗性"配置（默认 20%）。
    与 calc_resistance 的默认回退行为（弱点 0% / 非弱点 20%）一致。
    """
    elements = all_elements if all_elements is not None else ALL_ELEMENTS
    weak_set = set(weakness_elements)
    return {
        elem: 0.0 if elem in weak_set else non_weak_resistance
        for elem in elements
    }


# ── 防御系数（6.4.2）──────────────────────────────────────


def calc_defense(ctx: DamageContext, attacker_to_defender: bool = True) -> float:
    """计算防御系数。

    Args:
        ctx: 伤害上下文
        attacker_to_defender: True=角色攻击敌人，False=敌人攻击角色
    """
    dctx = ctx.defense_ctx
    if dctx is None:
        return 1.0  # 无防御上下文，视为无减免

    if attacker_to_defender:
        # 角色攻击敌人
        atk_level = min(dctx.attacker_level, 100)  # 敌人等级超过 100 按 100
        if dctx.is_piggy:
            def_factor = 1.5 * dctx.defender_level + 30
        else:
            def_factor = dctx.defender_level + 20
        reduction = dctx.def_ignore + dctx.def_reduce
        return (atk_level + 20) / ((atk_level + 20) + def_factor * (1 - reduction))
    else:
        # 敌人攻击角色
        enemy_level = min(dctx.attacker_level, 100)
        denom = 10 * enemy_level + 200 + dctx.defender_defense
        return (10 * enemy_level + 200) / denom


# ── 减伤乘区（多个减伤乘算，下限 1%）─────────────────────


def calc_damage_reduction(ctx: DamageContext) -> float:
    """计算减伤乘区。

    多个减伤为乘算，所有减伤乘算后不低于 1%。
    未击破时必定带有 10% 减伤。
    """
    reductions = list(ctx.damage_reductions)
    if not ctx.is_broken:
        reductions.append(UNBROKEN_DAMAGE_REDUCTION)
    if not reductions:
        return 1.0
    result = 1.0
    for r in reductions:
        result *= (1 - r)
    # 下限保护：不低于 1%
    return max(DAMAGE_REDUCTION_FLOOR, result)


# ── 暴击区 ────────────────────────────────────────────────


def calc_crit_zone(ctx: DamageContext, is_dot: bool = False) -> float:
    """计算暴击区。

    常规/欢愉伤害：暴击时取暴击伤害，否则 1
    持续伤害：默认 1（极少数效果可提供持续伤害暴击区，此处简化）
    """
    if is_dot:
        return 1.0  # 持续伤害默认不暴击
    if ctx.is_crit:
        return 1 + ctx.crit_dmg
    return 1.0


def calc_crit_expectation(ctx: DamageContext, is_dot: bool = False) -> float:
    """计算暴击期望乘区（用于期望伤害，而非单次）。"""
    if is_dot:
        return 1.0
    return 1 + ctx.crit_rate * ctx.crit_dmg


# ── 笑点区 / 好活当赏区（6.4.7）──────────────────────────


def calc_laugh_zone(value: float) -> float:
    """笑点区 = 1 + 笑点 × 5 / (笑点 + 240)"""
    if value <= 0:
        return 1.0
    return 1 + value * 5 / (value + 240)


# ── 6 类伤害计算 ─────────────────────────────────────────


def calc_normal_damage(ctx: DamageContext) -> float:
    """6.4.3 常规伤害。

    最终伤害 = 基础值 × 特殊独立乘区
             × (1 + 增伤%) × (1 + 易伤%) × (1 - 虚弱%)
             × 减伤乘区
             × 抗性系数 × 防御系数 × 暴击区

    增伤取自攻击者面板（attacker_stats.dmg_bonus），
    如需技能独立的增伤可叠加到 ctx.dmg_bonus。
    """
    base = ctx.base_value * ctx.special_multiplier
    dmg_zone = 1 + ctx.attacker_stats.dmg_bonus + ctx.dmg_bonus
    vuln_zone = 1 + ctx.vulnerability
    weak_zone = 1 - ctx.weakness
    reduction = calc_damage_reduction(ctx)
    res = calc_resistance(ctx)
    defense = calc_defense(ctx, attacker_to_defender=True)
    crit = calc_crit_zone(ctx)
    return base * dmg_zone * vuln_zone * weak_zone * reduction * res * defense * crit


def calc_break_damage(ctx: DamageContext) -> float:
    """6.4.4 击破伤害。

    击破伤害 = 击破基础值 × 属性倍率 × 特殊独立乘区
             × (1 + 易伤%)
             × (1 + 击破特攻%) × (1 + 击破增伤%)
             × 减伤乘区
             × 抗性系数 × 防御系数

    击破基础值 = 3767.55 × (韧性上限 / 40 + 0.5)
    """
    break_base = BREAK_BASE_COEFF * (ctx.toughness_max / 40 + 0.5)
    element_mult = BREAK_ELEMENT_MULTIPLIER.get(ctx.element, 1.0)
    base = break_base * element_mult * ctx.special_multiplier
    vuln_zone = 1 + ctx.vulnerability
    # 击破特攻取自攻击者面板 + ctx 显式叠加
    be_zone = 1 + ctx.attacker_stats.break_effect + ctx.break_effect
    break_bonus_zone = 1 + ctx.break_dmg_bonus
    reduction = calc_damage_reduction(ctx)
    res = calc_resistance(ctx)
    defense = calc_defense(ctx, attacker_to_defender=True)
    return base * vuln_zone * be_zone * break_bonus_zone * reduction * res * defense


def calc_super_break_damage(ctx: DamageContext) -> float:
    """6.4.5 超击破伤害。

    超击破伤害 = 超击破基础值 × 超击破倍率 × 特殊独立乘区
               × (1 + 易伤%)
               × (1 + 击破特攻%) × (1 + 击破增伤%)
               × 减伤乘区
               × 抗性系数 × 防御系数

    超击破基础值 = 3767.55 × 实际削韧值 / 10
    """
    super_break_base = BREAK_BASE_COEFF * ctx.actual_toughness_reduced / 10
    base = super_break_base * ctx.super_break_multiplier * ctx.special_multiplier
    vuln_zone = 1 + ctx.vulnerability
    # 击破特攻取自攻击者面板 + ctx 显式叠加
    be_zone = 1 + ctx.attacker_stats.break_effect + ctx.break_effect
    break_bonus_zone = 1 + ctx.break_dmg_bonus
    reduction = calc_damage_reduction(ctx)
    res = calc_resistance(ctx)
    defense = calc_defense(ctx, attacker_to_defender=True)
    return base * vuln_zone * be_zone * break_bonus_zone * reduction * res * defense


def calc_dot_damage(ctx: DamageContext) -> float:
    """6.4.6 持续伤害。

    持续伤害 = 基础值 × 特殊独立乘区
             × (1 + 增伤%) × (1 + 易伤%) × (1 - 虚弱%)
             × 减伤乘区
             × 抗性系数 × 防御系数 × 持续伤害暴击区

    与常规伤害的唯一区别：暴击区被替换为持续伤害暴击区（默认 1）。
    """
    base = ctx.base_value * ctx.special_multiplier
    dmg_zone = 1 + ctx.attacker_stats.dmg_bonus + ctx.dmg_bonus
    vuln_zone = 1 + ctx.vulnerability
    weak_zone = 1 - ctx.weakness
    reduction = calc_damage_reduction(ctx)
    res = calc_resistance(ctx)
    defense = calc_defense(ctx, attacker_to_defender=True)
    crit = calc_crit_zone(ctx, is_dot=True)
    return base * dmg_zone * vuln_zone * weak_zone * reduction * res * defense * crit


def calc_elation_damage(ctx: DamageContext) -> float:
    """6.4.7 欢愉伤害。

    欢愉伤害 = 欢愉倍率 × 基础值 × 特殊独立乘区
             × (1 + 欢愉度%) × (1 + 增笑%)
             × (笑点区 或 好活当赏区)
             × (1 + 易伤%)
             × 减伤乘区
             × 抗性系数 × 防御系数 × 暴击区

    基础值与角色等级相关，80 级固定 7535.107。
    欢愉技用笑点区，其余欢愉伤害用好活当赏区。
    """
    stats = ctx.attacker_stats
    base = ctx.elation_multiplier * ctx.base_value * ctx.special_multiplier
    elation_zone = 1 + stats.elation_dmg
    laugh_bonus_zone = 1 + stats.laugh_bonus
    # 欢愉技用笑点，其余用好活当赏
    if ctx.is_elation_skill:
        laugh_zone = calc_laugh_zone(stats.laugh_point)
    else:
        laugh_zone = calc_laugh_zone(stats.good_joke)
    vuln_zone = 1 + ctx.vulnerability
    reduction = calc_damage_reduction(ctx)
    res = calc_resistance(ctx)
    defense = calc_defense(ctx, attacker_to_defender=True)
    crit = calc_crit_zone(ctx)
    return base * elation_zone * laugh_bonus_zone * laugh_zone * vuln_zone * reduction * res * defense * crit


# ── 统一入口 ──────────────────────────────────────────────


def calculate_damage(ctx: DamageContext) -> float:
    """统一伤害计算入口，按 damage_type 分发。"""
    if ctx.damage_type == DamageType.NORMAL:
        return calc_normal_damage(ctx)
    if ctx.damage_type == DamageType.BREAK:
        return calc_break_damage(ctx)
    if ctx.damage_type == DamageType.SUPER_BREAK:
        return calc_super_break_damage(ctx)
    if ctx.damage_type == DamageType.DOT:
        return calc_dot_damage(ctx)
    if ctx.damage_type == DamageType.ELATION:
        return calc_elation_damage(ctx)
    if ctx.damage_type == DamageType.TRUE:
        # 真实伤害：只取基础值，不吃防御/抗性/增伤/暴击
        return max(0.0, ctx.base_value)
    raise ValueError(f"未知伤害类型: {ctx.damage_type}")
