"""遗器部位与词条的中文文案。

供桌面端（`src/ui/widgets/relic_config.py`）与 Web 端共用，
避免两处各维护一份词条表。纯数据 + 纯函数，不依赖 UI。
"""

from __future__ import annotations

from typing import Any

from ..freesr import RELIC_MAIN_AFFIXES, RELIC_SUB_AFFIXES

# 部位编号 → 中文名（与 nanoka relic_id 末位一致）
SLOT_NAMES: dict[int, str] = {
    1: "头部",
    2: "手部",
    3: "躯干",
    4: "脚部",
    5: "位面球",
    6: "连结绳",
}

# 每个部位最多 4 条副词条
MAX_SUB_AFFIXES = 4

# 位面球 main_affix_id 4~10 的属性顺序（物理/火/冰/雷/风/量子/虚数）
ORB_ELEMENTS: list[str] = ["物理", "火", "冰", "雷", "风", "量子", "虚数"]

# StatBonus 字段 → 中文名
STAT_LABELS: dict[str, str] = {
    "hp_flat": "生命值",
    "atk_flat": "攻击力",
    "def_flat": "防御力",
    "hp_pct": "生命值%",
    "atk_pct": "攻击力%",
    "def_pct": "防御力%",
    "spd_flat": "速度",
    "crit_rate": "暴击率",
    "crit_dmg": "暴击伤害",
    "outgoing_heal": "治疗量加成",
    "effect_hit": "效果命中",
    "break_effect": "击破特攻",
    "energy_regen": "能量恢复效率",
    "dmg_bonus": "属性伤害提高",
}

# 副词条 id → 中文名
SUB_AFFIX_LABELS: dict[int, str] = {
    1: "生命值",
    2: "攻击力",
    3: "防御力",
    4: "生命值%",
    5: "攻击力%",
    6: "防御力%",
    7: "速度",
    8: "暴击率",
    9: "暴击伤害",
    10: "效果命中",
    11: "效果抵抗",
    12: "击破特攻",
}

# 百分比类字段（显示时加 %）
PCT_FIELDS = frozenset({
    "hp_pct", "atk_pct", "def_pct", "crit_rate", "crit_dmg",
    "break_effect", "effect_hit", "effect_res", "energy_regen",
    "outgoing_heal", "dmg_bonus",
})


def _format_value(field_name: str, value: float) -> str:
    """数值显示：百分比字段加 %，其余按数值原样。"""
    if field_name in PCT_FIELDS:
        return f"{value:g}%"
    return f"{value:g}"


def main_affix_options(slot: int) -> list[tuple[int, str]]:
    """返回某部位可选的 (main_affix_id, 中文标签) 列表。"""
    table = RELIC_MAIN_AFFIXES.get(slot, {})
    options: list[tuple[int, str]] = []
    for main_id in sorted(table):
        field_name, value = table[main_id]
        if slot == 5 and main_id >= 4:
            label = f"{ORB_ELEMENTS[main_id - 4]}属性伤害提高"
        else:
            label = STAT_LABELS.get(field_name, field_name)
        options.append((main_id, f"{label} {_format_value(field_name, value)}"))
    return options


def main_affix_label(slot: int, main_affix_id: int) -> str:
    """某部位主词条的中文标签（含数值）。"""
    for main_id, label in main_affix_options(slot):
        if main_id == main_affix_id:
            return label
    return "—"


def sub_affix_label(sub_affix_id: int) -> str:
    """副词条中文名。"""
    return SUB_AFFIX_LABELS.get(sub_affix_id, "—")


def relic_slot_summary(relic: Any, set_name: str = "") -> str:
    """单件遗器的一句话摘要（tooltip / 明细用）。

    `relic` 为 `FreesrRelic`（鸭子类型：slot / relic_set_id / main_affix_id /
    sub_affixes），避免此模块反向依赖 freesr 的模型定义。
    """
    slot = int(getattr(relic, "slot", 0) or 0)
    slot_name = SLOT_NAMES.get(slot, f"部位{slot}")
    set_id = getattr(relic, "relic_set_id", 0)
    name = set_name or str(set_id)
    main_label = main_affix_label(slot, int(getattr(relic, "main_affix_id", 0) or 0))
    subs = getattr(relic, "sub_affixes", []) or []
    sub_count = len([s for s in subs if s[0] and s[1] > 0])
    text = f"{slot_name}：{name} / {main_label}"
    if sub_count:
        text += f"（副词条 {sub_count} 条）"
    return text


__all__ = [
    "SLOT_NAMES",
    "MAX_SUB_AFFIXES",
    "ORB_ELEMENTS",
    "STAT_LABELS",
    "SUB_AFFIX_LABELS",
    "PCT_FIELDS",
    "main_affix_options",
    "main_affix_label",
    "sub_affix_label",
    "relic_slot_summary",
    "RELIC_MAIN_AFFIXES",
    "RELIC_SUB_AFFIXES",
]
