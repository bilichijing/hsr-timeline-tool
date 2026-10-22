"""Web 会话状态与业务操作（不依赖 PySide6）。

与桌面端（`src/ui/battle_simulator.py`）保持同一套数值口径：

- 面板：`compute_panel_breakdown()` → `apply_lightcone_panel_bonus()`
  → `apply_relic_set_panel_bonus()`（= 桌面端 `_apply_row_panel()`）；
- 战斗：`build_character_unit()` / `make_preset_character()`，白字 / 绿字拆分
  与「表格面板值反解 flat」逻辑与桌面端 `_collect_config()` 一致；
- 交互模拟：`advance_av()` / `step()` / `execute_ultra()` / `snapshot()-restore()`
  的调用顺序与桌面端 `_interactive_*` 一致。
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from src.api.client import (
    fetch_character_detail,
    fetch_lightcone_detail,
    fetch_relicset_detail,
)
from src.api.consts import ELEMENT_MAP
from src.api.transforms import (
    clean_text,
    pick_lightcone_stats80,
    transform_character_detail,
    transform_lightcone_detail,
)
from src.core.character_factory import build_character_unit, make_preset_character
from src.core.damage import build_enemy_resistance
from src.core.freesr import (
    apply_lightcone_panel_bonus,
    apply_relic_set_panel_bonus,
    compute_panel_breakdown,
    parse_freesr,
    parse_relic,
)
from src.core.simulator import (
    BattleEndReason,
    BattleResult,
    BattleSimulator,
    EnemyAttack,
    EnemyState,
    PlayerAction,
)
from src.core.skill import SkillType

# 反查表：属性中文 → 英文（弱点输入用）
ELEMENT_MAP_ZH_TO_EN: dict[str, str] = {v: k for k, v in ELEMENT_MAP.items()}

STATE_PATH = Path("./cache/web_state.json")

ROW_COUNT = 4

# 面板字段（顺序即前端展示顺序）
PANEL_KEYS: tuple[str, ...] = (
    "hp", "atk", "def", "spd",
    "crit_rate", "crit_dmg", "break_effect", "effect_res",
    "energy_regen", "effect_hit", "outgoing_heal", "dmg_bonus",
)
PANEL_LABELS: dict[str, str] = {
    "hp": "生命值", "atk": "攻击力", "def": "防御力", "spd": "速度",
    "crit_rate": "暴击率", "crit_dmg": "暴击伤害", "break_effect": "击破特攻",
    "effect_res": "效果抵抗", "energy_regen": "能量恢复效率",
    "effect_hit": "效果命中", "outgoing_heal": "治疗量加成", "dmg_bonus": "属性增伤",
}
PERCENT_KEYS = frozenset({
    "crit_rate", "crit_dmg", "break_effect", "effect_res",
    "energy_regen", "effect_hit", "outgoing_heal", "dmg_bonus",
})
INT_KEYS = frozenset({"hp", "atk", "def"})

DEFAULT_PANEL: dict[str, float] = {
    "hp": 10000, "atk": 1000, "def": 500, "spd": 100,
    "crit_rate": 0.05, "crit_dmg": 0.5, "break_effect": 0.0, "effect_res": 0.0,
    "energy_regen": 0.0, "effect_hit": 0.0, "outgoing_heal": 0.0, "dmg_bonus": 0.0,
}

DEFAULT_ENEMY: dict[str, Any] = {
    "count": 1, "toughness": 60, "hp": 100000,
    "weakness": "火, 冰", "level": 80, "non_weak_resist": 20,
}
DEFAULT_BATTLE: dict[str, Any] = {"initial_sp": 3, "max_av": 300, "action_mode": 0}
DEFAULT_SKILL_LEVELS: dict[str, int] = {
    "normal": 1, "skill": 1, "ultra": 1, "talent": 1, "memo": 1, "elation": 1,
}


class WebError(Exception):
    """业务错误：由 HTTP 层转成 400 + 中文提示。"""


# ── 队伍行 ────────────────────────────────────────────────


@dataclass
class Row:
    """一支队伍中的一行（角色 + 装备 + 面板值）。"""

    name: str = ""
    char_id: str = ""
    path: str = ""
    element: str = ""
    sp_need: int = 0
    stats80: dict = field(default_factory=dict)
    skills_raw: dict = field(default_factory=dict)
    skill_trees_raw: dict = field(default_factory=dict)
    ranks_raw: dict = field(default_factory=dict)
    memosprite_raw: dict = field(default_factory=dict)
    loaded: bool = False
    sp_value: float = 0.0
    rank: int = 0
    lightcone_id: str = ""
    lightcone_name: str = ""
    lightcone_rank: int = 1
    lightcone_params: list = field(default_factory=list)
    lightcone_desc: str = ""
    lightcone_stats80: dict = field(default_factory=dict)
    relics: list = field(default_factory=list)          # 原始 freesr 风格遗器 dict
    relic_set_counts: dict = field(default_factory=dict)
    relic_set_effects: dict = field(default_factory=dict)
    relic_set_names: dict = field(default_factory=dict)
    panel_white_base: dict = field(default_factory=dict)
    panel_green_bonus: dict = field(default_factory=dict)
    cells: dict = field(default_factory=dict)           # 面板数值（见 PANEL_KEYS）

    def __post_init__(self) -> None:
        """补全面板默认值（空行也能显示/编辑面板）。"""
        for key, default in DEFAULT_PANEL.items():
            self.cells.setdefault(key, default)

    def reset_character(self) -> None:
        """清空角色相关数据（保留装备）。"""
        self.name = ""
        self.char_id = ""
        self.path = ""
        self.element = ""
        self.sp_need = 0
        self.stats80 = {}
        self.skills_raw = {}
        self.skill_trees_raw = {}
        self.ranks_raw = {}
        self.memosprite_raw = {}
        self.loaded = False
        self.sp_value = 0.0
        self.rank = 0
        self.panel_white_base = {}
        self.panel_green_bonus = {}

    def to_dict(self) -> dict:
        data = {}
        for key, value in self.__dict__.items():
            data[key] = value
        return data

    @classmethod
    def from_dict(cls, data: dict) -> Row:
        row = cls()
        for key, value in (data or {}).items():
            if hasattr(row, key):
                setattr(row, key, value)
        # 面板值缺失时补默认（旧存档 / 空行）
        for key, default in DEFAULT_PANEL.items():
            row.cells.setdefault(key, default)
        return row


# ── 会话 ──────────────────────────────────────────────────


class Session:
    """单用户会话：队伍配置 + 交互模拟 + 最近一次结果。"""

    def __init__(self) -> None:
        self.rows: list[Row] = [Row() for _ in range(ROW_COUNT)]
        self.config: dict = self.default_config()
        # 交互模拟
        self.sim: BattleSimulator | None = None
        self.sim_active: bool = False
        self.snapshots: list[dict] = []
        self.old_logs: list = []
        self.selected_target: str = ""
        # 最近一次完整模拟结果
        self.result: BattleResult | None = None
        self.result_chars: list = []
        self.result_enemies: list = []
        # 最近一次操作的提示（警告 / 拒绝原因）
        self.message: str = ""
        self.load()

    # ── 配置默认值 / 持久化 ───────────────────────────

    @staticmethod
    def default_config() -> dict:
        return {
            "enemy": dict(DEFAULT_ENEMY),
            "battle": dict(DEFAULT_BATTLE),
            "skill_levels": dict(DEFAULT_SKILL_LEVELS),
            "enemy_attacks": [],
        }

    def reset(self) -> None:
        """重置为空白队伍（保留已保存的配置默认值）。"""
        self.rows = [Row() for _ in range(ROW_COUNT)]
        self.config = self.default_config()
        self.sim = None
        self.sim_active = False
        self.snapshots = []
        self.old_logs = []
        self.result = None
        self.result_chars = []
        self.result_enemies = []
        self.message = ""
        self.save()

    def load(self) -> None:
        """读取缓存配置（不存在 / 损坏时保持默认）。"""
        try:
            raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict):
            return
        rows = raw.get("rows")
        if isinstance(rows, list):
            for i, item in enumerate(rows[:ROW_COUNT]):
                self.rows[i] = Row.from_dict(item)
        cfg = raw.get("config")
        if isinstance(cfg, dict):
            for section, defaults in (
                ("enemy", DEFAULT_ENEMY), ("battle", DEFAULT_BATTLE),
                ("skill_levels", DEFAULT_SKILL_LEVELS),
            ):
                value = cfg.get(section)
                if isinstance(value, dict):
                    merged = dict(defaults)
                    merged.update(value)
                    self.config[section] = merged
            attacks = cfg.get("enemy_attacks")
            if isinstance(attacks, list):
                self.config["enemy_attacks"] = [a for a in attacks if isinstance(a, dict)]

    def save(self) -> None:
        """写缓存（失败不影响使用）。"""
        data = {
            "version": 1,
            "rows": [row.to_dict() for row in self.rows],
            "config": self.config,
        }
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATE_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8",
            )
        except OSError:
            pass

    # ── 行访问 ────────────────────────────────────────

    def row(self, index: int) -> Row:
        if not 0 <= index < ROW_COUNT:
            raise WebError(f"行号越界: {index}")
        return self.rows[index]

    def filled_rows(self) -> list[tuple[int, Row]]:
        """已配置角色的行（与桌面端"名称非空"判定一致）。"""
        return [(i, row) for i, row in enumerate(self.rows) if row.name.strip()]

    # ── 面板计算 ──────────────────────────────────────

    def apply_panel(self, row: Row) -> None:
        """按角色基础 + 行迹 + 遗器 + 光锥（+2 件套无条件属性）重算面板。"""
        if not row.stats80:
            return
        relics = [parse_relic(r) for r in row.relics if isinstance(r, dict)]
        white_base, green_bonus, _final = compute_panel_breakdown(
            row.stats80, relics, row.lightcone_stats80 or None, row.skill_trees_raw,
        )
        final = apply_lightcone_panel_bonus(
            white_base, green_bonus, row.lightcone_id, row.lightcone_params,
        )
        final = apply_relic_set_panel_bonus(
            white_base, green_bonus, row.relic_set_counts, row.relic_set_effects,
        )
        row.panel_white_base = {
            "hp": white_base.hp_base,
            "atk": white_base.atk_base,
            "def": white_base.def_base,
            "spd": white_base.spd_base,
        }
        row.panel_green_bonus = asdict(green_bonus)
        row.cells = {
            "hp": int(final.hp),
            "atk": int(final.atk),
            "def": int(final.defense),
            "spd": round(final.spd, 1),
            "crit_rate": final.crit_rate,
            "crit_dmg": final.crit_dmg,
            "break_effect": final.break_effect,
            "effect_res": final.effect_res,
            "energy_regen": final.energy_regen,
            "effect_hit": final.effect_hit,
            "outgoing_heal": final.outgoing_heal,
            "dmg_bonus": final.dmg_bonus,
        }

    # ── 队伍编辑 ──────────────────────────────────────

    def set_name(self, index: int, name: str) -> None:
        self.row(index).name = (name or "").strip()

    def set_rank(self, index: int, rank: int) -> None:
        row = self.row(index)
        row.rank = max(0, min(6, int(rank)))

    def set_panel(self, index: int, values: dict) -> None:
        """手动修改面板数值（不重算，直接覆盖）。"""
        row = self.row(index)
        for key in PANEL_KEYS:
            if key not in values:
                continue
            try:
                value = float(values[key])
            except (TypeError, ValueError):
                continue
            row.cells[key] = int(value) if key in INT_KEYS else round(value, 4)

    async def set_character(self, index: int, char_id: str | int) -> None:
        """选择角色：拉取详情并重算面板（保留光锥与遗器）。"""
        row = self.row(index)
        char_id = str(char_id)
        detail = await fetch_character_detail(char_id)
        info = transform_character_detail(detail, char_id)
        stats80: dict = {}
        if info.stats:
            key = "6" if "6" in info.stats else max(info.stats, key=lambda k: int(k))
            stats80 = info.stats[key].model_dump()
        row.char_id = char_id
        row.name = info.name or row.name
        row.path = info.path
        row.element = info.element
        row.sp_need = info.sp_need
        row.stats80 = stats80
        row.skills_raw = info.skills
        row.skill_trees_raw = info.skill_trees
        row.ranks_raw = info.ranks
        row.memosprite_raw = info.memosprite
        row.loaded = True
        row.rank = 0
        row.sp_value = 0.0
        self.apply_panel(row)

    async def set_lightcone(
        self, index: int, lightcone_id: str | int | None = None,
        rank: int = 1, clear: bool = False,
    ) -> None:
        """选择 / 清除光锥（含叠影）。"""
        row = self.row(index)
        if clear or not lightcone_id:
            row.lightcone_id = ""
            row.lightcone_name = ""
            row.lightcone_rank = 1
            row.lightcone_params = []
            row.lightcone_desc = ""
            row.lightcone_stats80 = {}
        else:
            lightcone_id = str(lightcone_id)
            detail = await fetch_lightcone_detail(lightcone_id)
            info = transform_lightcone_detail(detail, lightcone_id)
            refinement = info.refinement
            row.lightcone_id = lightcone_id
            row.lightcone_name = info.name
            row.lightcone_rank = max(1, min(5, int(rank or 1)))
            levels = refinement.levels if refinement is not None else {}
            row.lightcone_params = list(levels.get(str(row.lightcone_rank), []))
            desc = clean_text(
                refinement.desc if refinement is not None else "",
                row.lightcone_params,
            )
            ref_name = refinement.name if refinement is not None else ""
            row.lightcone_desc = f"{ref_name}：{desc}" if desc and ref_name else desc
            row.lightcone_stats80 = pick_lightcone_stats80(info)
        self.apply_panel(row)

    async def set_relics(self, index: int, relics: list[dict]) -> None:
        """设置 6 部位遗器（freesr 风格 dict），并拉取缺失的套装效果。"""
        row = self.row(index)
        parsed = [parse_relic(r) for r in relics if isinstance(r, dict)]
        row.relics = [item.raw for item in parsed]
        counts: dict[str, int] = {}
        for item in parsed:
            key = str(item.relic_set_id)
            counts[key] = counts.get(key, 0) + 1
        row.relic_set_counts = counts
        # 清理不再使用的套装
        row.relic_set_effects = {
            k: v for k, v in row.relic_set_effects.items() if k in counts
        }
        row.relic_set_names = {
            k: v for k, v in row.relic_set_names.items() if k in counts
        }
        for set_id in counts:
            if set_id in row.relic_set_effects and set_id in row.relic_set_names:
                continue
            try:
                raw = await fetch_relicset_detail(set_id)
            except Exception:
                continue
            require_num = raw.get("require_num") or {}
            row.relic_set_effects[set_id] = {
                str(pieces): list(item.get("param_list") or [])
                for pieces, item in require_num.items()
                if isinstance(item, dict)
            }
            row.relic_set_names[set_id] = raw.get("name", "")
        self.apply_panel(row)

    async def import_freesr(self, data: dict) -> dict:
        """导入 freesr-data.json（按 char_id 匹配队伍行）。"""
        try:
            profile = parse_freesr(data)
        except Exception as e:  # noqa: BLE001
            raise WebError(f"解析 freesr-data.json 失败: {e}") from e
        if not profile.avatars:
            raise WebError("文件中没有已配置的角色（无有效数据）")

        by_char = {row.char_id: i for i, row in enumerate(self.rows) if row.char_id}
        matched: list[tuple[int, str]] = []
        unmatched: list[str] = []
        for char_id, avatar in profile.avatars.items():
            index = by_char.get(char_id)
            if index is None:
                unmatched.append(char_id)
                continue
            row = self.rows[index]
            row.sp_value = float(avatar.sp_value or 0)
            row.rank = max(0, min(6, int(avatar.rank)))
            if avatar.sp_max > 0 and not row.sp_need:
                row.sp_need = int(avatar.sp_max)
            row.relic_set_effects = {}
            row.relic_set_names = {}
            levels = avatar.skill_levels
            for key, skill_type in (
                ("normal", SkillType.NORMAL), ("skill", SkillType.SKILL),
                ("ultra", SkillType.ULTRA), ("talent", SkillType.TALENT),
            ):
                if skill_type in levels:
                    self.config["skill_levels"][key] = int(levels[skill_type])
            matched.append((index, char_id))

        for index, char_id in matched:
            relcs = profile.relics.get(char_id, [])
            await self.set_relics(index, [r.raw for r in relcs])
            lcs = profile.lightcones.get(char_id, [])
            if lcs:
                await self.set_lightcone(index, lcs[0].item_id, int(lcs[0].rank))
            else:
                await self.set_lightcone(index, clear=True)

        self.save()
        return {
            "matched": len(matched),
            "unmatched": unmatched,
            "rows": [i + 1 for i, _ in matched],
        }

    # ── 战斗构造 ──────────────────────────────────────

    def build_characters(self) -> tuple[list, list[str]]:
        """构造 CharacterUnit 列表（与桌面端 `_collect_config` 同口径）。"""
        warnings: list[str] = []
        levels = self.config["skill_levels"]
        skill_levels = {
            SkillType.NORMAL: int(levels["normal"]),
            SkillType.SKILL: int(levels["skill"]),
            SkillType.ULTRA: int(levels["ultra"]),
            SkillType.TALENT: int(levels["talent"]),
            SkillType.MEMO_DNSKILL: int(levels["memo"]),
        }
        characters = []
        for index, row in self.filled_rows():
            uid = f"char{index + 1}"
            cells = row.cells or {}
            if row.loaded and row.skills_raw:
                char = build_character_unit(
                    unit_id=uid,
                    name=row.name,
                    path=row.path or "Knight",
                    element=row.element or "Fire",
                    stats80=row.stats80,
                    skills_raw=row.skills_raw,
                    sp_need=row.sp_need,
                    skill_levels=skill_levels,
                    elation_skill_level=int(levels["elation"]),
                    char_id=row.char_id,
                    dmg_bonus=float(cells.get("dmg_bonus", 0.0)),
                    initial_energy=row.sp_value,
                    skill_trees_raw=None,
                    rank=row.rank,
                    ranks_raw=row.ranks_raw,
                    memo_skill_level=int(levels["memo"]),
                    memosprite_raw=row.memosprite_raw,
                    lightcone_id=row.lightcone_id,
                    lightcone_rank=row.lightcone_rank,
                    lightcone_params=row.lightcone_params,
                    lightcone_name=row.lightcone_name,
                    relic_set_counts=row.relic_set_counts,
                    relic_set_effects=row.relic_set_effects,
                )
                char.skill_trees_raw = row.skill_trees_raw or {}
                white = row.panel_white_base or {}
                green = row.panel_green_bonus or {}
                if white:
                    char.base_stats.hp_base = float(white.get("hp", char.base_stats.hp_base))
                    char.base_stats.atk_base = float(white.get("atk", char.base_stats.atk_base))
                    char.base_stats.def_base = float(white.get("def", char.base_stats.def_base))
                    char.base_stats.spd_base = float(white.get("spd", char.base_stats.spd_base))
                    char.bonus_stats.hp_pct = float(green.get("hp_pct", 0.0))
                    char.bonus_stats.hp_flat = float(green.get("hp_flat", 0.0))
                    char.bonus_stats.atk_pct = float(green.get("atk_pct", 0.0))
                    char.bonus_stats.atk_flat = float(green.get("atk_flat", 0.0))
                    char.bonus_stats.def_pct = float(green.get("def_pct", 0.0))
                    char.bonus_stats.def_flat = float(green.get("def_flat", 0.0))
                    char.bonus_stats.spd_pct = float(green.get("spd_pct", 0.0))
                    char.bonus_stats.spd_flat = float(green.get("spd_flat", 0.0))

                    def _sync_flat(base_attr: str, pct_attr: str, flat_attr: str,
                                   target: float) -> None:
                        base = getattr(char.base_stats, base_attr)
                        pct = getattr(char.bonus_stats, pct_attr)
                        flat = getattr(char.bonus_stats, flat_attr)
                        current = base * (1 + pct) + flat
                        setattr(char.bonus_stats, flat_attr, flat + target - current)

                    _sync_flat("hp_base", "hp_pct", "hp_flat",
                               float(cells.get("hp", char.final_stats().hp)))
                    _sync_flat("atk_base", "atk_pct", "atk_flat",
                               float(cells.get("atk", char.final_stats().atk)))
                    _sync_flat("def_base", "def_pct", "def_flat",
                               float(cells.get("def", char.final_stats().defense)))
                    _sync_flat("spd_base", "spd_pct", "spd_flat",
                               float(cells.get("spd", char.final_stats().spd)))
                else:
                    char.base_stats.hp_base = float(cells.get("hp", char.base_stats.hp_base))
                    char.base_stats.atk_base = float(cells.get("atk", char.base_stats.atk_base))
                    char.base_stats.def_base = float(cells.get("def", char.base_stats.def_base))
                    char.base_stats.spd_base = float(cells.get("spd", char.base_stats.spd_base))

                # 面板绿字里没有对应表格列的字段直接带进战斗
                if green:
                    char.bonus_stats.elemental_dmg_bonus = dict(
                        green.get("elemental_dmg_bonus") or {}
                    )
                    char.bonus_stats.follow_up_dmg_bonus = float(
                        green.get("follow_up_dmg_bonus", 0.0) or 0.0
                    )
                    char.bonus_stats.follow_up_crit_dmg_bonus = float(
                        green.get("follow_up_crit_dmg_bonus", 0.0) or 0.0
                    )

                char.base_stats.crit_rate = float(cells.get("crit_rate", char.base_stats.crit_rate))
                char.base_stats.crit_dmg = float(cells.get("crit_dmg", char.base_stats.crit_dmg))
                char.base_stats.break_effect = float(cells.get("break_effect", 0.0))
                char.base_stats.effect_res = float(cells.get("effect_res", 0.0))
                char.base_stats.energy_regen = float(cells.get("energy_regen", 0.0))
                char.base_stats.effect_hit = float(cells.get("effect_hit", 0.0))
                char.base_stats.outgoing_heal = float(cells.get("outgoing_heal", 0.0))
                characters.append(char)
                continue

            # 预设角色（未接入真实详情 / 纯手工面板）
            char = make_preset_character(
                uid, row.name, row.path or "Knight", row.element or "Fire",
                hp=float(cells.get("hp", 10000)),
                atk=float(cells.get("atk", 1000)),
                def_=float(cells.get("def", 500)),
                spd=float(cells.get("spd", 100)),
                crit_rate=float(cells.get("crit_rate", 0.05)),
                crit_dmg=float(cells.get("crit_dmg", 0.5)),
                break_effect=float(cells.get("break_effect", 0.0)),
                effect_res=float(cells.get("effect_res", 0.0)),
                energy_regen=float(cells.get("energy_regen", 0.0)),
                effect_hit=float(cells.get("effect_hit", 0.0)),
                outgoing_heal=float(cells.get("outgoing_heal", 0.0)),
                dmg_bonus=float(cells.get("dmg_bonus", 0.0)),
            )
            if row.char_id:
                char.char_id = row.char_id
                warnings.append(f"{row.name}：真实数据未就绪，使用预设技能")
            char.rank = row.rank
            char.ranks_raw = row.ranks_raw
            char.memosprite_raw = dict(row.memosprite_raw or {})
            char.memo_skill_level = max(1, min(10, int(levels["memo"])))
            char.lightcone_id = row.lightcone_id
            char.lightcone_rank = row.lightcone_rank
            char.lightcone_params = list(row.lightcone_params or [])
            char.lightcone_name = row.lightcone_name
            char.relic_set_counts = dict(row.relic_set_counts or {})
            char.relic_set_effects = dict(row.relic_set_effects or {})
            characters.append(char)
        return characters, warnings

    def build_enemies(self) -> list[EnemyState]:
        cfg = self.config["enemy"]
        weaknesses_zh = [w.strip() for w in str(cfg.get("weakness", "")).split(",") if w.strip()]
        weaknesses = [ELEMENT_MAP_ZH_TO_EN.get(w, w) for w in weaknesses_zh]
        resistance = build_enemy_resistance(
            weaknesses, float(cfg.get("non_weak_resist", 20)) / 100.0,
        )
        count = max(1, min(5, int(cfg.get("count", 1))))
        toughness = float(cfg.get("toughness", 60))
        return [
            EnemyState(
                unit_id=f"enemy{i + 1}",
                name="木桩",
                max_toughness=toughness,
                current_toughness=toughness,
                weakness_elements=weaknesses,
                level=int(cfg.get("level", 80)),
                speed=0.0,  # 木桩：不进入行动队列
                resistance=resistance,
                max_hp=float(cfg.get("hp", 100000)),
            )
            for i in range(count)
        ]

    def build_enemy_attacks(self) -> list[EnemyAttack]:
        """敌方攻击调度：UI 目标按队伍槽位，模拟器按已配置角色下标。"""
        configured = [i for i, row in enumerate(self.rows) if row.name.strip()]
        slot_to_index = {slot: idx for idx, slot in enumerate(configured)}
        attacks: list[EnemyAttack] = []
        for item in self.config.get("enemy_attacks", []):
            try:
                total_av = float(item.get("total_av", 0) or 0)
                attack = float(item.get("attack", 0) or 0)
                energy = float(item.get("energy_recover", 0) or 0)
                source = int(item.get("source_enemy_index", 0) or 0)
            except (TypeError, ValueError):
                continue
            raw_targets = item.get("target_indices") or []
            targets = [
                slot_to_index[int(slot)]
                for slot in raw_targets
                if str(slot).isdigit() and int(slot) in slot_to_index
            ]
            attacks.append(EnemyAttack(
                total_av=total_av,
                source_enemy_index=max(0, min(4, source)),
                attack=attack,
                target_indices=targets,
                energy_recover=energy,
            ))
        return attacks

    # ── 一次性模拟 ────────────────────────────────────

    def run(self) -> BattleResult:
        chars, warnings = self.build_characters()
        if not chars:
            raise WebError("至少需要一个角色")
        enemies = self.build_enemies()
        battle = self.config["battle"]
        sim = BattleSimulator(
            characters=chars,
            enemies=enemies,
            max_av=float(battle.get("max_av", 300)),
            initial_sp=int(battle.get("initial_sp", 3)),
            enemy_attacks=self.build_enemy_attacks(),
        )
        sim.setup()
        mode = int(battle.get("action_mode", 0))
        actions: list[PlayerAction] = []
        if mode in (1, 2):
            skill_type = SkillType.NORMAL if mode == 1 else SkillType.SKILL
            target = enemies[0].unit_id if enemies else ""
            actions = [
                PlayerAction(unit_id=c.unit_id, skill_type=skill_type, target_id=target)
                for c in chars
            ]
        result = sim.run(actions=actions or None)
        self.result = result
        self.result_chars = chars
        self.result_enemies = enemies
        self.message = "；".join(warnings)
        return result

    # ── 交互模拟 ──────────────────────────────────────

    def require_sim(self) -> BattleSimulator:
        if self.sim is None:
            raise WebError("尚未开始交互模拟")
        return self.sim

    def start_sim(self) -> None:
        chars, warnings = self.build_characters()
        if not chars:
            raise WebError("至少需要一个角色")
        enemies = self.build_enemies()
        battle = self.config["battle"]
        sim = BattleSimulator(
            characters=chars,
            enemies=enemies,
            max_av=float(battle.get("max_av", 300)),
            initial_sp=int(battle.get("initial_sp", 3)),
            enemy_attacks=self.build_enemy_attacks(),
        )
        sim.setup()
        self.sim = sim
        self.sim_active = True
        self.snapshots = [sim.snapshot()]
        self.old_logs = []
        self.selected_target = enemies[0].unit_id if enemies else ""
        self.result = None
        self.result_chars = []
        self.result_enemies = []
        self.message = "；".join(warnings)

    def select_target(self, unit_id: str) -> None:
        self.selected_target = unit_id or ""

    def _target_id(self, sim: BattleSimulator) -> str:
        if self.selected_target and any(e.unit_id == self.selected_target for e in sim.enemies):
            return self.selected_target
        return sim.enemies[0].unit_id if sim.enemies else ""

    def advance(self) -> None:
        """推进时间；轮到自动单位则自动行动。"""
        sim = self.require_sim()
        if sim.total_av >= sim.max_av or not sim.action_queue.entries:
            return
        actor = sim.action_queue.next_actor()
        if sim.pending_av_actor != actor.unit_id:
            sim.advance_av()
            actor = sim.action_queue.next_actor()
            if sim.is_auto_unit(actor):
                if sim.step() is None:
                    self.sim_active = False
        elif sim.is_auto_unit(actor):
            if sim.step() is None:
                self.sim_active = False
        else:
            self.message = f"已轮到 {actor.name}：请使用普攻（Q）或战技（E）"
            return
        self.snapshots.append(sim.snapshot())
        self.old_logs = []
        self._after_action(sim)

    def act(self, skill_type: str) -> None:
        """当前角色普攻 / 战技。"""
        sim = self.require_sim()
        if sim.total_av >= sim.max_av or not sim.action_queue.entries:
            raise WebError("战斗已结束")
        kind = SkillType.NORMAL if skill_type == "normal" else SkillType.SKILL
        actor = sim.action_queue.next_actor()
        if sim.is_auto_unit(actor):
            raise WebError("当前是自动单位行动，请按「推进」")
        if sim.pending_av_actor != actor.unit_id:
            sim.advance_av()
        char = sim._get_character(actor.unit_id)
        if char is None:
            return
        if kind == SkillType.SKILL:
            module = sim.char_modules.get(char.unit_id)
            if module is not None:
                reason = module.skill_deny_reason(sim, char)
                if reason:
                    raise WebError(reason)
            skill_for_sp = next(
                (s for s in char.skills.values() if s.skill_type == SkillType.SKILL), None,
            )
            if (
                skill_for_sp is not None
                and skill_for_sp.sp_cost > 0
                and not sim.sp.can_consume(1)
            ):
                raise WebError("当前 SP 为 0，无法使用战技")
        action = PlayerAction(
            unit_id=char.unit_id, skill_type=kind, target_id=self._target_id(sim),
        )
        if sim.step(action) is None:
            self.sim_active = False
        self.snapshots.append(sim.snapshot())
        self.old_logs = []
        self._after_action(sim)

    def ultra(self, char_index: int) -> None:
        """终结技插队。"""
        sim = self.require_sim()
        log = sim.execute_ultra(int(char_index), target_id=self._target_id(sim))
        if log is None:
            raise WebError(f"角色 {int(char_index) + 1} 能量不足或无终结技")
        self.snapshots.append(sim.snapshot())
        self.old_logs = []
        self._after_action(sim)

    def rewind(self, log_index: int) -> None:
        """回溯到第 log_index 条日志之前的状态。"""
        sim = self.require_sim()
        index = int(log_index)
        if index < 0 or index >= len(sim.logs):
            raise WebError("请选择有效的回合（不能回溯到已失效的旧记录）")
        if index >= len(self.snapshots):
            raise WebError("该回合没有可用快照")
        self.old_logs = list(sim.logs[index:])
        sim.restore(self.snapshots[index])
        self.snapshots = self.snapshots[: index + 1]
        self.sim_active = True

    def _after_action(self, sim: BattleSimulator) -> None:
        """战斗结束时把交互日志转成结果，填满结果页。"""
        if sim.enemies and sim.total_av < sim.max_av and sim.action_queue.entries:
            return
        self.sim_active = False
        if not sim.enemies:
            end_reason = BattleEndReason.ALL_ENEMIES_DEAD
        elif sim.total_av >= sim.max_av:
            end_reason = BattleEndReason.MAX_AV
        elif not sim.action_queue.entries:
            end_reason = BattleEndReason.NO_ACTIONS
        else:
            end_reason = BattleEndReason.MAX_TURNS
        final_av = 0.0
        if sim.action_queue.entries:
            final_av = sim.action_queue.next_actor().current_av
        self.result = BattleResult(
            logs=list(sim.logs),
            total_damage=sim.total_damage,
            total_turns=sim.current_turn,
            total_av=sim.total_av,
            final_av=final_av,
            end_reason=end_reason,
            aha_count=sim.aha_count,
            final_laugh_point=sum(c.laugh_point for c in sim.characters if c.is_elation),
            final_sp=sim.sp.current,
        )
        self.result_chars = list(sim.characters)
        self.result_enemies = list(sim.enemies)
