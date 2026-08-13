"""属性系统。

负责：
- 角色基础属性（HP/ATK/DEF/SPD/暴击率/暴击伤害/效果命中/效果抵抗/击破特攻）
- 属性加成计算（百分比加成 + 固定值加成，遗器主副词条、光锥属性、套装效果叠加）
- 最终面板属性 = 基础 × (1 + 百分比加成) + 固定值加成

属性命名约定（与 buff.stat 字段对齐）：
- hp_pct / hp_flat       生命百分比 / 固定值
- atk_pct / atk_flat     攻击百分比 / 固定值
- def_pct / def_flat     防御百分比 / 固定值
- spd_pct / spd_flat     速度百分比 / 固定值
- crit_rate / crit_dmg   暴击率 / 暴击伤害
- dmg_bonus              伤害加成（属性增伤、通用增伤；暂不区分属性，见字段 TODO）
- break_effect           击破特攻
- effect_hit / effect_res 效果命中 / 效果抵抗
- energy_regen           能量恢复效率（回能乘区）
- outgoing_heal          治疗量加成（待治疗模型接入）

欢愉伤害专属属性（新版本）：
- elation_dmg            欢愉度（欢愉伤害专属增伤）
- laugh_bonus            增笑（欢愉伤害专属增伤）
- laugh_point            笑点（欢愉技专用）
- good_joke              好活当赏（其余欢愉伤害专用）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class BaseStats:
    """角色/光锥/遗器提供的基础属性（不含加成）。

    满级 80 级数据。来自 nanoka 的 stats[level] 表。
    """

    hp_base: float = 0.0
    atk_base: float = 0.0
    def_base: float = 0.0
    spd_base: float = 0.0
    crit_rate: float = 0.05       # 默认 5%
    crit_dmg: float = 0.50        # 默认 50%
    break_effect: float = 0.0
    effect_hit: float = 0.0
    effect_res: float = 0.0
    energy_regen: float = 0.0     # 能量恢复效率（小数，如 0.1944 = +19.44%）
    outgoing_heal: float = 0.0    # 治疗量加成（小数；模拟器暂无治疗模型）
    res_pen: float = 0.0          # 全属性抗性穿透（小数，如 0.12 = +12%）
    energy_max: float = 100.0     # 能量上限
    aggro: float = 100.0          # 仇恨值

    # 欢愉系统属性（默认 0，由特定角色/遗器提供）
    elation_dmg: float = 0.0      # 欢愉度
    laugh_bonus: float = 0.0      # 增笑
    laugh_point: float = 0.0      # 笑点
    good_joke: float = 0.0        # 好活当赏


@dataclass
class StatBonus:
    """属性加成（百分比或固定值）。

    百分比加成已换算为小数（0.2 = +20%）。
    固定值加成为整数（如 +20 攻击力）。
    """

    # 百分比加成（小数）
    hp_pct: float = 0.0
    atk_pct: float = 0.0
    def_pct: float = 0.0
    spd_pct: float = 0.0
    crit_rate: float = 0.0
    crit_dmg: float = 0.0
    dmg_bonus: float = 0.0          # 属性增伤、通用增伤
    # TODO: dmg_bonus 暂为单值不区分属性。UI 只配置角色自身属性增伤一项，
    #       且伤害路径 element 恒等于角色属性，单值足够；引入跨属性增伤时再 dict 化。
    break_effect: float = 0.0
    effect_hit: float = 0.0
    effect_res: float = 0.0
    energy_regen: float = 0.0       # 能量恢复效率（小数）
    outgoing_heal: float = 0.0      # 治疗量加成（小数；模拟器暂无治疗模型）
    res_pen: float = 0.0            # 全属性抗性穿透（小数）

    # 固定值加成
    hp_flat: float = 0.0
    atk_flat: float = 0.0
    def_flat: float = 0.0
    spd_flat: float = 0.0

    # 欢愉系统加成
    elation_dmg: float = 0.0
    laugh_bonus: float = 0.0
    laugh_point: float = 0.0
    good_joke: float = 0.0

    def add(self, other: StatBonus) -> StatBonus:
        """合并两个加成（对应多个 buff 叠加）。"""
        return StatBonus(
            **{
                k: getattr(self, k) + getattr(other, k)
                for k in self.__dataclass_fields__
            }
        )

    def scale(self, factor: float) -> StatBonus:
        """整体缩放（如叠影层级）。"""
        return StatBonus(
            **{k: getattr(self, k) * factor for k in self.__dataclass_fields__}
        )


@dataclass
class FinalStats:
    """最终面板属性（用于伤害计算）。

    公式：final = base × (1 + pct_bonus) + flat_bonus
    """

    hp: float
    atk: float
    defense: float
    spd: float
    crit_rate: float
    crit_dmg: float
    dmg_bonus: float
    break_effect: float
    effect_hit: float
    effect_res: float
    energy_max: float
    aggro: float
    elation_dmg: float
    laugh_bonus: float
    laugh_point: float
    good_joke: float
    energy_regen: float = 0.0      # 能量恢复效率（小数；带默认，避免破坏全关键字构造）
    outgoing_heal: float = 0.0     # 治疗量加成（小数；模拟器暂无治疗模型）
    res_pen: float = 0.0           # 全属性抗性穿透（小数）


@dataclass
class StatCalculator:
    """属性计算器：基础属性 + 加成 → 最终面板。

    用法：
        calc = StatCalculator(base=BaseStats(...), bonus=StatBonus(...))
        final = calc.final()
    """

    base: BaseStats
    bonus: StatBonus = field(default_factory=StatBonus)

    def final(self) -> FinalStats:
        """计算最终面板属性。

        公式：final = base × (1 + pct_bonus) + flat_bonus
        """
        b = self.base
        s = self.bonus
        return FinalStats(
            hp=b.hp_base * (1 + s.hp_pct) + s.hp_flat,
            atk=b.atk_base * (1 + s.atk_pct) + s.atk_flat,
            defense=b.def_base * (1 + s.def_pct) + s.def_flat,
            spd=b.spd_base * (1 + s.spd_pct) + s.spd_flat,
            crit_rate=b.crit_rate + s.crit_rate,
            crit_dmg=b.crit_dmg + s.crit_dmg,
            dmg_bonus=s.dmg_bonus,           # 增伤为独立乘区，不与基础相乘
            break_effect=b.break_effect + s.break_effect,
            effect_hit=b.effect_hit + s.effect_hit,
            effect_res=b.effect_res + s.effect_res,
            energy_regen=b.energy_regen + s.energy_regen,
            outgoing_heal=b.outgoing_heal + s.outgoing_heal,
            res_pen=b.res_pen + s.res_pen,
            energy_max=b.energy_max,
            aggro=b.aggro,
            elation_dmg=b.elation_dmg + s.elation_dmg,
            laugh_bonus=b.laugh_bonus + s.laugh_bonus,
            laugh_point=b.laugh_point + s.laugh_point,
            good_joke=b.good_joke + s.good_joke,
        )


def compute_final_stats(base: BaseStats, *bonuses: StatBonus) -> FinalStats:
    """便捷函数：基础属性 + 多个加成 → 最终面板。"""
    total = StatBonus()
    for b in bonuses:
        total = total.add(b)
    return StatCalculator(base=base, bonus=total).final()
