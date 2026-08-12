"""战斗模拟器 GUI 主窗口。

精致深色游戏风界面：侧栏 + 主区域 Tab 布局。
- 侧栏：队伍快速概览
- 主区域 Tab：配置 / 行动日志 / AV时间轴 / 伤害占比 / 伤害明细 / 汇总

运行：
    python ui_main.py
"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
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

from src.api.consts import ELEMENT_MAP, PATH_MAP
from src.core.damage import DamageType
from src.core.simulator import (
    BattleEndReason,
    BattleSimulator,
    BattleResult,
    CharacterUnit,
    EnemyState,
    PlayerAction,
)
from src.core.skill import Skill, SkillEffect, SkillType
from src.core.stats import BaseStats, StatBonus
from src.ui.theme import DARK_STYLE, Colors, ELEMENT_COLORS, PATH_COLORS
from src.ui.widgets.character_picker import CharacterPickerDialog, _load_character_icon
from src.ui.widgets.damage_pie import DamagePieChartWidget
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
}


# ── 预设角色构造 ──────────────────────────────────────────


def make_preset_character(
    unit_id: str,
    name: str,
    path: str,
    element: str,
    atk: float = 1000,
    spd: float = 100,
    crit_rate: float = 0.05,
    crit_dmg: float = 0.5,
    dmg_bonus: float = 0.0,
    break_effect: float = 0.0,
) -> CharacterUnit:
    """构造预设角色（带普攻/战技/终结技）。"""
    base = BaseStats(
        hp_base=10000,
        atk_base=atk,
        def_base=500,
        spd_base=spd,
        crit_rate=crit_rate,
        crit_dmg=crit_dmg,
        break_effect=break_effect,
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
    """构造一个数据卡片（标题 + 数值）。"""
    card = QFrame()
    card.setObjectName("card")
    card.setStyleSheet(f"""
        QFrame#card {{
            background-color: {Colors.BG_CARD};
            border: 1px solid {Colors.BORDER};
            border-radius: 8px;
            padding: 12px;
        }}
    """)
    layout = QVBoxLayout(card)
    layout.setContentsMargins(12, 10, 12, 10)
    layout.setSpacing(4)

    title_label = QLabel(title)
    title_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; border: none;")
    value_label = QLabel(value)
    value_label.setStyleSheet(
        f"color: {color}; font-size: 20px; font-weight: 700; border: none;"
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
        """左侧栏：标题 + 队伍概览 + 操作按钮。"""
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(260)
        # 用 objectName 限定样式范围，避免级联覆盖子控件
        sidebar.setStyleSheet(
            f"QWidget#sidebar {{ background-color: {Colors.BG_DEEPEST}; }}"
        )
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 20, 16, 16)
        layout.setSpacing(16)

        # 标题
        title = QLabel("星铁排轴工具")
        title.setObjectName("title")
        title.setStyleSheet(
            f"QLabel#title {{ color: {Colors.GOLD}; font-size: 18px; font-weight: 700; border: none; }}"
        )
        layout.addWidget(title)

        subtitle = QLabel("战斗模拟器 · 阶段 2 验收")
        subtitle.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
        layout.addWidget(subtitle)

        # 分隔线
        layout.addWidget(self._make_separator())

        # 队伍概览
        overview_label = QLabel("队伍概览")
        overview_label.setStyleSheet(
            f"color: {Colors.GOLD}; font-size: 13px; font-weight: 600;"
        )
        layout.addWidget(overview_label)

        self.overview_container = QWidget()
        self.overview_layout = QVBoxLayout(self.overview_container)
        self.overview_layout.setContentsMargins(0, 0, 0, 0)
        self.overview_layout.setSpacing(8)
        layout.addWidget(self.overview_container)

        layout.addStretch()

        # 操作按钮
        self.run_btn = QPushButton("▶  运行模拟")
        self.run_btn.setObjectName("primaryBtn")
        self.run_btn.setMinimumHeight(40)
        self.run_btn.setCursor(Qt.PointingHandCursor)
        self.run_btn.clicked.connect(self._run_simulation)
        layout.addWidget(self.run_btn)

        self.reset_btn = QPushButton("↻  重置配置")
        self.reset_btn.setMinimumHeight(36)
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
        layout.setContentsMargins(12, 12, 12, 12)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        # Tab 1: 配置
        self.tabs.addTab(self._build_config_tab(), "配置")

        # Tab 2: 交互模拟
        self.tabs.addTab(self._build_interactive_tab(), "交互模拟")

        # Tab 3: 行动日志
        self.tabs.addTab(self._build_log_tab(), "行动日志")

        # Tab 3: AV 时间轴
        self.tabs.addTab(self._build_timeline_tab(), "AV 时间轴")

        # Tab 4: 伤害占比
        self.tabs.addTab(self._build_pie_tab(), "伤害占比")

        # Tab 5: 伤害明细
        self.tabs.addTab(self._build_detail_tab(), "伤害明细")

        # Tab 6: 汇总
        self.tabs.addTab(self._build_summary_tab(), "汇总")

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
        self.team_table = QTableWidget(4, 7)
        self.team_table.setHorizontalHeaderLabels(
            ["名称", "命途", "属性", "攻击力", "速度", "暴击率", "暴击伤害"]
        )
        self.team_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.team_table.verticalHeader().setDefaultSectionSize(36)
        self.team_table.setAlternatingRowColors(True)
        self.team_table.cellDoubleClicked.connect(self._on_team_cell_double_clicked)
        team_layout.addWidget(self.team_table)
        layout.addWidget(team_group)

        # 怪物配置 + 战斗参数（并排）
        bottom_layout = QHBoxLayout()

        enemy_group = QGroupBox("怪物配置")
        enemy_form = QFormLayout(enemy_group)
        enemy_form.setSpacing(8)
        self.enemy_name_edit = QPlainTextEdit()
        self.enemy_name_edit.setPlainText("史莱姆")
        self.enemy_name_edit.setFixedHeight(32)
        enemy_form.addRow("名称", self.enemy_name_edit)
        self.toughness_spin = QSpinBox()
        self.toughness_spin.setRange(1, 1000)
        self.toughness_spin.setValue(60)
        enemy_form.addRow("韧性", self.toughness_spin)
        self.weakness_edit = QPlainTextEdit()
        self.weakness_edit.setPlainText("火, 冰")
        self.weakness_edit.setFixedHeight(32)
        enemy_form.addRow("弱点属性", self.weakness_edit)
        self.enemy_level_spin = QSpinBox()
        self.enemy_level_spin.setRange(1, 100)
        self.enemy_level_spin.setValue(80)
        enemy_form.addRow("等级", self.enemy_level_spin)
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
        layout.addStretch()

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
        ops_group = QGroupBox("操作  ·  键盘: E=战技  Q=普攻  1/2/3/4=终结技插队  空格=推进怪物/阿哈")
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
        hint.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; font-size: 11px;")
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

    # ── 队伍概览更新 ─────────────────────────────────

    def _update_overview(self) -> None:
        """更新侧栏队伍概览。"""
        # 清空
        while self.overview_layout.count():
            item = self.overview_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for row in range(self.team_table.rowCount()):
            name_item = self.team_table.item(row, 0)
            path_item = self.team_table.item(row, 1)
            elem_item = self.team_table.item(row, 2)
            if not name_item or not name_item.text().strip():
                continue
            name = name_item.text().strip()
            path_zh = path_item.text().strip() if path_item else ""
            elem_zh = elem_item.text().strip() if elem_item else ""

            # 颜色
            path_en = PATH_MAP_ZH_TO_EN.get(path_zh, "")
            elem_en = ELEMENT_MAP_ZH_TO_EN.get(elem_zh, "")
            path_color = PATH_COLORS.get(path_en, Colors.TEXT_PRIMARY)
            elem_color = ELEMENT_COLORS.get(elem_en, Colors.TEXT_PRIMARY)

            card = QFrame()
            card.setObjectName("overviewCard")
            card.setStyleSheet(f"""
                QFrame#overviewCard {{
                    background-color: {Colors.BG_CARD};
                    border: 1px solid {Colors.BORDER};
                    border-radius: 6px;
                    padding: 8px;
                }}
            """)
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(10, 6, 10, 6)
            card_layout.setSpacing(2)

            name_label = QLabel(name)
            name_label.setStyleSheet(
                f"color: {Colors.TEXT_PRIMARY}; font-weight: 600; font-size: 13px; border: none;"
            )
            card_layout.addWidget(name_label)

            tag_label = QLabel(f"{path_zh}  ·  {elem_zh}")
            tag_label.setStyleSheet(
                f"color: {path_color}; font-size: 11px; border: none;"
            )
            card_layout.addWidget(tag_label)

            self.overview_layout.addWidget(card)

    # ── 角色选择 ─────────────────────────────────────

    def _on_team_cell_double_clicked(self, row: int, column: int) -> None:
        """双击队伍表格名称列，弹出角色选择器。"""
        if column != 0:
            return
        picker = CharacterPickerDialog(self)
        if picker.exec() == QDialog.Accepted and picker.selected_character:
            c = picker.selected_character
            name_item = QTableWidgetItem(c.name_zh or c.name_en)
            # 在名称列存储 nanoka 角色 ID（用于加载头像）
            name_item.setData(Qt.UserRole, c.id)
            self.team_table.setItem(row, 0, name_item)
            self.team_table.setItem(row, 1, QTableWidgetItem(PATH_MAP.get(c.path, c.path)))
            self.team_table.setItem(row, 2, QTableWidgetItem(ELEMENT_MAP.get(c.element, c.element)))
            self._update_overview()

    # ── 默认配置 ─────────────────────────────────────

    def _load_default_config(self) -> None:
        """加载默认配置。"""
        defaults = [
            ("char1", "角色A", "存护", "火", 1200, 100, 0.05, 0.5),
            ("char2", "角色B", "巡猎", "冰", 1100, 134, 0.30, 1.0),
            ("char3", "角色C", "智识", "雷", 1300, 110, 0.10, 0.7),
            ("char4", "角色D", "欢愉", "风", 1000, 120, 0.05, 0.5),
        ]
        for row, (uid, name, path, elem, atk, spd, cr, cd) in enumerate(defaults):
            self.team_table.setItem(row, 0, QTableWidgetItem(name))
            self.team_table.setItem(row, 1, QTableWidgetItem(path))
            self.team_table.setItem(row, 2, QTableWidgetItem(elem))
            self.team_table.setItem(row, 3, QTableWidgetItem(str(atk)))
            self.team_table.setItem(row, 4, QTableWidgetItem(str(spd)))
            self.team_table.setItem(row, 5, QTableWidgetItem(str(cr)))
            self.team_table.setItem(row, 6, QTableWidgetItem(str(cd)))
        self._update_overview()

    # ── 读取配置 ─────────────────────────────────────

    def _collect_config(self) -> tuple[list[CharacterUnit], list[EnemyState], int, int, int]:
        """从 UI 读取配置（命途/属性中文 → 英文）。"""
        characters = []
        for row in range(self.team_table.rowCount()):
            name_item = self.team_table.item(row, 0)
            if not name_item or not name_item.text().strip():
                continue
            name = name_item.text().strip()
            uid = f"char{row+1}"
            # 读取 nanoka 角色 ID（用于加载头像）
            char_id = name_item.data(Qt.UserRole) or ""
            path_zh = self.team_table.item(row, 1).text().strip() if self.team_table.item(row, 1) else "存护"
            path = PATH_MAP_ZH_TO_EN.get(path_zh, path_zh)
            elem_zh = self.team_table.item(row, 2).text().strip() if self.team_table.item(row, 2) else "火"
            elem = ELEMENT_MAP_ZH_TO_EN.get(elem_zh, elem_zh)
            atk = float(self.team_table.item(row, 3).text() or "1000") if self.team_table.item(row, 3) else 1000
            spd = float(self.team_table.item(row, 4).text() or "100") if self.team_table.item(row, 4) else 100
            cr = float(self.team_table.item(row, 5).text() or "0.05") if self.team_table.item(row, 5) else 0.05
            cd = float(self.team_table.item(row, 6).text() or "0.5") if self.team_table.item(row, 6) else 0.5
            char = make_preset_character(uid, name, path, elem, atk, spd, cr, cd)
            char.char_id = str(char_id)
            characters.append(char)

        enemy_name = self.enemy_name_edit.toPlainText().strip() or "怪物"
        toughness = self.toughness_spin.value()
        weaknesses_zh = [
            w.strip() for w in self.weakness_edit.toPlainText().split(",") if w.strip()
        ]
        weaknesses = [ELEMENT_MAP_ZH_TO_EN.get(w, w) for w in weaknesses_zh]
        enemy_level = self.enemy_level_spin.value()
        enemy = EnemyState(
            unit_id="enemy1",
            name=enemy_name,
            max_toughness=toughness,
            current_toughness=toughness,
            weakness_elements=weaknesses,
            level=enemy_level,
        )

        return characters, [enemy], self.sp_spin.value(), self.turns_spin.value(), self.action_combo.currentIndex()

    # ── 交互模拟 ─────────────────────────────────────

    def _start_interactive(self) -> None:
        """初始化交互模拟。"""
        try:
            chars, enemies, initial_sp, max_av, _ = self._collect_config()
        except Exception as e:
            QMessageBox.warning(self, "配置错误", f"读取配置失败: {e}")
            return

        if not chars:
            QMessageBox.warning(self, "配置错误", "至少需要一个角色")
            return

        self.characters = chars
        self.enemies = enemies

        self._interactive_sim = BattleSimulator(
            characters=chars,
            enemies=enemies,
            max_av=float(max_av),
            initial_sp=initial_sp,
        )
        self._interactive_sim.setup()
        self._interactive_snapshots = [self._interactive_sim.snapshot()]
        self._interactive_old_logs = []
        self._interactive_active = True

        # 重建能量图标
        self._rebuild_energy_orbs()

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
        # 怪物/阿哈不在此处理
        if actor.is_monster or actor.unit_id == "__aha__":
            return

        char = sim._get_character(actor.unit_id)
        if char is None:
            return

        # SP 检查：战技需要 1 点 SP
        if skill_type == SkillType.SKILL and not sim.sp.can_consume(1):
            QMessageBox.warning(self, "战技点不足", "当前 SP 为 0，无法使用战技")
            return

        target_id = sim.enemies[0].unit_id if sim.enemies else ""
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
        if not actor.is_monster and actor.unit_id != "__aha__":
            return  # 不是怪物/阿哈

        log = sim.step()
        if log is None:
            self._interactive_active = False
        self._interactive_snapshots.append(sim.snapshot())
        self._interactive_old_logs = []
        self._update_interactive_display()

    def _interactive_ultra(self, char_index: int) -> None:
        """交互模式：插队释放终结技。"""
        if not self._interactive_sim or not self._interactive_active:
            return
        sim = self._interactive_sim

        log = sim.execute_ultra(char_index)
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
        if sim.total_av >= sim.max_av:
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
            if actor.is_monster:
                actor_type = "怪物"
            elif actor.unit_id == "__aha__":
                actor_type = "阿哈"
            else:
                actor_type = "角色"

            all_energy = "  |  ".join(
                f"{c.name}: {c.energy:.0f}" for c in sim.characters
            )
            laugh_info = ""
            elation_chars = [c for c in sim.characters if c.is_elation]
            if elation_chars:
                total_laugh = sum(c.laugh_point for c in elation_chars)
                laugh_info = f"  笑点: {total_laugh:.0f}"

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
            if actor.is_monster or actor.unit_id == "__aha__":
                self.btn_advance.setEnabled(True)
            else:
                self.btn_normal.setEnabled(True)
                # 战技按钮：SP 不足时禁用
                self.btn_skill.setEnabled(sim.sp.can_consume(1))

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

        for char in self._interactive_sim.characters:
            orb = EnergyOrbWidget(
                name=char.name,
                max_energy=char.base_stats.energy_max,
            )
            orb.set_energy(char.energy)
            # 加载角色头像（若有 nanoka 角色 ID）
            if char.char_id:
                pix = _load_character_icon(char.char_id)
                orb.set_avatar(pix)
            self._energy_orbs.append(orb)
            self.energy_orbs_container.addWidget(orb)

    def _update_energy_orbs(self) -> None:
        """更新所有能量图标的数值和状态。"""
        if not self._interactive_sim:
            return
        sim = self._interactive_sim

        # 当前行动者 unit_id
        active_unit_id = ""
        if sim.action_queue.entries:
            active_unit_id = sim.action_queue.next_actor().unit_id

        for i, orb in enumerate(self._energy_orbs):
            if i >= len(sim.characters):
                continue
            char = sim.characters[i]
            orb.set_max_energy(char.base_stats.energy_max)
            orb.set_energy(char.energy)
            orb.set_active(char.unit_id == active_unit_id)

    def _interactive_fill_result_tabs(self) -> None:
        """交互模拟战斗结束后，构建结果并填充各结果 Tab。"""
        if not self._interactive_sim:
            return
        sim = self._interactive_sim

        # 判断结束原因
        if sim.total_av >= sim.max_av:
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
        is_char = not actor.is_monster and actor.unit_id != "__aha__"

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

        if is_char:
            if key == Qt.Key_E:
                self._interactive_step(SkillType.SKILL)
                return
            if key == Qt.Key_Q:
                self._interactive_step(SkillType.NORMAL)
                return
        else:
            # 怪物/阿哈：按空格/回车/E/Q 推进
            if key in (Qt.Key_Space, Qt.Key_Return, Qt.Key_E, Qt.Key_Q):
                self._interactive_advance()
                return

        super().keyPressEvent(event)

    # ── 运行模拟 ─────────────────────────────────────

    def _run_simulation(self) -> None:
        """运行战斗模拟并展示结果。"""
        try:
            chars, enemies, initial_sp, max_av, action_mode = self._collect_config()
        except Exception as e:
            QMessageBox.warning(self, "配置错误", f"读取配置失败: {e}")
            return

        if not chars:
            QMessageBox.warning(self, "配置错误", "至少需要一个角色")
            return

        self.characters = chars
        self.enemies = enemies

        sim = BattleSimulator(
            characters=chars,
            enemies=enemies,
            max_av=float(max_av),
            initial_sp=initial_sp,
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
            if log.sp_after != 3:
                notes += f" SP={log.sp_after}"
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
            self.char_summary_table.setItem(i, 4, QTableWidgetItem(f"{stats.spd:.0f}"))
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
