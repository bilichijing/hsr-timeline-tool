"""战斗模拟器 GUI 主窗口。

精致深色游戏风界面：侧栏 + 主区域 Tab 布局。
- 侧栏：队伍快速概览
- 主区域 Tab：配置 / 行动日志 / AV时间轴 / 伤害占比 / 伤害明细 / 汇总

运行：
    python ui_main.py
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt, QThread, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.api.client import fetch_character_detail, fetch_lightcone_detail, run_in_loop
from src.api.consts import ELEMENT_MAP, PATH_MAP
from src.api.transforms import (
    clean_text,
    pick_lightcone_stats80,
    transform_character_detail,
    transform_lightcone_detail,
)
from src.core.character_factory import (
    GROWTH_STEPS,
    build_character_unit,
    convert_stats80,
    extract_trace_bonuses,
)
from src.core.buff import BuffDuration
from src.core.damage import DamageType, build_enemy_resistance
from src.core.freesr import compute_panel, lightcone_base_stats, parse_freesr
from src.core.stats import StatCalculator
from src.core.simulator import (
    BattleEndReason,
    BattleSimulator,
    BattleResult,
    CharacterUnit,
    EnemyAttack,
    EnemyState,
    PlayerAction,
)
from src.core.skill import Skill, SkillEffect, SkillType
from src.core.stats import BaseStats, StatBonus
from src.ui.theme import DARK_STYLE, Colors, ELEMENT_COLORS, PATH_COLORS
from src.ui.widgets.character_picker import CharacterPickerDialog, ICONS_DIR, _load_character_icon
from src.ui.widgets.damage_pie import DamagePieChartWidget
from src.ui.widgets.enemy_target import EnemyTargetWidget
from src.ui.widgets.sp_indicator import SPIndicatorWidget
from src.ui.widgets.energy_orb import EnergyOrbWidget
from src.ui.widgets.timeline_gantt import (
    GanttAction,
    GanttLane,
    TimelineGanttWidget,
)

# 反向映射：中文 → 英文（用于读取 UI 输入并传给模拟器）
PATH_MAP_ZH_TO_EN: dict[str, str] = {v: k for k, v in PATH_MAP.items()}
ELEMENT_MAP_ZH_TO_EN: dict[str, str] = {v: k for k, v in ELEMENT_MAP.items()}

# 操作类型 → 中文
ACTION_NAMES_ZH: dict[str, str] = {
    "normal": "普攻",
    "skill": "战技",
    "ultra": "终结技",
    "monster": "怪物行动",
    "aha_moment": "阿哈时刻",
    "follow_up": "追加攻击",
    "technique": "秘技",
    "enemy_attack": "敌方攻击",
}


# 配置缓存文件（cache 目录已 gitignore）
CONFIG_PATH = Path("./cache/team_config.json")

# 侧栏行动预览窗口：只展示从当前总行动值起 300 AV 内的行动
PREVIEW_AV_WINDOW = 300.0


# ── 队伍表格行数据与列号 ──────────────────────────────────

# 队伍表格列号（名称/光锥 + 12 项属性；命途/属性存于行数据供角色构建使用）
COL_NAME = 0
COL_LIGHTCONE = 1
COL_HP, COL_ATK, COL_DEF, COL_SPD = 2, 3, 4, 5
COL_CRIT_RATE, COL_CRIT_DMG, COL_BREAK_EFFECT, COL_EFFECT_RES = 6, 7, 8, 9
COL_ENERGY_REGEN, COL_EFFECT_HIT, COL_OUTGOING_HEAL, COL_DMG_BONUS = 10, 11, 12, 13
COL_COUNT = 14

# 百分比列（数值为小数，0.05 = 5%）
PERCENT_COLUMNS = {
    COL_CRIT_RATE, COL_CRIT_DMG, COL_BREAK_EFFECT, COL_EFFECT_RES,
    COL_ENERGY_REGEN, COL_EFFECT_HIT, COL_OUTGOING_HEAL, COL_DMG_BONUS,
}

TABLE_HEADERS = [
    "名称", "光锥",
    "生命值", "攻击力", "防御力", "速度",
    "暴击率", "暴击伤害", "击破特攻", "效果抵抗",
    "能量恢复效率", "效果命中", "治疗量加成", "属性增伤",
]


class _WheelBlocker(QObject):
    """事件过滤器：吞掉滚轮事件，防止数值框/下拉框被误滚改值。"""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Wheel:
            return True
        return super().eventFilter(obj, event)


def _disable_wheel_inputs(root: QWidget) -> None:
    """禁用 root 下所有数值框/下拉框的滚轮改值（防止误操作）。"""
    targets = list(root.findChildren(QAbstractSpinBox))
    targets += list(root.findChildren(QComboBox))
    for widget in targets:
        widget.installEventFilter(_WheelBlocker(widget))


class _EnemyAttackTargetButton(QPushButton):
    """敌方攻击的目标角色选择按钮（下拉多选，显示真实角色名）。

    相比在表格单元格里平铺 4 个勾选框，这个控件占一个单元格，
    通过 QMenu 选择当前队伍中的角色，界面更紧凑、标签更直观。
    """

    SLOT_COUNT = 4

    def __init__(
        self,
        names_provider,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__("未选择", parent)
        self._names_provider = names_provider
        self._selected_indices: set[int] = set()
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(140)
        self.setToolTip("点击选择本次敌方攻击命中的角色（可多选）")
        self.clicked.connect(self._show_menu)
        self.refresh_text()

    # ── 对外接口 ─────────────────────────────────────

    def set_target_indices(self, indices) -> None:
        """设置已选角色槽位（0-3，队伍表行号）。"""
        self._selected_indices.clear()
        for raw in indices or []:
            try:
                index = int(raw)
            except (TypeError, ValueError):
                continue
            if 0 <= index < self.SLOT_COUNT:
                self._selected_indices.add(index)
        self.refresh_text()

    def target_indices(self) -> list[int]:
        """返回已选角色槽位（升序）。"""
        return sorted(self._selected_indices)

    def refresh_text(self) -> None:
        """根据当前队伍名称刷新按钮文本。"""
        names = self._names_provider() if callable(self._names_provider) else []
        selected_names = [
            names[i] for i in self.target_indices()
            if i < len(names) and names[i]
        ]
        configured_count = len([n for n in names if n])
        if configured_count >= 2 and len(selected_names) == configured_count:
            self.setText("全部角色")
        elif selected_names:
            self.setText("、".join(selected_names))
        else:
            self.setText("未选择")

    # ── 内部实现 ─────────────────────────────────────

    def _show_menu(self, *_args) -> None:
        menu = QMenu(self)
        names = self._names_provider() if callable(self._names_provider) else []
        for i in range(self.SLOT_COUNT):
            name = names[i] if i < len(names) and names[i] else ""
            label = f"{i + 1}. {name}" if name else f"{i + 1}. 未配置角色"
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(i in self._selected_indices)
            action.setEnabled(bool(name))
            action.triggered.connect(
                lambda checked, slot=i: self._toggle_slot(slot, checked)
            )
        menu.exec(self.mapToGlobal(self.rect().bottomLeft()))
        self.refresh_text()

    def _toggle_slot(self, index: int, checked: bool) -> None:
        if checked:
            self._selected_indices.add(index)
        else:
            self._selected_indices.discard(index)


@dataclass
class _RowCharData:
    """队伍表格一行的角色数据（存名称列 Qt.UserRole）。"""

    char_id: str = ""
    name: str = ""
    path: str = ""
    element: str = ""
    sp_need: int = 0
    stats80: dict = field(default_factory=dict)   # 详情 stats["6"]
    skills_raw: dict = field(default_factory=dict)
    skill_trees_raw: dict = field(default_factory=dict)  # 原始行迹（行迹属性加成）
    loaded: bool = False                          # 真实详情是否已就绪
    # freesr 导入数据（供未来套装效果/星魂使用）
    sp_value: float = 0.0    # 初始能量（freesr sp_value）
    rank: int = 0            # 星魂（freesr data.rank）
    relics_raw: list = field(default_factory=list)     # freesr 原始遗器列表
    lightcone_raw: list = field(default_factory=list)  # freesr 原始光锥列表
    lightcone_stats80: dict = field(default_factory=dict)  # 光锥 80 级基础（面板基础值显示用）
    lightcone_name: str = ""    # 携带光锥名（freesr 导入后填写）


# ── 角色详情后台加载线程 ──────────────────────────────────


class _CharacterDetailWorker(QObject):
    """后台加载单个角色详情（共享事件循环 run_in_loop）。

    每行独立的一次性线程；diskcache 缓存详情（1h），二次选择秒开。
    """

    loaded = Signal(int, object)   # (row, payload: {sp_need, stats80, skills_raw})
    failed = Signal(int, str)      # (row, error)

    def __init__(self, char_id: str, row: int) -> None:
        super().__init__()
        self.char_id = char_id
        self.row = row

    def run(self) -> None:
        try:
            payload = run_in_loop(self._load())
            self.loaded.emit(self.row, payload)
        except Exception as e:
            self.failed.emit(self.row, str(e))
        finally:
            # 一次性线程：任务完成立即退出线程，触发 finished → 自动回收
            QThread.currentThread().quit()

    async def _load(self) -> dict:
        raw = await fetch_character_detail(self.char_id)
        info = transform_character_detail(raw, self.char_id)
        stats80 = {}
        # stats 键为突破等级 "0"-"6"，优先取 "6"（80 级），缺省取最大键
        if info.stats:
            key = "6" if "6" in info.stats else max(info.stats.keys(), key=lambda k: int(k))
            stats80 = info.stats[key].model_dump()
        return {
            "char_id": self.char_id,
            "sp_need": info.sp_need,
            "stats80": stats80,
            "skills_raw": info.skills,
            "skill_trees_raw": info.skill_trees,
        }


class _FreesrLightconeWorker(QObject):
    """后台加载全部光锥详情（单个一次性线程，diskcache 命中秒回）。"""

    loaded = Signal(object, object)   # ({item_id: {"stats80":..., "name":...}}, [失败 item_id 列表])

    def __init__(self, item_ids: list[int]) -> None:
        super().__init__()
        self.item_ids = item_ids

    def run(self) -> None:
        try:
            rows, failed = run_in_loop(self._load())
            self.loaded.emit(rows, failed)
        except Exception as e:
            self.loaded.emit({}, [str(e)])
        finally:
            QThread.currentThread().quit()

    async def _load(self) -> tuple[dict, list]:
        rows: dict = {}
        failed: list = []
        for item_id in self.item_ids:
            try:
                raw = await fetch_lightcone_detail(item_id)
                info = transform_lightcone_detail(raw, str(item_id))
                rows[item_id] = {
                    "stats80": pick_lightcone_stats80(info),
                    "name": info.name,
                }
            except Exception:
                failed.append(item_id)
        return rows, failed


# ── 预设角色构造 ──────────────────────────────────────────


def make_preset_character(
    unit_id: str,
    name: str,
    path: str,
    element: str,
    hp: float = 10000,
    atk: float = 1000,
    def_: float = 500,
    spd: float = 100,
    crit_rate: float = 0.05,
    crit_dmg: float = 0.5,
    break_effect: float = 0.0,
    effect_hit: float = 0.0,
    effect_res: float = 0.0,
    energy_regen: float = 0.0,
    outgoing_heal: float = 0.0,
    dmg_bonus: float = 0.0,
) -> CharacterUnit:
    """构造预设角色（带普攻/战技/终结技）。"""
    base = BaseStats(
        hp_base=hp,
        atk_base=atk,
        def_base=def_,
        spd_base=spd,
        crit_rate=crit_rate,
        crit_dmg=crit_dmg,
        break_effect=break_effect,
        effect_hit=effect_hit,
        effect_res=effect_res,
        energy_regen=energy_regen,
        outgoing_heal=outgoing_heal,
    )
    bonus = StatBonus(dmg_bonus=dmg_bonus)

    normal = Skill(
        id=f"{unit_id}_normal",
        name="普攻",
        skill_type=SkillType.NORMAL,
        sp_cost=-1,
        energy_recover=20,
        effects=[SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=1.0,
            toughness_damage=10,
            element=element,
        )],
    )
    skill = Skill(
        id=f"{unit_id}_skill",
        name="战技",
        skill_type=SkillType.SKILL,
        sp_cost=1,
        energy_recover=30,
        effects=[SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=2.0,
            toughness_damage=20,
            element=element,
        )],
    )
    ultra = Skill(
        id=f"{unit_id}_ultra",
        name="终结技",
        skill_type=SkillType.ULTRA,
        energy_cost=120,
        effects=[SkillEffect(
            damage_type=DamageType.NORMAL,
            multiplier=4.0,
            toughness_damage=30,
            element=element,
        )],
    )

    # 能量上限与终结技耗能对齐（否则能量永远无法达到耗能要求，放不出终结技）
    base.energy_max = 120

    return CharacterUnit(
        unit_id=unit_id,
        name=name,
        path=path,
        element=element,
        base_stats=base,
        bonus_stats=bonus,
        skills={
            normal.id: normal,
            skill.id: skill,
            ultra.id: ultra,
        },
    )


# ── 卡片样式辅助 ──────────────────────────────────────────


def make_card(title: str, value: str, color: str = Colors.GOLD) -> QFrame:
    """构造一个带强调色描边的数据卡片（标题 + 数值）。"""
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(f"""
        QFrame#card {{
            background: qlineargradient(
                x1: 0, y1: 0, x2: 0, y2: 1,
                stop: 0 {Colors.BG_CARD},
                stop: 1 {Colors.BG_PANEL}
            );
            border: 1px solid {Colors.BORDER};
            border-left: 3px solid {color};
            border-radius: 9px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(14, 10, 12, 10)
    layout.setSpacing(3)

    title_label = QLabel(title)
    title_label.setStyleSheet(
        f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; border: none;"
    )
    value_label = QLabel(value)
    value_label.setStyleSheet(
        f"color: {color}; font-size: 21px; font-weight: 800; border: none;"
    )
    layout.addWidget(title_label)
    layout.addWidget(value_label)
    return card


# ── 主窗口 ────────────────────────────────────────────────


class BattleSimulatorWindow(QMainWindow):
    """战斗模拟器主窗口（深色游戏风）。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("星穹铁道排轴工具 · 战斗模拟器")
        self.resize(1400, 900)

        # 应用级事件过滤器：交互模式下按键无论焦点在哪个控件都被拦截处理
        # （否则焦点在日志表格等控件时 Q/E/空格 会被控件消费）
        QApplication.instance().installEventFilter(self)

        self.characters: list[CharacterUnit] = []
        self.enemies: list[EnemyState] = []
        self._last_result: BattleResult | None = None

        # 交互模式状态
        self._interactive_sim: BattleSimulator | None = None
        self._interactive_snapshots: list[dict] = []
        self._interactive_old_logs: list = []  # 回溯后灰显的旧记录
        self._interactive_active: bool = False
        self._energy_orbs: list[EnergyOrbWidget] = []  # 角色能量图标

        self._init_ui()
        self._load_default_config()
        # 配置缓存：有则自动恢复上次关闭时的全部配置
        self._load_config()
        self._update_action_preview()

    # ── UI 初始化 ─────────────────────────────────────

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 左侧栏
        root.addWidget(self._build_sidebar())

        # 右侧主区域
        root.addWidget(self._build_main_area(), stretch=1)

    def _build_sidebar(self) -> QWidget:
        """左侧栏：品牌头图 + 未来行动预览 + 操作按钮。"""
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(300)
        sidebar.setStyleSheet(
            f"QWidget#sidebar {{ background-color: {Colors.BG_DEEPEST}; }}"
        )
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 18, 16, 14)
        layout.setSpacing(10)

        # ── 品牌头图 ──────────────────────────────────
        header = QFrame()
        header.setObjectName("sidebarHeader")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(14, 12, 14, 12)
        header_layout.setSpacing(3)

        brand = QLabel("✦  星铁排轴工具")
        brand.setObjectName("sidebarBrand")
        header_layout.addWidget(brand)

        sub = QLabel("HONKAI: STAR RAIL · TIMELINE LAB")
        sub.setObjectName("sidebarSub")
        header_layout.addWidget(sub)
        layout.addWidget(header)

        # ── 未来 300 AV 行动预览 ─────────────────────
        preview_panel = QFrame()
        preview_panel.setObjectName("previewPanel")
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(10, 10, 10, 10)
        preview_layout.setSpacing(6)

        preview_title_row = QHBoxLayout()
        preview_title = QLabel("未来 300 AV 行动")
        preview_title.setStyleSheet(
            f"color: {Colors.GOLD}; font-size: 12px; font-weight: 700; border: none;"
        )
        preview_title_row.addWidget(preview_title)
        live_badge = QLabel("实时")
        live_badge.setObjectName("liveBadge")
        live_badge.setAlignment(Qt.AlignCenter)
        preview_title_row.addWidget(live_badge)
        preview_title_row.addStretch()
        preview_layout.addLayout(preview_title_row)

        self.preview_range_label = QLabel("开始交互模拟后显示")
        self.preview_range_label.setObjectName("previewRange")
        preview_layout.addWidget(self.preview_range_label)

        self.action_preview_table = QTableWidget(0, 4)
        self.action_preview_table.setHorizontalHeaderLabels(["#", "行动者", "+AV", "总AV"])
        self.action_preview_table.setFixedHeight(180)
        self.action_preview_table.setShowGrid(False)
        self.action_preview_table.setAlternatingRowColors(True)
        self.action_preview_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.action_preview_table.setSelectionMode(QTableWidget.NoSelection)
        self.action_preview_table.setFocusPolicy(Qt.NoFocus)
        self.action_preview_table.verticalHeader().setVisible(False)
        self.action_preview_table.verticalHeader().setDefaultSectionSize(25)
        self.action_preview_table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.action_preview_table.setColumnWidth(0, 26)
        self.action_preview_table.setColumnWidth(1, 112)
        self.action_preview_table.setColumnWidth(2, 50)
        self.action_preview_table.setColumnWidth(3, 54)
        self.action_preview_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.action_preview_table.setToolTip(
            "基于当前行动队列的静态预测；角色技能造成的推拉条/速度变化以实际结算为准"
        )
        preview_layout.addWidget(self.action_preview_table)
        layout.addWidget(preview_panel)

        layout.addStretch(1)

        # ── 底部操作 ──────────────────────────────────
        self.run_btn = QPushButton("▶  运行模拟")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self._run_simulation)
        layout.addWidget(self.run_btn)

        self.reset_btn = QPushButton("↻  重置配置")
        self.reset_btn.setMinimumHeight(34)
        self.reset_btn.setCursor(Qt.PointingHandCursor)
        self.reset_btn.clicked.connect(self._load_default_config)
        layout.addWidget(self.reset_btn)

        return sidebar

    def _build_main_area(self) -> QWidget:
        """右侧主区域：Tab 切换。"""
        main = QWidget()
        main.setObjectName("mainArea")
        # 用 objectName 限定样式，避免级联覆盖子控件（如按钮背景色）
        main.setStyleSheet(
            f"QWidget#mainArea {{ background-color: {Colors.BG_DARK}; }}"
        )
        layout = QVBoxLayout(main)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._build_config_tab(), "⚙  配置")
        self.tabs.addTab(self._build_interactive_tab(), "▶  交互模拟")
        self.tabs.addTab(self._build_log_tab(), "☰  行动日志")
        self.tabs.addTab(self._build_timeline_tab(), "◔  AV 时间轴")
        self.tabs.addTab(self._build_pie_tab(), "◔  伤害占比")
        self.tabs.addTab(self._build_detail_tab(), "≡  伤害明细")
        self.tabs.addTab(self._build_summary_tab(), "✦  汇总")

        return main

    # ── 各 Tab 构建 ───────────────────────────────────

    def _build_config_tab(self) -> QWidget:
        """配置页：队伍 + 怪物 + 战斗参数。"""
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        # 队伍配置
        team_group = QGroupBox("队伍配置（双击名称列可选择角色）")
        team_layout = QVBoxLayout(team_group)
        import_row = QHBoxLayout()
        import_btn = QPushButton("导入 freesr-data.json")
        import_btn.setCursor(Qt.PointingHandCursor)
        import_btn.clicked.connect(self._import_freesr)
        import_row.addWidget(import_btn)
        import_row.addStretch()
        team_layout.addLayout(import_row)
        self.team_table = QTableWidget(4, COL_COUNT)
        self.team_table.setHorizontalHeaderLabels(TABLE_HEADERS)
        header = self.team_table.horizontalHeader()
        # 名称/光锥列可伸缩，12 项属性固定宽度，横向滚动
        header.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        header.setSectionResizeMode(COL_LIGHTCONE, QHeaderView.Interactive)
        for col in range(2, COL_COUNT):
            header.setSectionResizeMode(col, QHeaderView.Fixed)
        header.setDefaultSectionSize(90)
        # 表头 tooltip：百分比列注明小数格式；属性增伤注明适用角色自身属性
        for col in range(2, COL_COUNT):
            tip = TABLE_HEADERS[col]
            if col in PERCENT_COLUMNS:
                tip += "（小数，0.05 = 5%）"
            if col == COL_DMG_BONUS:
                tip += "（仅该角色自身属性）"
            item = QTableWidgetItem(TABLE_HEADERS[col])
            item.setToolTip(tip)
            self.team_table.setHorizontalHeaderItem(col, item)
        self.team_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOn)
        self.team_table.verticalHeader().setDefaultSectionSize(30)
        self.team_table.setAlternatingRowColors(True)
        # 固定表格高度：完整显示表头 + 4 行 + 横向滚动条，无需纵向滚动
        header_h = self.team_table.horizontalHeader().sizeHint().height()
        self.team_table.setFixedHeight(header_h + 4 * 30 + 32)
        self.team_table.cellDoubleClicked.connect(self._on_team_cell_double_clicked)
        team_layout.addWidget(self.team_table)
        layout.addWidget(team_group)

        # 怪物配置 + 战斗参数（并排）
        bottom_layout = QHBoxLayout()

        enemy_group = QGroupBox("怪物配置")
        enemy_form = QFormLayout(enemy_group)
        enemy_form.setSpacing(8)
        # 怪物数量（1-5）：场上所有怪物共享韧性/弱点/等级/抗性配置
        self.enemy_count_spin = QSpinBox()
        self.enemy_count_spin.setRange(1, 5)
        self.enemy_count_spin.setValue(1)
        self.enemy_count_spin.setToolTip("场上怪物数量（1-5），所有怪物共享下方配置")
        enemy_form.addRow("数量", self.enemy_count_spin)
        # 种类固定"木桩"：速度 0，不进入行动队列（永不行动）
        enemy_name_label = QLabel("木桩（速度 0，永不行动）")
        enemy_name_label.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; border: none;")
        enemy_form.addRow("种类", enemy_name_label)
        self.toughness_spin = QSpinBox()
        self.toughness_spin.setRange(1, 1000)
        self.toughness_spin.setValue(60)
        enemy_form.addRow("韧性", self.toughness_spin)
        self.enemy_hp_spin = QSpinBox()
        self.enemy_hp_spin.setRange(1, 100_000_000)
        self.enemy_hp_spin.setValue(100000)
        self.enemy_hp_spin.setSingleStep(1000)
        self.enemy_hp_spin.setToolTip("生命值（所有怪物共享）；HP 归零判定死亡离场")
        enemy_form.addRow("生命值", self.enemy_hp_spin)
        self.weakness_edit = QPlainTextEdit()
        self.weakness_edit.setPlainText("火, 冰")
        self.weakness_edit.setFixedHeight(32)
        self.weakness_edit.setToolTip("弱点属性对所有怪物生效；持有弱点的对应属性抗性为 0")
        enemy_form.addRow("弱点属性", self.weakness_edit)
        self.enemy_level_spin = QSpinBox()
        self.enemy_level_spin.setRange(1, 100)
        self.enemy_level_spin.setValue(80)
        enemy_form.addRow("等级", self.enemy_level_spin)
        self.non_weak_resist_spin = QSpinBox()
        self.non_weak_resist_spin.setRange(0, 100)
        self.non_weak_resist_spin.setValue(20)
        self.non_weak_resist_spin.setSuffix(" %")
        self.non_weak_resist_spin.setToolTip(
            "非弱点属性抗性（默认 20%）：怪物持有弱点的对应属性抗性为 0，其余属性使用此值"
        )
        enemy_form.addRow("非弱点抗性", self.non_weak_resist_spin)
        bottom_layout.addWidget(enemy_group)

        params_group = QGroupBox("战斗参数")
        params_form = QFormLayout(params_group)
        params_form.setSpacing(8)
        self.sp_spin = QSpinBox()
        self.sp_spin.setRange(0, 5)
        self.sp_spin.setValue(3)
        params_form.addRow("初始 SP", self.sp_spin)
        self.turns_spin = QSpinBox()
        self.turns_spin.setRange(50, 10000)
        self.turns_spin.setSingleStep(50)
        self.turns_spin.setValue(300)
        params_form.addRow("最大总行动值", self.turns_spin)
        self.action_combo = QComboBox()
        self.action_combo.addItems([
            "智能（终结技 > 战技 > 普攻）",
            "全部普攻",
            "全部战技（SP 够时）",
        ])
        params_form.addRow("默认操作", self.action_combo)
        bottom_layout.addWidget(params_group)

        layout.addLayout(bottom_layout)

        # 技能等级（全局，按技能类型分级；忆灵/欢愉为对应命途专用）
        skill_group = QGroupBox("技能等级（全局）")
        skill_form = QFormLayout(skill_group)
        skill_form.setSpacing(8)
        self.skill_level_normal_spin = QSpinBox()
        self.skill_level_normal_spin.setRange(1, 10)
        self.skill_level_normal_spin.setValue(1)
        skill_form.addRow("普攻", self.skill_level_normal_spin)
        self.skill_level_skill_spin = QSpinBox()
        self.skill_level_skill_spin.setRange(1, 15)
        self.skill_level_skill_spin.setValue(1)
        skill_form.addRow("战技", self.skill_level_skill_spin)
        self.skill_level_ultra_spin = QSpinBox()
        self.skill_level_ultra_spin.setRange(1, 15)
        self.skill_level_ultra_spin.setValue(1)
        skill_form.addRow("终结技", self.skill_level_ultra_spin)
        self.skill_level_talent_spin = QSpinBox()
        self.skill_level_talent_spin.setRange(1, 15)
        self.skill_level_talent_spin.setValue(1)
        skill_form.addRow("天赋", self.skill_level_talent_spin)
        self.skill_level_memo_spin = QSpinBox()
        self.skill_level_memo_spin.setRange(1, 15)
        self.skill_level_memo_spin.setValue(1)
        self.skill_level_memo_spin.setToolTip("记忆命途角色（忆灵技）专用")
        skill_form.addRow("忆灵技", self.skill_level_memo_spin)
        self.elation_skill_level_spin = QSpinBox()
        self.elation_skill_level_spin.setRange(1, 15)
        self.elation_skill_level_spin.setValue(1)
        self.elation_skill_level_spin.setToolTip("欢愉命途角色（欢愉技）专用；技能数据识别 TODO")
        skill_form.addRow("欢愉技", self.elation_skill_level_spin)
        layout.addWidget(skill_group)

        # 敌方攻击配置（木桩速度 0，按总行动值强制攻击）
        attack_group = QGroupBox("敌方攻击配置（行动值推进到配置值即强制攻击）")
        attack_layout = QVBoxLayout(attack_group)
        attack_btn_row = QHBoxLayout()
        add_attack_btn = QPushButton("＋ 添加攻击")
        add_attack_btn.setCursor(Qt.PointingHandCursor)
        add_attack_btn.clicked.connect(self._add_enemy_attack_row)
        attack_btn_row.addWidget(add_attack_btn)
        remove_attack_btn = QPushButton("－ 删除选中")
        remove_attack_btn.setCursor(Qt.PointingHandCursor)
        remove_attack_btn.clicked.connect(self._remove_enemy_attack_row)
        attack_btn_row.addWidget(remove_attack_btn)
        attack_btn_row.addStretch()
        attack_layout.addLayout(attack_btn_row)
        self.enemy_attack_table = QTableWidget(0, 5)
        self.enemy_attack_table.setHorizontalHeaderLabels(
            ["总行动值", "释放来源", "攻击力", "目标角色", "恢复能量"]
        )
        self.enemy_attack_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.enemy_attack_table.verticalHeader().setDefaultSectionSize(40)
        self.enemy_attack_table.setAlternatingRowColors(True)
        self.enemy_attack_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.enemy_attack_table.setToolTip(
            "每行配置一次敌方攻击；「释放来源」为发动攻击的敌方目标；"
            "「目标角色」点击按钮后可多选当前队伍中的角色"
        )
        attack_layout.addWidget(self.enemy_attack_table)
        layout.addWidget(attack_group)

        # 队伍名称/行变动时，刷新敌方攻击目标按钮上的角色名
        self.team_table.itemChanged.connect(self._refresh_enemy_attack_target_buttons)

        layout.addStretch()

        # 禁止数值框/下拉框通过滚轮改值（防止误操作）
        _disable_wheel_inputs(content)

        scroll.setWidget(content)

        # 页面布局：滚动区域 + 固定底部运行按钮
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        page_layout.setSpacing(8)
        page_layout.addWidget(scroll, stretch=1)

        # 运行按钮固定在配置页底部（滚动区域外，始终可见）
        run_btn2 = QPushButton("▶  运行模拟")
        run_btn2.setObjectName("primaryBtn")
        run_btn2.setMinimumHeight(44)
        run_btn2.setCursor(Qt.PointingHandCursor)
        run_btn2.clicked.connect(self._run_simulation)
        page_layout.addWidget(run_btn2)

        return page

    def _build_interactive_tab(self) -> QWidget:
        """交互模拟页：步进式模拟 + 键盘操作 + 回溯。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        # 状态栏
        status_group = QGroupBox("当前状态")
        status_layout = QVBoxLayout(status_group)
        self.interactive_status_label = QLabel(
            "未开始交互模拟 — 请在配置页设置队伍后点击「开始交互模拟」"
        )
        self.interactive_status_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 13px; padding: 6px;"
        )
        self.interactive_status_label.setWordWrap(True)
        status_layout.addWidget(self.interactive_status_label)
        layout.addWidget(status_group)

        # 敌方目标选择（有几个敌人就有几个选取对象；普攻/战技/终结技攻击所选目标）
        target_group = QGroupBox("敌方目标（选择主目标）")
        self.enemy_target_layout = QHBoxLayout(target_group)
        self.enemy_target_layout.setSpacing(12)
        self._enemy_target_buttons: list[EnemyTargetWidget] = []
        self._selected_enemy_id: str = ""
        layout.addWidget(target_group)

        # 角色能量图标区（含 SP 指示器）
        energy_group = QGroupBox("角色能量  ·  满能量(红色高亮)可释放终结技")
        energy_layout = QHBoxLayout(energy_group)
        energy_layout.setSpacing(12)
        # 角色能量图标（左侧）
        self.energy_orbs_container = QHBoxLayout()
        energy_layout.addLayout(self.energy_orbs_container)
        energy_layout.addStretch()
        # 分隔线
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet(f"color: {Colors.BORDER};")
        energy_layout.addWidget(sep)
        # SP 图标（右侧）
        self.sp_indicator = SPIndicatorWidget()
        energy_layout.addWidget(self.sp_indicator)
        layout.addWidget(energy_group)

        # 操作按钮区
        ops_group = QGroupBox("操作  ·  键盘: E=战技  Q=普攻  1/2/3/4=终结技插队  空格=推进行动")
        ops_layout = QHBoxLayout(ops_group)
        ops_layout.setSpacing(6)

        self.btn_start_interactive = QPushButton("▶ 开始交互模拟")
        self.btn_start_interactive.setObjectName("primaryBtn")
        self.btn_start_interactive.setCursor(Qt.PointingHandCursor)
        self.btn_start_interactive.clicked.connect(self._start_interactive)
        ops_layout.addWidget(self.btn_start_interactive)

        self.btn_advance = QPushButton("▶ 推进 (空格)")
        self.btn_advance.setEnabled(False)
        self.btn_advance.setCursor(Qt.PointingHandCursor)
        self.btn_advance.clicked.connect(self._interactive_advance)
        ops_layout.addWidget(self.btn_advance)

        self.btn_normal = QPushButton("普攻 (Q)")
        self.btn_normal.setEnabled(False)
        self.btn_normal.setCursor(Qt.PointingHandCursor)
        self.btn_normal.clicked.connect(lambda: self._interactive_step(SkillType.NORMAL))
        ops_layout.addWidget(self.btn_normal)

        self.btn_skill = QPushButton("战技 (E)")
        self.btn_skill.setEnabled(False)
        self.btn_skill.setCursor(Qt.PointingHandCursor)
        self.btn_skill.clicked.connect(lambda: self._interactive_step(SkillType.SKILL))
        ops_layout.addWidget(self.btn_skill)

        # 终结技按钮 1-4
        self.btn_ultras: list[QPushButton] = []
        for i in range(4):
            btn = QPushButton(f"终结技{i + 1}")
            btn.setEnabled(False)
            btn.setCursor(Qt.PointingHandCursor)
            btn.clicked.connect(lambda checked, idx=i: self._interactive_ultra(idx))
            self.btn_ultras.append(btn)
            ops_layout.addWidget(btn)

        self.btn_rewind = QPushButton("⟲ 回溯到此回合")
        self.btn_rewind.setEnabled(False)
        self.btn_rewind.setCursor(Qt.PointingHandCursor)
        self.btn_rewind.clicked.connect(self._interactive_rewind_to_selected)
        ops_layout.addWidget(self.btn_rewind)

        # 交互区按钮禁用键盘焦点：空格/回车始终由主窗口 keyPressEvent 处理，
        # 避免按钮获得焦点时空格触发"重新开始"等按钮点击
        for btn in (self.btn_start_interactive, self.btn_advance, self.btn_normal,
                    self.btn_skill, self.btn_rewind, *self.btn_ultras):
            btn.setFocusPolicy(Qt.NoFocus)

        layout.addWidget(ops_group)

        # 日志表格
        hint = QLabel("提示：选中某行后点击「回溯到此回合」可回到该回合重新操作（旧记录灰显保留）")
        hint.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(hint)

        self.interactive_log_table = QTableWidget(0, 8)
        self.interactive_log_table.setHorizontalHeaderLabels(
            ["回合", "AV", "总行动值", "行动者", "操作", "伤害明细", "总伤害", "备注"]
        )
        self.interactive_log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.interactive_log_table.verticalHeader().setDefaultSectionSize(32)
        self.interactive_log_table.setAlternatingRowColors(True)
        self.interactive_log_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.interactive_log_table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.interactive_log_table)

        return page

    def _build_log_tab(self) -> QWidget:
        """行动日志页：表格。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        self.log_table = QTableWidget(0, 8)
        self.log_table.setHorizontalHeaderLabels(
            ["回合", "AV", "总行动值", "行动者", "操作", "伤害明细", "总伤害", "备注"]
        )
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.log_table.verticalHeader().setDefaultSectionSize(32)
        self.log_table.setAlternatingRowColors(True)
        layout.addWidget(self.log_table)
        return page

    def _build_timeline_tab(self) -> QWidget:
        """AV 时间轴页：甘特图。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel("横轴为累计总行动值，悬停行动点可查看详情")
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 12px;")
        layout.addWidget(hint)

        self.gantt_widget = TimelineGanttWidget()
        layout.addWidget(self.gantt_widget)
        return page

    def _build_pie_tab(self) -> QWidget:
        """伤害占比页：饼图 + 角色伤害列表。"""
        page = QWidget()
        layout = QVBoxLayout(page)

        self.pie_widget = DamagePieChartWidget()
        layout.addWidget(self.pie_widget, stretch=1)

        # 角色伤害排行表
        rank_label = QLabel("角色伤害排行")
        rank_label.setStyleSheet(
            f"color: {Colors.GOLD}; font-size: 13px; font-weight: 600;"
        )
        layout.addWidget(rank_label)

        self.rank_table = QTableWidget(0, 4)
        self.rank_table.setHorizontalHeaderLabels(["角色", "命途/属性", "总伤害", "占比"])
        self.rank_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.rank_table.verticalHeader().setDefaultSectionSize(32)
        self.rank_table.setAlternatingRowColors(True)
        layout.addWidget(self.rank_table)
        return page

    def _build_detail_tab(self) -> QWidget:
        """伤害明细页：表格。"""
        page = QWidget()
        layout = QVBoxLayout(page)
        self.detail_table = QTableWidget(0, 8)
        self.detail_table.setHorizontalHeaderLabels(
            ["回合", "总AV", "行动者", "操作", "目标", "伤害段数", "总伤害", "备注"]
        )
        self.detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.detail_table.verticalHeader().setDefaultSectionSize(32)
        self.detail_table.setAlternatingRowColors(True)
        layout.addWidget(self.detail_table)
        return page

    def _build_summary_tab(self) -> QWidget:
        """汇总页：数据卡片 + 状态信息。"""
        page = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(12)

        # 战斗数据卡片
        cards_label = QLabel("战斗数据")
        cards_label.setStyleSheet(
            f"color: {Colors.GOLD}; font-size: 13px; font-weight: 600;"
        )
        layout.addWidget(cards_label)

        cards_layout = QGridLayout()
        cards_layout.setSpacing(10)
        self.card_turns = make_card("总回合数", "-", Colors.GOLD)
        self.card_av = make_card("总行动值", "-", Colors.CYAN)
        self.card_damage = make_card("总伤害", "-", Colors.GOLD)
        self.card_avg = make_card("平均每回合", "-", Colors.PURPLE)
        self.card_aha = make_card("阿哈时刻", "-", Colors.GOLD)
        self.card_sp = make_card("最终 SP", "-", Colors.GREEN)
        cards_layout.addWidget(self.card_turns, 0, 0)
        cards_layout.addWidget(self.card_av, 0, 1)
        cards_layout.addWidget(self.card_damage, 0, 2)
        cards_layout.addWidget(self.card_avg, 1, 0)
        cards_layout.addWidget(self.card_aha, 1, 1)
        cards_layout.addWidget(self.card_sp, 1, 2)
        layout.addLayout(cards_layout)

        # 角色最终状态
        char_group = QGroupBox("角色最终状态")
        char_layout = QVBoxLayout(char_group)
        self.char_summary_table = QTableWidget(0, 7)
        self.char_summary_table.setHorizontalHeaderLabels(
            ["角色", "命途", "属性", "攻击力", "速度", "暴击", "能量"]
        )
        self.char_summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.char_summary_table.verticalHeader().setDefaultSectionSize(32)
        self.char_summary_table.setAlternatingRowColors(True)
        char_layout.addWidget(self.char_summary_table)
        layout.addWidget(char_group)

        # 怪物状态
        enemy_group = QGroupBox("怪物状态")
        enemy_layout = QVBoxLayout(enemy_group)
        self.enemy_summary_table = QTableWidget(0, 5)
        self.enemy_summary_table.setHorizontalHeaderLabels(
            ["名称", "韧性", "击破", "弱点", "等级"]
        )
        self.enemy_summary_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.enemy_summary_table.verticalHeader().setDefaultSectionSize(32)
        self.enemy_summary_table.setAlternatingRowColors(True)
        enemy_layout.addWidget(self.enemy_summary_table)
        layout.addWidget(enemy_group)

        # 结束原因
        self.end_reason_label = QLabel()
        self.end_reason_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 12px; padding: 8px;"
        )
        layout.addWidget(self.end_reason_label)

        layout.addStretch()
        scroll.setWidget(content)
        wrap = QVBoxLayout()
        wrap.setContentsMargins(0, 0, 0, 0)
        wrap.addWidget(scroll)
        page.setLayout(wrap)
        return page

    def _make_separator(self) -> QFrame:
        """构造水平分隔线。"""
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"color: {Colors.BORDER}; background-color: {Colors.BORDER};")
        line.setFixedHeight(1)
        return line

    # ── 角色选择 ─────────────────────────────────────

    def _on_team_cell_double_clicked(self, row: int, column: int) -> None:
        """双击队伍表格名称列，弹出角色选择器。"""
        if column != 0:
            return
        picker = CharacterPickerDialog(self)
        if picker.exec() == QDialog.Accepted and picker.selected_character:
            c = picker.selected_character
            name_item = QTableWidgetItem(c.name_zh or c.name_en)
            # 名称列存储行角色数据（真实详情加载完成后回填）
            name_item.setData(
                Qt.UserRole,
                _RowCharData(char_id=c.id, name=c.name_zh or c.name_en, path=c.path, element=c.element),
            )
            self.team_table.setItem(row, 0, name_item)
            self._update_element_bonus_tooltips()
            # 异步加载真实详情（技能/面板自动填充）
            self._start_detail_load(row, c.id)

    # ── 详情异步加载 ────────────────────────────────────

    def _start_detail_load(self, row: int, char_id: str) -> None:
        """启动单行角色详情加载线程（一次性，finished 后自动回收）。"""
        if not hasattr(self, "_detail_threads"):
            self._detail_threads: dict[int, QThread] = {}
            self._detail_workers: dict[int, QObject] = {}
        thread = QThread()
        worker = _CharacterDetailWorker(char_id, row)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._on_detail_loaded)
        worker.failed.connect(self._on_detail_failed)
        # 线程结束自动回收
        thread.finished.connect(thread.deleteLater)
        # 关键：worker 无 parent，必须保存在实例属性避免被 GC 回收
        # （回收会触发 destroyed → thread.quit，导致 run 未执行线程就退出）
        self._detail_threads[row] = thread
        self._detail_workers[row] = worker

        def _cleanup(r: int = row) -> None:
            self._detail_threads.pop(r, None)
            self._detail_workers.pop(r, None)

        thread.finished.connect(_cleanup)
        thread.start()

    def _on_detail_loaded(self, row: int, payload: dict) -> None:
        """详情加载完成：校验行角色一致性后回填并自动填充面板列。"""
        if row >= self.team_table.rowCount():
            return
        name_item = self.team_table.item(row, 0)
        if name_item is None:
            return
        row_data = name_item.data(Qt.UserRole)
        if not isinstance(row_data, _RowCharData) or not row_data.char_id:
            return
        # 防连选竞态：仅当载荷与当前行角色一致才写入
        if payload.get("char_id") != row_data.char_id:
            return

        row_data.sp_need = payload.get("sp_need", 0)
        row_data.stats80 = payload.get("stats80", {})
        row_data.skills_raw = payload.get("skills_raw", {})
        row_data.skill_trees_raw = payload.get("skill_trees_raw", {})
        row_data.loaded = True
        name_item.setData(Qt.UserRole, row_data)

        # 自动填充面板列（角色基础 + 行迹加成 = 游戏面板最终值；
        # 行迹是常驻加成而非 buff，用户可手动修改表格模拟遗器加成）
        s = row_data.stats80
        base = convert_stats80(s)
        trace = extract_trace_bonuses(row_data.skill_trees_raw)
        final = StatCalculator(base=base, bonus=trace).final()
        self._set_cell_value(row, COL_HP, int(final.hp))
        self._set_cell_value(row, COL_ATK, int(final.atk))
        self._set_cell_value(row, COL_DEF, int(final.defense))
        self._set_cell_value(row, COL_SPD, final.spd)
        self._set_cell_value(row, COL_CRIT_RATE, final.crit_rate)
        self._set_cell_value(row, COL_CRIT_DMG, final.crit_dmg)
        self._set_cell_value(row, COL_BREAK_EFFECT, final.break_effect)
        self._set_cell_value(row, COL_EFFECT_RES, final.effect_res)
        self._set_cell_value(row, COL_ENERGY_REGEN, final.energy_regen)
        self._set_cell_value(row, COL_EFFECT_HIT, final.effect_hit)
        self._set_cell_value(row, COL_OUTGOING_HEAL, final.outgoing_heal)
        self._set_cell_value(row, COL_DMG_BONUS, final.dmg_bonus)

        # freesr 导入时序钩子：详情加载完成时补填已导入行的最终面板
        job = getattr(self, "_freesr_job", None)
        if job and any(r == row for r, _ in job["matched"]):
            self._fill_freesr_panels()

    def _on_detail_failed(self, row: int, err: str) -> None:
        """详情加载失败：提示并保持预设技能。"""
        if row >= self.team_table.rowCount():
            return
        name_item = self.team_table.item(row, 0)
        name = name_item.text() if name_item else f"角色 {row + 1}"
        QMessageBox.warning(
            self, "数据加载失败",
            f"角色「{name}」真实数据加载失败：{err}\n将使用预设技能数据",
        )

    def _set_cell_value(self, row: int, col: int, value) -> None:
        """写入面板列（百分比列 4 位小数，速度 1 位小数，其余原样）。"""
        if col in PERCENT_COLUMNS:
            text = f"{value:.4f}"
        elif col == COL_SPD:
            text = f"{value:.1f}"
        else:
            text = str(value)
        self.team_table.setItem(row, col, QTableWidgetItem(text))

    def _set_lightcone_cell(self, row: int, name: str) -> None:
        """写入光锥列（携带光锥名）。"""
        self.team_table.setItem(row, COL_LIGHTCONE, QTableWidgetItem(name))

    def _update_element_bonus_tooltips(self) -> None:
        """属性增伤列 tooltip：按行角色属性动态标注。"""
        if not hasattr(self, "team_table"):
            return
        for row in range(self.team_table.rowCount()):
            elem_zh = ""
            name_item = self.team_table.item(row, 0)
            if name_item is not None:
                row_data = name_item.data(Qt.UserRole)
                if isinstance(row_data, _RowCharData) and row_data.element:
                    elem_zh = ELEMENT_MAP.get(row_data.element, row_data.element)
            item = self.team_table.item(row, COL_DMG_BONUS)
            if item is None:
                item = QTableWidgetItem("0")
                self.team_table.setItem(row, COL_DMG_BONUS, item)
            item.setToolTip(f"适用于{elem_zh}的伤害加成" if elem_zh else "属性伤害加成")

    # ── freesr 导入 ────────────────────────────────────

    def _import_freesr(self) -> None:
        """导入 freesr-data.json：选文件 → 解析 → 匹配队伍 → 填面板。"""
        path, _ = QFileDialog.getOpenFileName(
            self, "选择 freesr-data.json", "", "JSON 文件 (*.json);;所有文件 (*)"
        )
        if not path:
            return
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
            profile = parse_freesr(raw)
        except Exception as e:
            QMessageBox.warning(self, "导入失败", f"解析 freesr-data.json 失败: {e}")
            return

        if not profile.avatars:
            QMessageBox.information(self, "导入", "文件中没有已配置的角色（无有效数据）")
            return

        matched, unmatched = self._apply_freesr_profile(profile)

        # 记录导入任务（光锥详情异步加载完成后填面板）
        self._freesr_job = {
            "profile": profile,
            "matched": matched,
            "lightcone_rows": {},      # {item_id: stats80 行}
            "lc_failed": [],
        }

        # 收集需要的光锥详情（去重）
        item_ids = sorted({
            lc.item_id for lcs in profile.lightcones.values() for lc in lcs
        })
        if item_ids:
            self._start_freesr_lightcone_load(item_ids)
        else:
            self._fill_freesr_panels()

        if unmatched:
            # 未匹配提示截断（freesr 空配置的 data 也计入，可能很多）
            shown = unmatched[:10]
            suffix = f"\n…等 {len(unmatched)} 个角色" if len(unmatched) > 10 else ""
            QMessageBox.information(
                self, "导入完成",
                f"已导入 {len(matched)} 个角色。\n\n以下角色已配置但不在队伍中：\n"
                + "\n".join(shown) + suffix,
            )
        else:
            QMessageBox.information(self, "导入完成", f"已导入 {len(matched)} 个角色")

    def _apply_freesr_profile(
        self, profile,
    ) -> tuple[list[tuple[int, str]], list[str]]:
        """按 char_id 匹配队伍行：写入行数据 + 更新技能等级 SpinBox。

        Returns:
            (matched: [(row, char_id)], unmatched: [char_id])
        """
        # char_id → row 映射
        row_by_char: dict[str, int] = {}
        for row in range(self.team_table.rowCount()):
            name_item = self.team_table.item(row, 0)
            if name_item is None:
                continue
            row_data = name_item.data(Qt.UserRole)
            if isinstance(row_data, _RowCharData) and row_data.char_id:
                row_by_char[row_data.char_id] = row

        matched: list[tuple[int, str]] = []
        unmatched: list[str] = []
        for char_id, avatar in profile.avatars.items():
            row = row_by_char.get(char_id)
            if row is None:
                unmatched.append(char_id)
                continue
            name_item = self.team_table.item(row, 0)
            row_data = name_item.data(Qt.UserRole)
            row_data.sp_value = avatar.sp_value
            row_data.rank = avatar.rank
            row_data.relics_raw = [
                r.raw for r in profile.relics.get(char_id, [])
            ]
            row_data.lightcone_raw = [
                lc.raw for lc in profile.lightcones.get(char_id, [])
            ]
            name_item.setData(Qt.UserRole, row_data)
            # 技能等级 → 全局 SpinBox（freesr 主技能）
            levels = avatar.skill_levels
            if SkillType.NORMAL in levels:
                self.skill_level_normal_spin.setValue(levels[SkillType.NORMAL])
            if SkillType.SKILL in levels:
                self.skill_level_skill_spin.setValue(levels[SkillType.SKILL])
            if SkillType.ULTRA in levels:
                self.skill_level_ultra_spin.setValue(levels[SkillType.ULTRA])
            if SkillType.TALENT in levels:
                self.skill_level_talent_spin.setValue(levels[SkillType.TALENT])
            # sp_max 兜底 sp_need（详情未加载时能量上限）
            if avatar.sp_max > 0 and row_data.sp_need == 0:
                row_data.sp_need = avatar.sp_max
            matched.append((row, char_id))
        return matched, unmatched

    def _start_freesr_lightcone_load(self, item_ids: list[int]) -> None:
        """启动光锥详情加载线程（一次性，finished 后自动回收）。"""
        if not hasattr(self, "_lc_threads"):
            self._lc_threads: dict[str, QThread] = {}
            self._lc_workers: dict[str, QObject] = {}
        thread = QThread()
        worker = _FreesrLightconeWorker(item_ids)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._on_freesr_lightcone_loaded)
        thread.finished.connect(thread.deleteLater)
        key = ",".join(str(i) for i in item_ids)
        self._lc_threads[key] = thread
        self._lc_workers[key] = worker

        def _cleanup(k: str = key) -> None:
            self._lc_threads.pop(k, None)
            self._lc_workers.pop(k, None)

        thread.finished.connect(_cleanup)
        thread.start()

    def _on_freesr_lightcone_loaded(self, rows: dict, failed: list) -> None:
        """光锥详情就绪：更新导入任务并填面板；失败的按 0 处理并提示。"""
        job = getattr(self, "_freesr_job", None)
        if job is None:
            return
        job["lightcone_rows"].update(rows)
        job["lc_failed"] = list(failed)
        self._fill_freesr_panels()
        if failed:
            QMessageBox.warning(
                self, "光锥数据加载失败",
                f"以下光锥详情加载失败，其属性按 0 处理：{failed}",
            )

    def _fill_freesr_panels(self) -> None:
        """为已就绪的匹配行计算并填写最终面板（幂等，可多次调用）。"""
        job = getattr(self, "_freesr_job", None)
        if not job:
            return
        profile = job["profile"]
        for row, char_id in job["matched"]:
            name_item = self.team_table.item(row, 0)
            if name_item is None:
                continue
            row_data = name_item.data(Qt.UserRole)
            if not isinstance(row_data, _RowCharData) or not row_data.stats80:
                continue  # 详情未就绪，等待 _on_detail_loaded 钩子补调

            # 光锥 80 级行（缺失按 0 处理；同时存入行数据供面板基础值显示与光锥名展示）
            lc_stats80 = None
            lcs = profile.lightcones.get(char_id, [])
            if lcs:
                item_id = lcs[0].item_id
                lc_info = job["lightcone_rows"].get(item_id) or {}
                lc_stats80 = lc_info.get("stats80")
                row_data.lightcone_name = lc_info.get("name", "")
            row_data.lightcone_stats80 = lc_stats80 or {}
            self._set_lightcone_cell(row, row_data.lightcone_name)

            final = compute_panel(
                row_data.stats80,
                profile.relics.get(char_id, []),
                lc_stats80,
                row_data.skill_trees_raw,
            )
            self._set_cell_value(row, COL_HP, int(final.hp))
            self._set_cell_value(row, COL_ATK, int(final.atk))
            self._set_cell_value(row, COL_DEF, int(final.defense))
            self._set_cell_value(row, COL_SPD, final.spd)
            self._set_cell_value(row, COL_CRIT_RATE, final.crit_rate)
            self._set_cell_value(row, COL_CRIT_DMG, final.crit_dmg)
            self._set_cell_value(row, COL_BREAK_EFFECT, final.break_effect)
            self._set_cell_value(row, COL_EFFECT_RES, final.effect_res)
            self._set_cell_value(row, COL_ENERGY_REGEN, final.energy_regen)
            self._set_cell_value(row, COL_EFFECT_HIT, final.effect_hit)
            self._set_cell_value(row, COL_OUTGOING_HEAL, final.outgoing_heal)
            self._set_cell_value(row, COL_DMG_BONUS, final.dmg_bonus)

    # ── 默认配置 ─────────────────────────────────────

    def _load_default_config(self) -> None:
        """加载默认配置。"""
        defaults = [
            ("char1", "角色A", "存护", "火", 10000, 1200, 500, 100, 0.05, 0.5),
            ("char2", "角色B", "巡猎", "冰", 9000, 1100, 480, 134, 0.30, 1.0),
            ("char3", "角色C", "智识", "雷", 8000, 1300, 420, 110, 0.10, 0.7),
            ("char4", "角色D", "欢愉", "风", 10000, 1000, 500, 120, 0.05, 0.5),
        ]
        for row, (uid, name, path, elem, hp, atk, def_, spd, cr, cd) in enumerate(defaults):
            name_item = QTableWidgetItem(name)
            # 重置行数据（清掉可能的旧真实角色残留；命途/属性存英文原始值供侧栏显示）
            name_item.setData(Qt.UserRole, _RowCharData(
                char_id="",
                name=name,
                path=PATH_MAP_ZH_TO_EN.get(path, ""),
                element=ELEMENT_MAP_ZH_TO_EN.get(elem, ""),
            ))
            self.team_table.setItem(row, 0, name_item)
            self._set_cell_value(row, COL_HP, hp)
            self._set_cell_value(row, COL_ATK, atk)
            self._set_cell_value(row, COL_DEF, def_)
            self._set_cell_value(row, COL_SPD, spd)
            self._set_cell_value(row, COL_CRIT_RATE, cr)
            self._set_cell_value(row, COL_CRIT_DMG, cd)
            for col in (COL_BREAK_EFFECT, COL_EFFECT_RES, COL_ENERGY_REGEN,
                        COL_EFFECT_HIT, COL_OUTGOING_HEAL, COL_DMG_BONUS):
                self._set_cell_value(row, col, 0.0)
        self._update_element_bonus_tooltips()

    # ── 配置缓存 ─────────────────────────────────────

    def _save_config(self) -> None:
        """保存全部配置（队伍表格 + 怪物 + 战斗参数 + 技能等级）到缓存文件。"""
        rows = []
        for row in range(self.team_table.rowCount()):
            name_item = self.team_table.item(row, 0)
            if name_item is None or not name_item.text().strip():
                continue
            entry = {"name": name_item.text().strip()}
            row_data = name_item.data(Qt.UserRole)
            entry["row_data"] = asdict(row_data) if isinstance(row_data, _RowCharData) else None
            entry["cells"] = {}
            for col in range(1, COL_COUNT):
                item = self.team_table.item(row, col)
                entry["cells"][col] = item.text() if item else ""
            rows.append(entry)

        data = {
            "version": 3,
            "rows": rows,
            "enemy": {
                "count": self.enemy_count_spin.value(),
                "toughness": self.toughness_spin.value(),
                "hp": self.enemy_hp_spin.value(),
                "weakness": self.weakness_edit.toPlainText(),
                "level": self.enemy_level_spin.value(),
                "non_weak_resist": self.non_weak_resist_spin.value(),
            },
            "battle": {
                "initial_sp": self.sp_spin.value(),
                "max_av": self.turns_spin.value(),
                "action_mode": self.action_combo.currentIndex(),
            },
            "skill_levels": {
                "normal": self.skill_level_normal_spin.value(),
                "skill": self.skill_level_skill_spin.value(),
                "ultra": self.skill_level_ultra_spin.value(),
                "talent": self.skill_level_talent_spin.value(),
                "memo": self.skill_level_memo_spin.value(),
                "elation": self.elation_skill_level_spin.value(),
            },
            "enemy_attacks": [asdict(a) for a in self._collect_enemy_attacks()],
        }
        try:
            CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(
                json.dumps(data, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
        except OSError:
            pass  # 缓存写入失败不影响使用

    def _load_config(self) -> None:
        """加载缓存配置（存在且可解析时覆盖默认配置）。

        旧版本（13 列，无光锥列）队伍缓存自动迁移：属性列号 +1。
        其余配置（怪物/战斗参数/技能等级）为尽力加载，损坏字段回退默认。
        """
        if not CONFIG_PATH.exists():
            return
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        if not isinstance(data, dict):
            return

        def _int(value, default: int) -> int:
            """安全转 int（缓存字段损坏时回退默认）。"""
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        # ── 队伍表格 ──────────────────────────────
        if data.get("version") in (2, 3) and isinstance(data.get("rows"), list):
            rows = data["rows"]
        else:
            # 旧格式（13 列）：属性列号整体 +1（插入光锥列）
            rows = data if isinstance(data, list) else []
            for entry in rows:
                cells = entry.get("cells", {})
                entry["cells"] = {int(k) + 1: v for k, v in cells.items()}
        for i, entry in enumerate(rows[: self.team_table.rowCount()]):
            name_item = QTableWidgetItem(entry.get("name", ""))
            rd_raw = entry.get("row_data")
            if isinstance(rd_raw, dict):
                try:
                    rd = _RowCharData(**rd_raw)
                except TypeError:
                    rd = _RowCharData(char_id="")
            else:
                rd = _RowCharData(char_id="")
            name_item.setData(Qt.UserRole, rd)
            self.team_table.setItem(i, 0, name_item)
            for col, text in entry.get("cells", {}).items():
                self.team_table.setItem(i, int(col), QTableWidgetItem(str(text)))
        self._update_element_bonus_tooltips()

        # ── 怪物配置 ──────────────────────────────
        enemy = data.get("enemy")
        if isinstance(enemy, dict):
            self.enemy_count_spin.setValue(_int(enemy.get("count"), 1))
            self.toughness_spin.setValue(_int(enemy.get("toughness"), 60))
            self.enemy_hp_spin.setValue(_int(enemy.get("hp"), 100000))
            weakness = enemy.get("weakness")
            if isinstance(weakness, str):
                self.weakness_edit.setPlainText(weakness)
            self.enemy_level_spin.setValue(_int(enemy.get("level"), 80))
            self.non_weak_resist_spin.setValue(_int(enemy.get("non_weak_resist"), 20))

        # ── 战斗参数 ──────────────────────────────
        battle = data.get("battle")
        if isinstance(battle, dict):
            self.sp_spin.setValue(_int(battle.get("initial_sp"), 3))
            self.turns_spin.setValue(_int(battle.get("max_av"), 300))
            mode = _int(battle.get("action_mode"), 0)
            if 0 <= mode < self.action_combo.count():
                self.action_combo.setCurrentIndex(mode)

        # ── 技能等级 ──────────────────────────────
        levels = data.get("skill_levels")
        if isinstance(levels, dict):
            self.skill_level_normal_spin.setValue(_int(levels.get("normal"), 1))
            self.skill_level_skill_spin.setValue(_int(levels.get("skill"), 1))
            self.skill_level_ultra_spin.setValue(_int(levels.get("ultra"), 1))
            self.skill_level_talent_spin.setValue(_int(levels.get("talent"), 1))
            self.skill_level_memo_spin.setValue(_int(levels.get("memo"), 1))
            self.elation_skill_level_spin.setValue(_int(levels.get("elation"), 1))

        # ── 敌方攻击配置 ──────────────────────────
        attacks = data.get("enemy_attacks")
        if isinstance(attacks, list):
            self.enemy_attack_table.setRowCount(0)
            for a in attacks:
                if not isinstance(a, dict):
                    continue
                self._add_enemy_attack_row()
                row = self.enemy_attack_table.rowCount() - 1
                self.enemy_attack_table.item(row, 0).setText(str(a.get("total_av", 0)))
                source_combo = self.enemy_attack_table.cellWidget(row, 1)
                if isinstance(source_combo, QComboBox):
                    source_combo.setCurrentIndex(max(0, min(4, _int(a.get("source_enemy_index"), 0))))
                self.enemy_attack_table.item(row, 2).setText(str(a.get("attack", 0)))
                target_widget = self.enemy_attack_table.cellWidget(row, 3)
                target_indices = a.get("target_indices")
                if (
                    isinstance(target_widget, _EnemyAttackTargetButton)
                    and isinstance(target_indices, list)
                ):
                    target_widget.set_target_indices(target_indices)
                self.enemy_attack_table.item(row, 4).setText(str(a.get("energy_recover", 0)))

    # ── 敌方攻击配置 ─────────────────────────────────

    def _team_names(self) -> list[str]:
        """返回队伍表 4 个槽位上的角色名（空槽位为空字符串）。"""
        names: list[str] = []
        for row in range(self.team_table.rowCount()):
            item = self.team_table.item(row, COL_NAME)
            names.append(item.text().strip() if item else "")
        return names

    def _refresh_enemy_attack_target_buttons(self, *_args) -> None:
        """队伍名称变化后，刷新所有敌方攻击目标按钮的显示文本。"""
        if not hasattr(self, "enemy_attack_table"):
            return
        for row in range(self.enemy_attack_table.rowCount()):
            widget = self.enemy_attack_table.cellWidget(row, 3)
            if isinstance(widget, _EnemyAttackTargetButton):
                widget.refresh_text()

    def _add_enemy_attack_row(self) -> None:
        """添加一行敌方攻击配置。"""
        row = self.enemy_attack_table.rowCount()
        self.enemy_attack_table.insertRow(row)
        self.enemy_attack_table.setItem(row, 0, QTableWidgetItem("0"))
        # 释放来源（敌方目标）
        source_combo = QComboBox()
        source_combo.addItems([f"敌人{i + 1}" for i in range(5)])
        source_combo.installEventFilter(_WheelBlocker(source_combo))
        self.enemy_attack_table.setCellWidget(row, 1, source_combo)
        self.enemy_attack_table.setItem(row, 2, QTableWidgetItem("0"))
        # 目标角色：按钮 + 下拉多选菜单（显示当前队伍真实角色名）
        target_button = _EnemyAttackTargetButton(self._team_names)
        self.enemy_attack_table.setCellWidget(row, 3, target_button)
        self.enemy_attack_table.setItem(row, 4, QTableWidgetItem("0"))

    def _remove_enemy_attack_row(self) -> None:
        """删除选中的敌方攻击行。"""
        row = self.enemy_attack_table.currentRow()
        if row >= 0:
            self.enemy_attack_table.removeRow(row)

    def _collect_enemy_attacks(self, *, for_simulator: bool = False) -> list[EnemyAttack]:
        """从敌方攻击配置表收集攻击列表。

        Args:
            for_simulator: False 时保留队伍槽位下标（用于配置存档）；
                           True 时转换为模拟器 characters 列表下标。
        """
        attacks: list[EnemyAttack] = []

        def _num(item: QTableWidgetItem | None, default: float = 0.0) -> float:
            try:
                return float(item.text().strip()) if item and item.text().strip() else default
            except ValueError:
                return default

        # UI 中目标按队伍槽位（0-3）选择；模拟器里的 target_indices 是
        # 已配置角色列表的下标，因此运行时做一次槽位 → 角色下标映射。
        slot_to_char_index: dict[int, int] = {}
        if for_simulator:
            configured_rows = [i for i, name in enumerate(self._team_names()) if name]
            slot_to_char_index = {slot: idx for idx, slot in enumerate(configured_rows)}

        for row in range(self.enemy_attack_table.rowCount()):
            total_av = _num(self.enemy_attack_table.item(row, 0))
            attack = _num(self.enemy_attack_table.item(row, 2))
            energy = _num(self.enemy_attack_table.item(row, 4))
            source_widget = self.enemy_attack_table.cellWidget(row, 1)
            source_index = source_widget.currentIndex() if isinstance(source_widget, QComboBox) else 0
            target_widget = self.enemy_attack_table.cellWidget(row, 3)
            selected_slots = (
                target_widget.target_indices()
                if isinstance(target_widget, _EnemyAttackTargetButton)
                else []
            )
            target_indices = (
                [slot_to_char_index[slot] for slot in selected_slots
                 if slot in slot_to_char_index]
                if for_simulator
                else selected_slots
            )
            attacks.append(EnemyAttack(
                total_av=total_av,
                source_enemy_index=max(0, min(4, source_index)),
                attack=attack,
                target_indices=target_indices,
                energy_recover=energy,
            ))
        return attacks

    # ── 读取配置 ─────────────────────────────────────

    def _collect_config(self) -> tuple[list[CharacterUnit], list[EnemyState], int, int, int, list[str]]:
        """从 UI 读取配置（命途/属性中文 → 英文）。

        Returns:
            (characters, enemies, sp, max_av, action_mode, warnings)
            warnings: 真实数据未就绪而回退预设的角色提示
        """
        characters = []
        warnings: list[str] = []

        def cell_text(row: int, col: int, default: str) -> str:
            item = self.team_table.item(row, col)
            return item.text().strip() if item else default

        def cell_float(row: int, col: int, default: float) -> float:
            try:
                return float(cell_text(row, col, "") or default)
            except ValueError:
                return default

        # 技能等级（全局）
        skill_levels = {
            SkillType.NORMAL: self.skill_level_normal_spin.value(),
            SkillType.SKILL: self.skill_level_skill_spin.value(),
            SkillType.ULTRA: self.skill_level_ultra_spin.value(),
            SkillType.TALENT: self.skill_level_talent_spin.value(),
            SkillType.MEMO_DNSKILL: self.skill_level_memo_spin.value(),
        }

        for row in range(self.team_table.rowCount()):
            name_item = self.team_table.item(row, 0)
            if not name_item or not name_item.text().strip():
                continue
            name = name_item.text().strip()
            uid = f"char{row+1}"
            # 命途/属性从行数据读取（表格不显示这两列，侧栏概览展示）
            row_data = name_item.data(Qt.UserRole)
            if isinstance(row_data, _RowCharData) and row_data.path:
                path = row_data.path
                elem = row_data.element
            else:
                path, elem = "Knight", "Fire"  # 兜底：存护/火

            if isinstance(row_data, _RowCharData) and row_data.loaded and row_data.skills_raw:
                # 真实角色：真实技能 + 真实面板（表格数值已自动填充，用户可改的为面板）
                char = build_character_unit(
                    unit_id=uid,
                    name=name,
                    path=path,
                    element=elem,
                    stats80=row_data.stats80,
                    skills_raw=row_data.skills_raw,
                    sp_need=row_data.sp_need,
                    skill_levels=skill_levels,
                    elation_skill_level=self.elation_skill_level_spin.value(),
                    char_id=row_data.char_id,
                    dmg_bonus=cell_float(row, COL_DMG_BONUS, 0.0),
                    initial_energy=row_data.sp_value,
                    # 行迹加成已包含在表格面板值中（作为 base_stats），不再重复叠加
                    skill_trees_raw=None,
                )
                # 用户手动编辑的面板数值覆盖真实基础值（模拟遗器加成）
                char.base_stats.hp_base = cell_float(row, COL_HP, char.base_stats.hp_base)
                char.base_stats.atk_base = cell_float(row, COL_ATK, char.base_stats.atk_base)
                char.base_stats.def_base = cell_float(row, COL_DEF, char.base_stats.def_base)
                char.base_stats.spd_base = cell_float(row, COL_SPD, char.base_stats.spd_base)
                char.base_stats.crit_rate = cell_float(row, COL_CRIT_RATE, char.base_stats.crit_rate)
                char.base_stats.crit_dmg = cell_float(row, COL_CRIT_DMG, char.base_stats.crit_dmg)
                char.base_stats.break_effect = cell_float(row, COL_BREAK_EFFECT, 0.0)
                char.base_stats.effect_res = cell_float(row, COL_EFFECT_RES, 0.0)
                char.base_stats.energy_regen = cell_float(row, COL_ENERGY_REGEN, 0.0)
                char.base_stats.effect_hit = cell_float(row, COL_EFFECT_HIT, 0.0)
                char.base_stats.outgoing_heal = cell_float(row, COL_OUTGOING_HEAL, 0.0)
                characters.append(char)
                continue

            # 预设角色（或真实数据未就绪回退）
            char = make_preset_character(
                uid, name, path, elem,
                hp=cell_float(row, COL_HP, 10000),
                atk=cell_float(row, COL_ATK, 1000),
                def_=cell_float(row, COL_DEF, 500),
                spd=cell_float(row, COL_SPD, 100),
                crit_rate=cell_float(row, COL_CRIT_RATE, 0.05),
                crit_dmg=cell_float(row, COL_CRIT_DMG, 0.5),
                break_effect=cell_float(row, COL_BREAK_EFFECT, 0.0),
                effect_res=cell_float(row, COL_EFFECT_RES, 0.0),
                energy_regen=cell_float(row, COL_ENERGY_REGEN, 0.0),
                effect_hit=cell_float(row, COL_EFFECT_HIT, 0.0),
                outgoing_heal=cell_float(row, COL_OUTGOING_HEAL, 0.0),
                dmg_bonus=cell_float(row, COL_DMG_BONUS, 0.0),
            )
            if isinstance(row_data, _RowCharData) and row_data.char_id:
                char.char_id = row_data.char_id
                warnings.append(f"{name}：真实数据未就绪，使用预设技能")
            characters.append(char)

        enemy_name = "木桩"
        enemy_count = self.enemy_count_spin.value()
        toughness = self.toughness_spin.value()
        weaknesses_zh = [
            w.strip() for w in self.weakness_edit.toPlainText().split(",") if w.strip()
        ]
        weaknesses = [ELEMENT_MAP_ZH_TO_EN.get(w, w) for w in weaknesses_zh]
        enemy_level = self.enemy_level_spin.value()
        non_weak_resist = self.non_weak_resist_spin.value() / 100.0
        # 弱点属性对所有怪物生效；弱点对应属性抗性 0，其余用非弱点抗性配置
        resistance = build_enemy_resistance(weaknesses, non_weak_resist)
        enemies = [
            EnemyState(
                unit_id=f"enemy{i + 1}",
                name=enemy_name,
                max_toughness=toughness,
                current_toughness=toughness,
                weakness_elements=weaknesses,
                level=enemy_level,
                speed=0.0,  # 木桩：速度 0，不进入行动队列（永不行动）
                resistance=resistance,
                max_hp=float(self.enemy_hp_spin.value()),
            )
            for i in range(enemy_count)
        ]

        return (
            characters, enemies, self.sp_spin.value(), self.turns_spin.value(),
            self.action_combo.currentIndex(), warnings,
        )

    # ── 交互模拟 ─────────────────────────────────────

    def _start_interactive(self) -> None:
        """初始化交互模拟。"""
        try:
            chars, enemies, initial_sp, max_av, _, warnings = self._collect_config()
        except Exception as e:
            QMessageBox.warning(self, "配置错误", f"读取配置失败: {e}")
            return

        if not chars:
            QMessageBox.warning(self, "配置错误", "至少需要一个角色")
            return
        if warnings:
            QMessageBox.information(self, "提示", "\n".join(warnings))

        self.characters = chars
        self.enemies = enemies

        self._interactive_sim = BattleSimulator(
            characters=chars,
            enemies=enemies,
            max_av=float(max_av),
            initial_sp=initial_sp,
            enemy_attacks=self._collect_enemy_attacks(for_simulator=True),
        )
        self._interactive_sim.setup()
        # 战斗开始（含秘技进战效果）后停在待推进阶段：按空格才轮到第一个行动者
        self._interactive_snapshots = [self._interactive_sim.snapshot()]
        self._interactive_old_logs = []
        self._interactive_active = True

        # 重建能量图标
        self._rebuild_energy_orbs()
        # 重建敌方目标选择按钮（默认选中第一个）
        self._rebuild_enemy_targets()

        # 启用操作按钮
        self.btn_start_interactive.setText("↻ 重新开始")
        self.btn_rewind.setEnabled(True)
        self.interactive_log_table.setRowCount(0)
        self._update_interactive_display()

    def _interactive_step(self, skill_type: SkillType) -> None:
        """交互模式：当前角色执行普攻/战技。"""
        if not self._interactive_sim or not self._interactive_active:
            return
        sim = self._interactive_sim
        if sim.total_av >= sim.max_av or not sim.action_queue.entries:
            return

        actor = sim.action_queue.next_actor()
        # 怪物/阿哈/倒计时不在此处理
        if sim.is_auto_unit(actor):
            return

        # 待推进状态按 Q/E：视为"推进 + 行动"——先推进到下个行动者位置再释放技能
        if sim.pending_av_actor != actor.unit_id:
            sim.advance_av()

        char = sim._get_character(actor.unit_id)
        if char is None:
            return

        # 模块技能限制检查（如千冶未开启结界/生命 ≤1 时无法施放战技）：弹窗提示
        if skill_type == SkillType.SKILL:
            module = sim.char_modules.get(char.unit_id)
            if module is not None:
                reason = module.skill_deny_reason(sim, char)
                if reason:
                    QMessageBox.warning(self, "无法施放战技", reason)
                    return

        # SP 检查：战技消耗 SP 时才需要（千冶等战技不耗 SP 的角色不受限）
        skill_for_sp = next(
            (s for s in char.skills.values() if s.skill_type == SkillType.SKILL), None
        )
        if (
            skill_type == SkillType.SKILL
            and skill_for_sp is not None
            and skill_for_sp.sp_cost > 0
            and not sim.sp.can_consume(1)
        ):
            QMessageBox.warning(self, "战技点不足", "当前 SP 为 0，无法使用战技")
            return

        target_id = self._selected_target_id()
        action = PlayerAction(
            unit_id=char.unit_id,
            skill_type=skill_type,
            target_id=target_id,
        )

        log = sim.step(action)
        if log is None:
            self._interactive_active = False
        self._interactive_snapshots.append(sim.snapshot())
        self._interactive_old_logs = []
        self._update_interactive_display()

    def _interactive_advance(self) -> None:
        """交互模式：推进怪物/阿哈自动行动。"""
        if not self._interactive_sim or not self._interactive_active:
            return
        sim = self._interactive_sim
        if sim.total_av >= sim.max_av or not sim.action_queue.entries:
            return

        actor = sim.action_queue.next_actor()
        if sim.pending_av_actor != actor.unit_id:
            # 待推进（战斗开始/任意行动完成）：推进时间到下个行动者位置
            sim.advance_av()
            # 怪物/阿哈/倒计时无需选择技能：自动执行其行动并回到待推进状态
            actor = sim.action_queue.next_actor()
            if sim.is_auto_unit(actor):
                log = sim.step()
                if log is None:
                    self._interactive_active = False
        elif sim.is_auto_unit(actor):
            # 已轮到怪物/阿哈/倒计时（异常状态，正常流程推进后自动行动）：执行其行动
            log = sim.step()
            if log is None:
                self._interactive_active = False
        else:
            return  # 已轮到角色：用 Q/E 行动，空格无操作
        self._interactive_snapshots.append(sim.snapshot())
        self._interactive_old_logs = []
        self._update_interactive_display()

    def _interactive_ultra(self, char_index: int) -> None:
        """交互模式：插队释放终结技。"""
        if not self._interactive_sim or not self._interactive_active:
            return
        sim = self._interactive_sim

        log = sim.execute_ultra(char_index, target_id=self._selected_target_id())
        if log is None:
            QMessageBox.information(
                self, "提示",
                f"角色 {char_index + 1} 能量不足或无终结技"
            )
            return

        self._interactive_snapshots.append(sim.snapshot())
        self._interactive_old_logs = []
        self._update_interactive_display()

    def _interactive_rewind_to_selected(self) -> None:
        """回溯到选中的日志行。"""
        if not self._interactive_sim:
            return

        row = self.interactive_log_table.currentRow()
        if row < 0:
            QMessageBox.warning(self, "提示", "请先在日志中选择一个回合")
            return

        sim = self._interactive_sim
        # row 对应 sim.logs[row]（如果 row < len(sim.logs)）
        # 如果 row >= len(sim.logs)，说明选中的是灰显的旧记录，不支持回溯
        if row >= len(sim.logs):
            QMessageBox.warning(self, "提示", "不能回溯到已失效的旧记录，请选择有效的回合")
            return
        if row >= len(self._interactive_snapshots):
            return

        # 保存旧记录（灰显）
        self._interactive_old_logs = list(sim.logs[row:])
        # 恢复到第 row 步之前的状态
        sim.restore(self._interactive_snapshots[row])
        # 截断快照
        self._interactive_snapshots = self._interactive_snapshots[:row + 1]
        self._interactive_active = True

        self._update_interactive_display()

    def _update_interactive_display(self) -> None:
        """更新交互模式的状态栏、日志表格和按钮状态。"""
        if not self._interactive_sim:
            return

        sim = self._interactive_sim

        # 更新状态栏
        battle_ended = False
        if not sim.enemies:
            status = (
                f"战斗结束！  全部敌人已死亡  总AV: {sim.total_av:.1f}/{sim.max_av:.0f}  "
                f"总伤害: {sim.total_damage:.0f}"
            )
            self._interactive_active = False
            battle_ended = True
        elif sim.total_av >= sim.max_av:
            status = (
                f"战斗结束！  总AV: {sim.total_av:.1f}/{sim.max_av:.0f}  "
                f"总伤害: {sim.total_damage:.0f}  阿哈时刻: {sim.aha_count}次"
            )
            self._interactive_active = False
            battle_ended = True
        elif not sim.action_queue.entries:
            status = "行动队列为空，战斗结束"
            self._interactive_active = False
            battle_ended = True
        else:
            actor = sim.action_queue.next_actor()
            all_energy = "  |  ".join(
                f"{c.name}: {c.energy:.0f}" for c in sim.characters
            )
            laugh_info = ""
            elation_chars = [c for c in sim.characters if c.is_elation]
            if elation_chars:
                total_laugh = sum(c.laugh_point for c in elation_chars)
                laugh_info = f"  笑点: {total_laugh:.0f}"

            if sim.pending_av_actor != actor.unit_id:
                # 待推进：战斗开始（秘技进战）/行动完成，时间停在当前位置，按空格轮到下个行动者
                status = (
                    f"按空格推进到下个行动者，或按Q/E推进到下个行动者并自动尝试释放普攻/战技\n"
                    f"总AV: {sim.total_av:.1f}/{sim.max_av:.0f}"
                    f"{laugh_info}"
                )
            else:
                if actor.is_monster:
                    actor_type = "怪物"
                elif actor.unit_id == "__aha__":
                    actor_type = "阿哈"
                elif actor.unit_id in sim.countdown_units:
                    actor_type = "倒计时"
                else:
                    actor_type = "角色"
                status = (
                    f"当前行动者: [{actor.name}]（{actor_type}）  "
                    f"总AV: {sim.total_av:.1f}/{sim.max_av:.0f}"
                    f"{laugh_info}\n"
                    f"全队能量: {all_energy}"
                )

        self.interactive_status_label.setText(status)

        # 战斗结束时：构建结果并填充各结果 Tab
        if battle_ended:
            self._interactive_fill_result_tabs()

        # 更新 SP 图标
        self.sp_indicator.set_sp(sim.sp.current)

        # 更新角色能量图标
        self._update_energy_orbs()

        # 刷新敌方目标按钮文字（击破标记）
        self._update_enemy_targets_display()

        # 更新日志表格
        logs = sim.logs
        old_logs = self._interactive_old_logs
        total_rows = len(logs) + len(old_logs)
        self.interactive_log_table.setRowCount(total_rows)

        for i, log in enumerate(logs):
            self._set_interactive_log_row(i, log, is_old=False)
        for i, log in enumerate(old_logs):
            self._set_interactive_log_row(len(logs) + i, log, is_old=True)

        # 更新按钮状态
        is_active = self._interactive_active
        self.btn_advance.setEnabled(False)
        self.btn_normal.setEnabled(False)
        self.btn_skill.setEnabled(False)
        # 终结技按钮：仅在能量满时启用
        for i, btn in enumerate(self.btn_ultras):
            can_ultra = (
                is_active
                and i < len(sim.characters)
                and sim.characters[i].energy >= sim._get_energy_cost(
                    sim.characters[i], SkillType.ULTRA
                )
            )
            btn.setEnabled(can_ultra)

        if is_active and sim.action_queue.entries:
            actor = sim.action_queue.next_actor()
            if sim.pending_av_actor != actor.unit_id:
                # 待推进（战斗开始 / 行动完成）：按推进键轮到下个行动者
                self.btn_advance.setEnabled(True)
                self.btn_advance.setText("推进（空格）")
            elif sim.is_auto_unit(actor):
                # 轮到怪物/阿哈/倒计时：按推进键执行其行动
                self.btn_advance.setEnabled(True)
                self.btn_advance.setText("行动（空格）")
            else:
                self.btn_normal.setEnabled(True)
                # 战技按钮：SP 不足时禁用（战技不耗 SP 的角色不受限）
                actor_char = sim._get_character(actor.unit_id)
                skill_for_sp = (
                    next(
                        (s for s in actor_char.skills.values() if s.skill_type == SkillType.SKILL),
                        None,
                    )
                    if actor_char is not None
                    else None
                )
                self.btn_skill.setEnabled(
                    sim.sp.can_consume(1)
                    or (skill_for_sp is not None and skill_for_sp.sp_cost <= 0)
                )

        # 侧栏：未来 300 AV 行动顺序实时预览
        self._update_action_preview()

    def _action_entry_kind(self, sim: BattleSimulator, actor) -> tuple[str, str]:
        """判断行动条条目的业务类型与展示颜色。"""
        if actor.unit_id == "__aha__":
            return "阿哈时刻", Colors.GOLD
        if actor.unit_id in sim._enemy_attack_map:
            return "敌方攻击", Colors.RED
        if actor.unit_id in sim.countdown_units:
            return "倒计时", Colors.PURPLE
        if actor.is_monster:
            return "怪物", Colors.CYAN
        return "角色", Colors.GREEN

    def _predict_action_timeline(self, sim: BattleSimulator) -> list[dict]:
        """基于当前行动队列静态预测未来 300 AV 内的行动顺序。

        说明：这是 UI 层预估，不会修改模拟器状态。角色技能带来的
        速度变化/推拉条/插队终结技需要实际结算后才会反映到下一次预览。
        """
        if not sim.action_queue.entries or sim.total_av >= sim.max_av:
            return []

        queue = copy.deepcopy(sim.action_queue)
        actor = queue.next_actor()
        window_end = min(sim.total_av + PREVIEW_AV_WINDOW, sim.max_av)

        # 已推进到当前行动者时，下一次行动就是“现在”（相对 +0）
        if sim.pending_av_actor == actor.unit_id:
            total_av = sim.total_av
        else:
            total_av = sim.total_av + actor.current_av

        items: list[dict] = []
        safety = 0
        while total_av <= window_end + 1e-9 and safety < 60:
            kind, color = self._action_entry_kind(sim, actor)
            items.append({
                "unit_id": actor.unit_id,
                "name": actor.name,
                "kind": kind,
                "color": color,
                "delta_av": total_av - sim.total_av,
                "total_av": total_av,
            })

            queue.advance()
            # 一次性行动（敌方攻击调度/倒计时）行动后离场，预测中同步移除
            if (
                actor.unit_id in sim._enemy_attack_map
                or actor.unit_id in sim.countdown_units
            ):
                queue.remove(actor.unit_id)

            if not queue.entries:
                break
            actor = queue.next_actor()
            total_av += max(0.0, actor.current_av)
            safety += 1

        return items

    def _character_avatar_icon(self, char) -> QIcon:
        """构造行动预览用的角色头像图标。

        真实角色优先读取本地头像缓存；没有本地头像（如预设角色）时，
        生成元素配色 + 首字的圆形占位头像。
        """
        if char is not None and char.char_id:
            icon_path = ICONS_DIR / f"character_{char.char_id}.webp"
            if icon_path.exists():
                pix = _load_character_icon(char.char_id)
                if not pix.isNull():
                    return QIcon(
                        pix.scaled(20, 20, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    )

        pixmap = QPixmap(20, 20)
        pixmap.fill(QColor(0, 0, 0, 0))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        color = ELEMENT_COLORS.get(char.element, Colors.CYAN) if char else Colors.BG_HOVER
        painter.setBrush(QColor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(0, 0, 20, 20)
        painter.setPen(QColor(Colors.BG_DEEPEST))
        font = QFont()
        font.setPixelSize(11)
        font.setBold(True)
        painter.setFont(font)
        painter.drawText(
            pixmap.rect(),
            Qt.AlignCenter,
            char.name[:1] if char and char.name else "?",
        )
        painter.end()
        return QIcon(pixmap)

    def _update_action_preview(self) -> None:
        """更新侧栏“未来 300 AV 行动”预览表。"""
        table = self.action_preview_table
        table.clearSpans()
        table.setRowCount(0)

        sim = self._interactive_sim
        if sim is None:
            self.preview_range_label.setText("开始交互模拟后显示")
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("—"))
            placeholder = QTableWidgetItem("等待开始交互模拟")
            placeholder.setForeground(QColor(Colors.TEXT_DISABLED))
            table.setItem(0, 1, placeholder)
            return

        if not self._interactive_active:
            self.preview_range_label.setText("战斗已结束" if sim else "暂无预览")
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("—"))
            placeholder = QTableWidgetItem("暂无后续行动")
            placeholder.setForeground(QColor(Colors.TEXT_DISABLED))
            table.setItem(0, 1, placeholder)
            return

        window_end = min(sim.total_av + PREVIEW_AV_WINDOW, sim.max_av)
        self.preview_range_label.setText(
            f"总AV {sim.total_av:.1f} → {window_end:.1f}"
        )

        items = self._predict_action_timeline(sim)
        if not items:
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("—"))
            placeholder = QTableWidgetItem("暂无后续行动")
            placeholder.setForeground(QColor(Colors.TEXT_DISABLED))
            table.setItem(0, 1, placeholder)
            return

        table.setRowCount(len(items))
        for i, item in enumerate(items):
            is_next = i == 0

            seq = QTableWidgetItem(f"{i + 1:02d}")
            seq.setTextAlignment(Qt.AlignCenter)
            seq.setForeground(QColor(Colors.GOLD if is_next else Colors.TEXT_SECONDARY))

            name_item = QTableWidgetItem(item["name"])
            name_item.setForeground(QColor(item["color"]))
            if item["kind"] == "角色":
                char = sim._get_character(item["unit_id"])
                icon = self._character_avatar_icon(char)
                if not icon.isNull():
                    name_item.setIcon(icon)
            name_item.setToolTip(
                f"{item['kind']} · 预计总AV {item['total_av']:.1f}"
            )

            delta_text = "现在" if item["delta_av"] < 0.001 else f"+{item['delta_av']:.0f}"
            delta_item = QTableWidgetItem(delta_text)
            delta_item.setTextAlignment(Qt.AlignCenter)
            delta_item.setForeground(QColor(Colors.GOLD if is_next else Colors.CYAN))

            total_item = QTableWidgetItem(f"{item['total_av']:.1f}")
            total_item.setTextAlignment(Qt.AlignCenter)
            total_item.setForeground(QColor(Colors.TEXT_PRIMARY))

            table.setItem(i, 0, seq)
            table.setItem(i, 1, name_item)
            table.setItem(i, 2, delta_item)
            table.setItem(i, 3, total_item)

            if is_next:
                bg = QColor(Colors.BG_SELECTED)
                for col in range(4):
                    cell = table.item(i, col)
                    if cell is not None:
                        cell.setBackground(bg)
                        font = cell.font()
                        font.setBold(True)
                        cell.setFont(font)

    def _rebuild_energy_orbs(self) -> None:
        """根据当前队伍重建能量图标（含角色头像）。"""
        # 清空旧图标
        while self.energy_orbs_container.count():
            item = self.energy_orbs_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._energy_orbs.clear()

        if not self._interactive_sim:
            return

        for i, char in enumerate(self._interactive_sim.characters):
            orb = EnergyOrbWidget(
                name=char.name,
                max_energy=char.base_stats.energy_max,
            )
            orb.set_energy(char.energy)
            orb.set_hp(char.current_hp, char.final_stats().hp)
            # 加载角色头像（若有 nanoka 角色 ID）
            if char.char_id:
                pix = _load_character_icon(char.char_id)
                orb.set_avatar(pix)
            # 点击头像查看角色 buff 列表
            orb.clicked.connect(lambda idx=i: self._show_char_buffs(idx))
            self._energy_orbs.append(orb)
            self.energy_orbs_container.addWidget(orb)

    # ── 敌方目标选择 ─────────────────────────────────

    def _rebuild_enemy_targets(self) -> None:
        """根据当前敌人数量重建敌方目标卡片（默认选中第一个）。"""
        # 清空旧卡片与布局
        while self.enemy_target_layout.count():
            item = self.enemy_target_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._enemy_target_buttons.clear()

        sim = self._interactive_sim
        if not sim or not sim.enemies:
            self._selected_enemy_id = ""
            return

        for enemy in sim.enemies:
            card = EnemyTargetWidget(enemy.unit_id, enemy.name)
            card.clicked.connect(self._on_enemy_target_clicked)
            card.double_clicked.connect(self._on_enemy_target_double_clicked)
            card.set_hp(enemy.current_hp, enemy.max_hp)
            card.set_toughness(enemy.current_toughness, enemy.max_toughness, enemy.is_broken)
            self._enemy_target_buttons.append(card)
            self.enemy_target_layout.addWidget(card)

        # 默认选中第一个
        self._selected_enemy_id = sim.enemies[0].unit_id
        self._enemy_target_buttons[0].set_checked(True)

    def _on_enemy_target_clicked(self, unit_id: str) -> None:
        """点击敌人卡片：切换选中。"""
        self._selected_enemy_id = unit_id
        for card in self._enemy_target_buttons:
            card.set_checked(card.unit_id == unit_id)

    def _on_enemy_target_double_clicked(self, unit_id: str) -> None:
        """双击敌人卡片：弹出敌方目标当前 buff / 状态。"""
        self._show_enemy_buffs(unit_id)

    def _show_enemy_buffs(self, unit_id: str) -> None:
        """显示敌方目标的当前 buff / 状态（减防、易伤、buff 列表）。"""
        sim = self._interactive_sim
        if not sim:
            return
        enemy = next((e for e in sim.enemies if e.unit_id == unit_id), None)
        if enemy is None:
            return

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{enemy.name} 的 Buff")
        dlg.resize(560, 420)
        layout = QVBoxLayout(dlg)

        # 基本状态
        broken_zh = "是" if enemy.is_broken else "否"
        state = QLabel(
            f"生命 {enemy.current_hp:,.0f}/{enemy.max_hp:,.0f}"
            f"   |   韧性 {enemy.current_toughness:.0f}/{enemy.max_toughness:.0f}"
            f"   |   击破 {broken_zh}   |   等级 {enemy.level}"
        )
        state.setWordWrap(True)
        state.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: 600;")
        layout.addWidget(state)

        # buff / debuff 列表（名称 + 剩余回合右对齐 + 描述，逐条展示不合并数值）
        parts: list[str] = []
        for buff in enemy.buff_mgr.buffs:
            left = f"<b>{buff.name}</b>"
            if buff.max_stacks > 1 or buff.current_stacks > 1:
                left += f"（{buff.current_stacks}/{buff.max_stacks}）"
            turns = self._buff_turns_text(buff)
            if turns:
                head = (
                    f'<table width="100%" cellspacing="0" cellpadding="0" border="0">'
                    f"<tr><td>{left}</td>"
                    f'<td align="right"><font color="{Colors.TEXT_SECONDARY}">{turns}</font></td>'
                    f"</tr></table>"
                )
            else:
                head = left
            parts.append(f"{head}<br>{self._buff_desc(buff)}")
        # 各角色模块施加在该敌人身上的 debuff（饲饵/煞火缠身/结界等，逐条展示）
        for module in sim.char_modules.values():
            for name, desc in module.enemy_buffs(sim, enemy):
                parts.append(f"<b>{name}</b><br>{desc}")

        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFrameShape(QFrame.NoFrame)
        text_edit.setStyleSheet(
            f"background-color: {Colors.BG_PANEL}; color: {Colors.TEXT_PRIMARY};"
            f" border: 1px solid {Colors.BORDER}; border-radius: 5px;"
        )
        text_edit.setHtml("<br><br>".join(parts) if parts else "无 buff")
        layout.addWidget(text_edit, stretch=1)

        close_btn = QPushButton("关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        dlg.exec()

    def _selected_target_id(self) -> str:
        """返回当前选中的敌方目标 unit_id（无敌人返回空串）。

        若选中的敌人已死亡离场，回退到第一个存活敌人。
        """
        sim = self._interactive_sim
        if not sim or not sim.enemies:
            return ""
        if self._selected_enemy_id and any(
            e.unit_id == self._selected_enemy_id for e in sim.enemies
        ):
            return self._selected_enemy_id
        return sim.enemies[0].unit_id

    def _update_enemy_targets_display(self) -> None:
        """刷新敌方目标卡片（血条/韧性条/击破标记；敌人死亡则重建）。"""
        sim = self._interactive_sim
        if not sim:
            return
        card_ids = [c.unit_id for c in self._enemy_target_buttons]
        sim_ids = [e.unit_id for e in sim.enemies]
        if card_ids != sim_ids:
            self._rebuild_enemy_targets()
            return
        for i, enemy in enumerate(sim.enemies):
            if i >= len(self._enemy_target_buttons):
                continue
            card = self._enemy_target_buttons[i]
            card.set_hp(enemy.current_hp, enemy.max_hp)
            card.set_toughness(enemy.current_toughness, enemy.max_toughness, enemy.is_broken)

    def _update_energy_orbs(self) -> None:
        """更新所有能量图标的数值和状态。"""
        if not self._interactive_sim:
            return
        sim = self._interactive_sim

        # 当前行动者 unit_id 与待命（虚线）行动者
        active_unit_id = ""
        pending_unit_id = ""
        if sim.action_queue.entries:
            actor = sim.action_queue.next_actor()
            if sim.pending_av_actor == actor.unit_id:
                active_unit_id = actor.unit_id  # 已轮到该行动者（实线）
            elif sim.pending_av_actor:
                # 待推进：刚行动完的角色实线高亮（行动后插队窗口），
                # 下个行动的角色虚线高亮（即将轮到）
                active_unit_id = sim.pending_av_actor
                pending_unit_id = actor.unit_id
            else:
                # 战斗开始待推进：下个行动的角色虚线高亮
                pending_unit_id = actor.unit_id

        for i, orb in enumerate(self._energy_orbs):
            if i >= len(sim.characters):
                continue
            char = sim.characters[i]
            orb.set_max_energy(char.base_stats.energy_max)
            orb.set_energy(char.energy)
            orb.set_hp(char.current_hp, char.final_stats().hp)
            orb.set_active(char.unit_id == active_unit_id)
            orb.set_pending(char.unit_id == pending_unit_id)
            # 充能指示：圆点（不死途追击充能）/ 文字（千冶天赋充能 "6/9"）
            module = sim.char_modules.get(char.unit_id)
            charge = getattr(module, "charge", None)
            if charge is not None:
                style = getattr(module, "CHARGE_STYLE", "dots")
                # 充能上限：模块显式声明（不死途 3、千冶 9），缺失时按样式兜底
                charge_max = int(getattr(
                    module, "CHARGE_MAX", 3 if style == "dots" else 9
                ))
                if style == "text":
                    orb.set_charge_text(int(charge), charge_max)
                else:
                    orb.set_charge(charge, charge_max)
            else:
                orb.set_charge(None)

    # ── 角色 buff 查看 ─────────────────────────────────

    # stat 字段 → 中文描述
    _STAT_NAMES_ZH = {
        "hp_pct": "生命值提升", "atk_pct": "攻击力提升", "def_pct": "防御力提升",
        "spd_pct": "速度提升", "crit_rate": "暴击率提升", "crit_dmg": "暴击伤害提升",
        "dmg_bonus": "伤害提高", "break_effect": "击破特攻提升",
        "effect_hit": "效果命中提升", "effect_res": "效果抵抗提升",
        "energy_regen": "能量恢复效率提升", "outgoing_heal": "治疗量加成提升",
        "res_pen": "我方全体目标全属性抗性穿透提高",
        "hp_flat": "生命值提升", "atk_flat": "攻击力提升", "def_flat": "防御力提升",
        "spd_flat": "速度提升",
        "good_joke": "好活当赏", "laugh_point": "笑点",
        "elation_dmg": "欢愉度提升", "laugh_bonus": "增笑提升",
    }
    # 百分比语义字段（value 为小数，显示为 %）
    _PCT_BUFF_STATS = {
        "hp_pct", "atk_pct", "def_pct", "spd_pct", "crit_rate", "crit_dmg",
        "dmg_bonus", "break_effect", "effect_hit", "effect_res",
        "energy_regen", "outgoing_heal", "res_pen", "good_joke",
        "elation_dmg", "laugh_bonus",
    }

    def _buff_desc(self, buff) -> str:
        """Buff 文字描述（数值包含在描述中，如"攻击力提升 20%"）。"""
        value = buff.value * buff.current_stacks
        if buff.stat in self._PCT_BUFF_STATS:
            text = f"{value * 100:.1f}%"
        else:
            text = f"{value:.0f}"
        stat_zh = self._STAT_NAMES_ZH.get(buff.stat, buff.stat)
        return f"{stat_zh} {text}"

    def _buff_turns_text(self, buff) -> str:
        """回合制 buff 的剩余回合文本（非回合制时效返回空串）。"""
        if buff.duration_type in (
            BuffDuration.TURNS_SELF_START,
            BuffDuration.TURNS_SELF_END,
        ):
            return f"剩余 {buff.duration_count} 回合"
        return ""

    def _buffs_html(self, char: CharacterUnit, char_index: int) -> str:
        """生成 buff 列表 HTML（名称加粗、剩余回合右对齐、描述换行）。

        包含：BuffManager buff、模块资源（婪酣等）、额外能力（行迹被动）。
        """
        parts: list[str] = []

        def append(name: str, desc: str, stacks: str = "", turns: str = "") -> None:
            left = f"<b>{name}</b>"
            if stacks:
                left += f"（{stacks}）"
            if turns:
                head = (
                    f'<table width="100%" cellspacing="0" cellpadding="0" border="0">'
                    f"<tr><td>{left}</td>"
                    f'<td align="right"><font color="{Colors.TEXT_SECONDARY}">{turns}</font></td>'
                    f"</tr></table>"
                )
            else:
                head = left
            parts.append(f"{head}<br>{desc}")

        # Buff（来自 BuffManager）
        for buff in char.buff_mgr.buffs:
            stacks = ""
            if buff.max_stacks > 1 or buff.current_stacks > 1:
                stacks = f"{buff.current_stacks}/{buff.max_stacks}"
            append(buff.name, self._buff_desc(buff), stacks, self._buff_turns_text(buff))

        # 模块资源（如不死途婪酣层数）
        module = self._interactive_sim.char_modules.get(char.unit_id)
        if module is not None:
            greed = getattr(module, "greed", None)
            if greed is not None:
                append("婪酣", f"婪酣层数 {greed}", f"{greed}")

        # 额外能力：自身全部显示；他人仅光环（"我方目标"）可见
        for src_row, source, name, desc, is_aura in self._extra_abilities():
            if src_row != char_index and not is_aura:
                continue
            label = name if src_row == char_index else f"{name}（{source}）"
            append(label, desc)

        return "<br><br>".join(parts) if parts else "无 buff"

    def _extra_abilities(self) -> list[tuple[int, str, str, str, bool]]:
        """收集队伍所有角色的额外能力（行迹 point_type=3）。

        返回 [(来源行号, 来源角色名, 能力名, 插值后描述, 是否全队光环)]。
        光环类效果（描述含"我方目标/我方"，如"头狼"我方暴伤）对所有我方角色可见；
        自身效果（如"影肢"追加攻击加成）仅显示在来源角色自身。
        """
        result: list[tuple[int, str, str, str, bool]] = []
        for row in range(self.team_table.rowCount()):
            name_item = self.team_table.item(row, 0)
            if name_item is None:
                continue
            row_data = name_item.data(Qt.UserRole)
            if not isinstance(row_data, _RowCharData):
                continue
            source = row_data.name or name_item.text().strip()
            for group in row_data.skill_trees_raw.values():
                if not isinstance(group, dict):
                    continue
                for point in group.values():
                    if not isinstance(point, dict):
                        continue
                    if point.get("point_type") != 3 or not point.get("point_name"):
                        continue
                    desc = clean_text(point.get("point_desc"), point.get("param_list"))
                    if desc:
                        is_aura = "我方目标" in desc or "我方" in desc
                        result.append((row, source, point.get("point_name", ""), desc, is_aura))
        return result

    def _char_base_stats(self, char_index: int) -> BaseStats | None:
        """角色装备光锥后的基础值（无遗器/行迹加成）。

        数据来源：行数据中保存的详情 stats80 + freesr 光锥基础；
        无真实数据（预设角色）返回 None。
        """
        name_item = self.team_table.item(char_index, 0)
        if name_item is None:
            return None
        row_data = name_item.data(Qt.UserRole)
        if not isinstance(row_data, _RowCharData) or not row_data.stats80:
            return None
        base = convert_stats80(row_data.stats80)
        if row_data.lightcone_stats80:
            lc = lightcone_base_stats(row_data.lightcone_stats80)
            base.hp_base += lc.hp_base
            base.atk_base += lc.atk_base
            base.def_base += lc.def_base
        return base

    def _show_char_buffs(self, char_index: int) -> None:
        """点击角色头像：弹出角色 buff 列表（含模块资源如婪酣）。"""
        if not self._interactive_sim or char_index >= len(self._interactive_sim.characters):
            return
        char = self._interactive_sim.characters[char_index]

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{char.name} 的 Buff")
        dlg.resize(600, 420)
        layout = QVBoxLayout(dlg)

        # 主要面板属性（生命/攻击/防御/速度/暴击率/暴击伤害）
        final = char.final_stats()
        base = self._char_base_stats(char_index)

        def _fmt_pair(value: float, base_value: float, pct: bool = False) -> str:
            """基础 + 增量 = 最终 或 仅最终。"""
            if base is not None:
                fmt = lambda v: f"{v * 100:.1f}%" if pct else f"{v:.1f}" if base_value < 100 else f"{v:.0f}"
                return f"{fmt(base_value)} + {fmt(value - base_value)} = {fmt(value)}"
            return f"{value * 100:.1f}%" if pct else f"{value:.1f}"

        def _stats_text(show_base: bool) -> str:
            if show_base and base is not None:
                return (
                    f"生命 {_fmt_pair(final.hp, base.hp_base)}"
                    f"   |   攻击 {_fmt_pair(final.atk, base.atk_base)}"
                    f"   |   防御 {_fmt_pair(final.defense, base.def_base)}\n"
                    f"速度 {_fmt_pair(final.spd, base.spd_base)}"
                    f"   |   暴击率 {_fmt_pair(final.crit_rate, base.crit_rate, pct=True)}"
                    f"   |   暴击伤害 {_fmt_pair(final.crit_dmg, base.crit_dmg, pct=True)}"
                )
            return (
                f"生命 {final.hp:.0f}   |   攻击 {final.atk:.0f}   |   防御 {final.defense:.0f}\n"
                f"速度 {final.spd:.1f}   |   暴击率 {final.crit_rate * 100:.1f}%"
                f"   |   暴击伤害 {final.crit_dmg * 100:.1f}%"
            )

        main_stats = QLabel(_stats_text(False))  # 默认仅最终值
        main_stats.setWordWrap(True)
        main_stats.setStyleSheet(f"color: {Colors.TEXT_PRIMARY}; font-weight: 600;")
        layout.addWidget(main_stats)

        # 显示属性基础值开关：开启显示"基础 + 增量 = 最终"，关闭仅最终
        base_check = QCheckBox("显示属性基础值")
        base_check.setCursor(Qt.PointingHandCursor)
        base_check.setEnabled(base is not None)  # 无真实基础数据（预设角色）时禁用
        base_check.toggled.connect(lambda on: main_stats.setText(_stats_text(on)))
        layout.addWidget(base_check)

        # 展开详情：其它属性（默认隐藏）
        detail_stats = QLabel(
            f"击破特攻 {final.break_effect * 100:.1f}%"
            f"   |   效果命中 {final.effect_hit * 100:.1f}%"
            f"   |   效果抵抗 {final.effect_res * 100:.1f}%\n"
            f"能量恢复效率 {final.energy_regen * 100:.1f}%"
            f"   |   治疗量加成 {final.outgoing_heal * 100:.1f}%"
            f"   |   属性增伤 {final.dmg_bonus * 100:.1f}%\n"
            f"能量 {char.energy:.0f}/{final.energy_max:.0f}"
        )
        detail_stats.setWordWrap(True)
        detail_stats.setStyleSheet(f"color: {Colors.TEXT_SECONDARY};")
        detail_stats.hide()
        layout.addWidget(detail_stats)

        toggle_btn = QPushButton("▸ 展开详情")
        toggle_btn.setCheckable(True)
        toggle_btn.setCursor(Qt.PointingHandCursor)

        def _toggle_detail(checked: bool) -> None:
            detail_stats.setVisible(checked)
            toggle_btn.setText("▾ 收起详情" if checked else "▸ 展开详情")

        toggle_btn.toggled.connect(_toggle_detail)
        layout.addWidget(toggle_btn, alignment=Qt.AlignLeft)

        # Buff 列表（富文本：名称加粗、层数括号、描述换行）
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setFrameShape(QFrame.NoFrame)
        text_edit.setStyleSheet(
            f"background-color: {Colors.BG_PANEL}; color: {Colors.TEXT_PRIMARY};"
            f" border: 1px solid {Colors.BORDER}; border-radius: 5px;"
        )
        text_edit.setHtml(self._buffs_html(char, char_index))
        layout.addWidget(text_edit, stretch=1)

        close_btn = QPushButton("关闭")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        dlg.exec()

    def _interactive_fill_result_tabs(self) -> None:
        """交互模拟战斗结束后，构建结果并填充各结果 Tab。"""
        if not self._interactive_sim:
            return
        sim = self._interactive_sim

        # 判断结束原因
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

        result = BattleResult(
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

        self._last_result = result
        self._display_result(result)

    def _set_interactive_log_row(self, row: int, log, is_old: bool) -> None:
        """设置交互日志表格的一行。"""
        notes = log.notes
        if log.enemy_broken:
            notes = "【击破】" + notes

        items = [
            str(row + 1),
            f"{log.av:.1f}",
            f"{log.total_av:.1f}",
            log.actor_name,
            ACTION_NAMES_ZH.get(log.action_type, log.action_type),
            ", ".join(f"{d:.0f}" for d in log.damages) if log.damages else "-",
            f"{log.total_damage:.0f}",
            notes,
        ]
        for col, text in enumerate(items):
            item = QTableWidgetItem(text)
            if is_old:
                item.setForeground(QColor(Colors.TEXT_DISABLED))
            self.interactive_log_table.setItem(row, col, item)

    def eventFilter(self, obj, event) -> bool:
        """应用级按键拦截：交互模式下焦点控件不消费操作键。

        仅拦截交互操作键（Q/E/空格/回车/1-4），其余按键照常传递；
        有模态对话框（如 QMessageBox）时不拦截。
        """
        if (
            event.type() == QEvent.KeyPress
            and self._interactive_active
            and self._interactive_sim
            and self.tabs.currentIndex() == 1
            and QApplication.activeModalWidget() is None
            and event.key() in (
                Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter,
                Qt.Key_E, Qt.Key_Q,
                Qt.Key_1, Qt.Key_2, Qt.Key_3, Qt.Key_4,
            )
        ):
            self.keyPressEvent(event)
            return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event) -> None:
        """键盘事件处理（仅在交互模拟 Tab 激活时生效）。"""
        if not self._interactive_active or not self._interactive_sim:
            super().keyPressEvent(event)
            return

        # 仅在交互模拟 Tab（索引 1）时处理
        if self.tabs.currentIndex() != 1:
            super().keyPressEvent(event)
            return

        sim = self._interactive_sim
        if not sim.action_queue.entries:
            super().keyPressEvent(event)
            return

        key = event.key()
        actor = sim.action_queue.next_actor()
        is_char = not sim.is_auto_unit(actor)

        # 终结技插队（任意时刻）
        if key == Qt.Key_1:
            self._interactive_ultra(0)
            return
        if key == Qt.Key_2:
            self._interactive_ultra(1)
            return
        if key == Qt.Key_3:
            self._interactive_ultra(2)
            return
        if key == Qt.Key_4:
            self._interactive_ultra(3)
            return

        # 空格/回车：推进（怪物行动 / 角色行动后轮转到下个行动者）
        if key in (Qt.Key_Space, Qt.Key_Return):
            self._interactive_advance()
            return

        if is_char:
            if key == Qt.Key_E:
                self._interactive_step(SkillType.SKILL)
                return
            if key == Qt.Key_Q:
                self._interactive_step(SkillType.NORMAL)
                return
        else:
            # 怪物/阿哈/倒计时：按 E/Q 执行其行动
            if key in (Qt.Key_E, Qt.Key_Q):
                self._interactive_advance()
                return

        super().keyPressEvent(event)

    # ── 运行模拟 ─────────────────────────────────────

    def _run_simulation(self) -> None:
        """运行战斗模拟并展示结果。"""
        try:
            chars, enemies, initial_sp, max_av, action_mode, warnings = self._collect_config()
        except Exception as e:
            QMessageBox.warning(self, "配置错误", f"读取配置失败: {e}")
            return

        if not chars:
            QMessageBox.warning(self, "配置错误", "至少需要一个角色")
            return
        if warnings:
            QMessageBox.information(self, "提示", "\n".join(warnings))

        self.characters = chars
        self.enemies = enemies

        sim = BattleSimulator(
            characters=chars,
            enemies=enemies,
            max_av=float(max_av),
            initial_sp=initial_sp,
            enemy_attacks=self._collect_enemy_attacks(for_simulator=True),
        )
        sim.setup()

        actions: list[PlayerAction] = []
        if action_mode == 1:  # 全部普攻
            for char in chars:
                actions.append(PlayerAction(
                    unit_id=char.unit_id,
                    skill_type=SkillType.NORMAL,
                    target_id=enemies[0].unit_id,
                ))
        elif action_mode == 2:  # 全部战技
            for char in chars:
                actions.append(PlayerAction(
                    unit_id=char.unit_id,
                    skill_type=SkillType.SKILL,
                    target_id=enemies[0].unit_id,
                ))

        result = sim.run(actions=actions if actions else None)
        self._last_result = result
        self._display_result(result)
        # 自动跳到行动日志 Tab
        self.tabs.setCurrentIndex(1)

    # ── 结果展示 ─────────────────────────────────────

    def _display_result(self, result: BattleResult) -> None:
        """展示模拟结果到各 Tab。"""
        self._fill_log_table(result)
        self._fill_gantt(result)
        self._fill_pie(result)
        self._fill_detail_table(result)
        self._fill_summary(result)

    def _fill_log_table(self, result: BattleResult) -> None:
        """行动日志表格。"""
        self.log_table.setRowCount(len(result.logs))
        for i, log in enumerate(result.logs):
            self.log_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.log_table.setItem(i, 1, QTableWidgetItem(f"{log.av:.1f}"))
            self.log_table.setItem(i, 2, QTableWidgetItem(f"{log.total_av:.1f}"))
            self.log_table.setItem(i, 3, QTableWidgetItem(log.actor_name))
            self.log_table.setItem(i, 4, QTableWidgetItem(
                ACTION_NAMES_ZH.get(log.action_type, log.action_type)
            ))
            dmg_str = ", ".join(f"{d:.0f}" for d in log.damages) if log.damages else "-"
            self.log_table.setItem(i, 5, QTableWidgetItem(dmg_str))
            self.log_table.setItem(i, 6, QTableWidgetItem(f"{log.total_damage:.0f}"))
            notes = log.notes
            if log.enemy_broken:
                notes = "【击破】" + notes
            self.log_table.setItem(i, 7, QTableWidgetItem(notes))

    def _fill_gantt(self, result: BattleResult) -> None:
        """AV 时间轴甘特图。"""
        # 按 unit_id 聚合行动
        unit_actions: dict[str, list[tuple[float, str, float, str]]] = {}
        # 同时记录单位顺序（角色 → 怪物 → 阿哈）
        unit_order: list[str] = []
        for c in self.characters:
            if c.unit_id not in unit_actions:
                unit_actions[c.unit_id] = []
                unit_order.append(c.unit_id)
        for e in self.enemies:
            if e.unit_id not in unit_actions:
                unit_actions[e.unit_id] = []
                unit_order.append(e.unit_id)

        for log in result.logs:
            if log.actor_id not in unit_actions:
                unit_actions[log.actor_id] = []
                unit_order.append(log.actor_id)
            unit_actions[log.actor_id].append(
                (log.total_av, log.action_type, log.total_damage, log.notes)
            )

        # 构造 GanttLane
        lanes: list[GanttLane] = []
        for uid in unit_order:
            actions_data = unit_actions.get(uid, [])
            if not actions_data:
                continue
            # 单位名
            if uid == "__aha__":
                name = "阿哈"
            else:
                name = next((c.name for c in self.characters if c.unit_id == uid), None)
                if name is None:
                    name = next((e.name for e in self.enemies if e.unit_id == uid), uid)
            gantt_actions = [
                GanttAction(total_av=av, action_type=at, damage=dmg, note=note)
                for av, at, dmg, note in actions_data
            ]
            lanes.append(GanttLane(unit_id=uid, name=name, actions=gantt_actions))

        self.gantt_widget.set_data(lanes)

    def _fill_pie(self, result: BattleResult) -> None:
        """伤害占比饼图 + 排行表。"""
        # 按角色聚合伤害
        damage_by_unit: dict[str, float] = {}
        for log in result.logs:
            if log.actor_id == "__aha__" or log.actor_id.startswith("enemy"):
                continue
            damage_by_unit[log.actor_id] = damage_by_unit.get(log.actor_id, 0) + log.total_damage

        # 排序
        sorted_data = sorted(damage_by_unit.items(), key=lambda x: x[1], reverse=True)
        # 饼图数据
        pie_data: list[tuple[str, float]] = []
        for uid, dmg in sorted_data:
            name = next((c.name for c in self.characters if c.unit_id == uid), uid)
            pie_data.append((name, dmg))

        self.pie_widget.set_data(pie_data)

        # 排行表
        total = sum(d for _, d in sorted_data)
        self.rank_table.setRowCount(len(sorted_data))
        for i, (uid, dmg) in enumerate(sorted_data):
            char = next((c for c in self.characters if c.unit_id == uid), None)
            name = char.name if char else uid
            path_zh = PATH_MAP.get(char.path, "") if char else ""
            elem_zh = ELEMENT_MAP.get(char.element, "") if char else ""
            pct = (dmg / total * 100) if total > 0 else 0
            self.rank_table.setItem(i, 0, QTableWidgetItem(name))
            self.rank_table.setItem(i, 1, QTableWidgetItem(f"{path_zh} / {elem_zh}"))
            self.rank_table.setItem(i, 2, QTableWidgetItem(f"{dmg:.0f}"))
            self.rank_table.setItem(i, 3, QTableWidgetItem(f"{pct:.1f}%"))

    def _fill_detail_table(self, result: BattleResult) -> None:
        """伤害明细表格。"""
        self.detail_table.setRowCount(len(result.logs))
        for i, log in enumerate(result.logs):
            self.detail_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.detail_table.setItem(i, 1, QTableWidgetItem(f"{log.total_av:.1f}"))
            self.detail_table.setItem(i, 2, QTableWidgetItem(log.actor_name))
            self.detail_table.setItem(i, 3, QTableWidgetItem(
                ACTION_NAMES_ZH.get(log.action_type, log.action_type)
            ))
            self.detail_table.setItem(i, 4, QTableWidgetItem(log.target_id or "-"))
            self.detail_table.setItem(i, 5, QTableWidgetItem(
                f"{len(log.damages)} 段" if log.damages else "-"
            ))
            self.detail_table.setItem(i, 6, QTableWidgetItem(f"{log.total_damage:.0f}"))
            self.detail_table.setItem(i, 7, QTableWidgetItem(log.notes or "-"))

    def _fill_summary(self, result: BattleResult) -> None:
        """汇总页：卡片 + 角色状态 + 怪物状态。"""
        # 卡片
        self._set_card_value(self.card_turns, str(result.total_turns))
        self._set_card_value(self.card_av, f"{result.total_av:.1f}")
        self._set_card_value(self.card_damage, f"{result.total_damage:.0f}")
        avg = result.total_damage / max(1, result.total_turns)
        self._set_card_value(self.card_avg, f"{avg:.0f}")
        self._set_card_value(self.card_aha, f"{result.aha_count} 次")
        self._set_card_value(self.card_sp, str(result.final_sp))

        self.end_reason_label.setText(f"结束原因：{result.end_reason.value}")

        # 角色状态表
        self.char_summary_table.setRowCount(len(self.characters))
        for i, char in enumerate(self.characters):
            stats = char.final_stats()
            path_zh = PATH_MAP.get(char.path, char.path)
            elem_zh = ELEMENT_MAP.get(char.element, char.element)
            self.char_summary_table.setItem(i, 0, QTableWidgetItem(char.name))
            self.char_summary_table.setItem(i, 1, QTableWidgetItem(path_zh))
            self.char_summary_table.setItem(i, 2, QTableWidgetItem(elem_zh))
            self.char_summary_table.setItem(i, 3, QTableWidgetItem(f"{stats.atk:.0f}"))
            self.char_summary_table.setItem(i, 4, QTableWidgetItem(f"{stats.spd:.1f}"))
            self.char_summary_table.setItem(i, 5, QTableWidgetItem(
                f"{stats.crit_rate*100:.1f}% / {stats.crit_dmg*100:.1f}%"
            ))
            self.char_summary_table.setItem(i, 6, QTableWidgetItem(
                f"{char.energy:.0f}/{stats.energy_max:.0f}"
            ))

        # 怪物状态表
        self.enemy_summary_table.setRowCount(len(self.enemies))
        for i, enemy in enumerate(self.enemies):
            weaknesses_zh = ", ".join(ELEMENT_MAP.get(w, w) for w in enemy.weakness_elements)
            self.enemy_summary_table.setItem(i, 0, QTableWidgetItem(enemy.name))
            self.enemy_summary_table.setItem(i, 1, QTableWidgetItem(
                f"{enemy.current_toughness:.0f}/{enemy.max_toughness:.0f}"
            ))
            self.enemy_summary_table.setItem(i, 2, QTableWidgetItem(
                "是" if enemy.is_broken else "否"
            ))
            self.enemy_summary_table.setItem(i, 3, QTableWidgetItem(weaknesses_zh))
            self.enemy_summary_table.setItem(i, 4, QTableWidgetItem(str(enemy.level)))

    def _set_card_value(self, card: QFrame, value: str) -> None:
        """更新卡片的数值标签。"""
        layout = card.layout()
        if layout and layout.count() >= 2:
            value_label = layout.itemAt(1).widget()
            if isinstance(value_label, QLabel):
                value_label.setText(value)

    # ── 清理 ────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        """窗口关闭：保存全部配置缓存 + 终止仍在运行的详情/光锥加载线程。"""
        if hasattr(self, "team_table"):
            self._save_config()
        threads = dict(getattr(self, "_detail_threads", {}))
        threads.update(getattr(self, "_lc_threads", {}))
        for thread in threads.values():
            if thread.isRunning():
                thread.terminate()
                thread.wait(1000)
        super().closeEvent(event)


# ── 入口 ──────────────────────────────────────────────────


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(DARK_STYLE)

    # 强制深色调色板（QSS 未覆盖的部分）
    palette = app.palette()
    palette.setColor(QPalette.Window, QColor(Colors.BG_DEEPEST))
    palette.setColor(QPalette.WindowText, QColor(Colors.TEXT_PRIMARY))
    palette.setColor(QPalette.Base, QColor(Colors.BG_PANEL))
    palette.setColor(QPalette.AlternateBase, QColor(Colors.BG_CARD))
    palette.setColor(QPalette.Text, QColor(Colors.TEXT_PRIMARY))
    palette.setColor(QPalette.Button, QColor(Colors.BG_CARD))
    palette.setColor(QPalette.ButtonText, QColor(Colors.TEXT_PRIMARY))
    palette.setColor(QPalette.Highlight, QColor(Colors.BG_SELECTED))
    palette.setColor(QPalette.HighlightedText, QColor(Colors.TEXT_PRIMARY))
    app.setPalette(palette)

    window = BattleSimulatorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
