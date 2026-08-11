"""战斗模拟器 GUI 验收页面。

用于阶段 2 验收：直观查看战斗逻辑是否正确。

功能：
- 配置 4 个角色（属性、命途、技能倍率）
- 配置 1 个怪物（韧性、弱点、抗性）
- 配置初始 SP、最大回合数
- 运行模拟，展示行动日志、伤害明细、AV 时间轴
- 支持添加 buff、设置操作序列

运行：
    python -m src.ui.battle_simulator
或：
    python ui_main.py
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QColor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.api.consts import ELEMENT_MAP, PATH_MAP
from src.core.av_system import ActionEntry, ActionQueue, AV_PER_ACTION
from src.core.buff import Buff, BuffDuration, BuffManager, StackRule
from src.core.damage import DamageType, ELATION_BASE_LEVEL_80
from src.core.simulator import (
    BattleSimulator,
    CharacterUnit,
    EnemyState,
    PlayerAction,
)
from src.core.skill import Skill, SkillEffect, SkillType
from src.core.sp import SkillPoint
from src.core.stats import BaseStats, StatBonus
from src.ui.widgets.character_picker import CharacterPickerDialog

# 反向映射：中文 → 英文（用于读取 UI 输入并传给模拟器）
PATH_MAP_ZH_TO_EN: dict[str, str] = {v: k for k, v in PATH_MAP.items()}
ELEMENT_MAP_ZH_TO_EN: dict[str, str] = {v: k for k, v in ELEMENT_MAP.items()}


# ── 预设角色 ──────────────────────────────────────────────


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
    # 增伤由 dmg_bonus 提供面板加成
    bonus = StatBonus(dmg_bonus=dmg_bonus)

    # 普攻：1.0 倍率，削韧 10
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
    # 战技：2.0 倍率，削韧 20
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
    # 终结技：4.0 倍率，削韧 30
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

    char = CharacterUnit(
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
    return char


# ── 主窗口 ────────────────────────────────────────────────


class BattleSimulatorWindow(QMainWindow):
    """战斗模拟器主窗口。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("星铁排轴工具 - 战斗模拟器（阶段 2 验收）")
        self.resize(1200, 800)

        self.characters: list[CharacterUnit] = []
        self.enemies: list[EnemyState] = []
        self.result_text = ""

        self._init_ui()
        self._load_default_config()

    def _init_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)

        # 左侧：配置区
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_panel.setFixedWidth(480)

        # 队伍配置
        team_group = QGroupBox("队伍配置（双击名称列可选择角色）")
        team_layout = QVBoxLayout(team_group)
        self.team_table = QTableWidget(4, 7)
        self.team_table.setHorizontalHeaderLabels(
            ["名称", "命途", "属性", "攻击力", "速度", "暴击率", "暴击伤害"]
        )
        self.team_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.team_table.cellDoubleClicked.connect(self._on_team_cell_double_clicked)
        team_layout.addWidget(self.team_table)
        left_layout.addWidget(team_group)

        # 怪物配置
        enemy_group = QGroupBox("怪物配置")
        enemy_layout = QGridLayout(enemy_group)
        enemy_layout.addWidget(QLabel("名称:"), 0, 0)
        self.enemy_name_edit = QPlainTextEdit()
        self.enemy_name_edit.setPlainText("史莱姆")
        self.enemy_name_edit.setFixedHeight(28)
        enemy_layout.addWidget(self.enemy_name_edit, 0, 1)
        enemy_layout.addWidget(QLabel("韧性:"), 1, 0)
        self.toughness_spin = QSpinBox()
        self.toughness_spin.setRange(1, 1000)
        self.toughness_spin.setValue(60)
        enemy_layout.addWidget(self.toughness_spin, 1, 1)
        enemy_layout.addWidget(QLabel("弱点属性:"), 2, 0)
        self.weakness_edit = QPlainTextEdit()
        self.weakness_edit.setPlainText("火, 冰")
        self.weakness_edit.setFixedHeight(28)
        enemy_layout.addWidget(self.weakness_edit, 2, 1)
        enemy_layout.addWidget(QLabel("等级:"), 3, 0)
        self.enemy_level_spin = QSpinBox()
        self.enemy_level_spin.setRange(1, 100)
        self.enemy_level_spin.setValue(80)
        enemy_layout.addWidget(self.enemy_level_spin, 3, 1)
        left_layout.addWidget(enemy_group)

        # 战斗参数
        params_group = QGroupBox("战斗参数")
        params_layout = QGridLayout(params_group)
        params_layout.addWidget(QLabel("初始 SP:"), 0, 0)
        self.sp_spin = QSpinBox()
        self.sp_spin.setRange(0, 5)
        self.sp_spin.setValue(3)
        params_layout.addWidget(self.sp_spin, 0, 1)
        params_layout.addWidget(QLabel("最大总行动值:"), 1, 0)
        self.turns_spin = QSpinBox()
        self.turns_spin.setRange(50, 10000)
        self.turns_spin.setSingleStep(50)
        self.turns_spin.setValue(300)
        params_layout.addWidget(self.turns_spin, 1, 1)
        params_layout.addWidget(QLabel("默认操作:"), 2, 0)
        self.action_combo = QComboBox()
        self.action_combo.addItems([
            "智能（终结技 > 战技 > 普攻）",
            "全部普攻",
            "全部战技（SP 够时）",
        ])
        params_layout.addWidget(self.action_combo, 2, 1)
        left_layout.addWidget(params_group)

        # 操作按钮
        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("运行模拟")
        self.run_btn.clicked.connect(self._run_simulation)
        btn_layout.addWidget(self.run_btn)
        self.reset_btn = QPushButton("重置配置")
        self.reset_btn.clicked.connect(self._load_default_config)
        btn_layout.addWidget(self.reset_btn)
        left_layout.addLayout(btn_layout)

        left_layout.addStretch()
        main_layout.addWidget(left_panel)

        # 右侧：结果区
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        # Tab 切换
        self.result_tabs = QTabWidget()
        right_layout.addWidget(self.result_tabs)

        # Tab 1: 行动日志
        self.log_table = QTableWidget(0, 8)
        self.log_table.setHorizontalHeaderLabels(
            ["回合", "AV", "总行动值", "行动者", "操作", "伤害明细", "总伤害", "备注"]
        )
        self.log_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.result_tabs.addTab(self.log_table, "行动日志")

        # Tab 2: 伤害明细
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setFont(QFont("Consolas", 10))
        self.result_tabs.addTab(self.detail_text, "伤害明细")

        # Tab 3: AV 时间轴
        self.timeline_text = QTextEdit()
        self.timeline_text.setReadOnly(True)
        self.timeline_text.setFont(QFont("Consolas", 10))
        self.result_tabs.addTab(self.timeline_text, "AV 时间轴")

        # Tab 4: 汇总
        self.summary_text = QTextEdit()
        self.summary_text.setReadOnly(True)
        self.summary_text.setFont(QFont("Consolas", 11))
        self.result_tabs.addTab(self.summary_text, "汇总")

        main_layout.addWidget(right_panel, stretch=1)

    def _on_team_cell_double_clicked(self, row: int, column: int) -> None:
        """双击队伍表格单元格。

        双击名称列（第 0 列）时弹出角色选择器，
        选择角色后自动填充名称、命途、属性。
        其他列不响应（保持手动编辑）。
        """
        if column != 0:
            return

        picker = CharacterPickerDialog(self)
        if picker.exec() == QDialog.Accepted and picker.selected_character:
            c = picker.selected_character
            # 名称：优先中文名
            self.team_table.setItem(row, 0, QTableWidgetItem(c.name_zh or c.name_en))
            # 命途/属性：显示中文
            path_zh = PATH_MAP.get(c.path, c.path)
            elem_zh = ELEMENT_MAP.get(c.element, c.element)
            self.team_table.setItem(row, 1, QTableWidgetItem(path_zh))
            self.team_table.setItem(row, 2, QTableWidgetItem(elem_zh))

    def _load_default_config(self) -> None:
        """加载默认配置（4 个角色，命途/属性显示中文）。"""
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

    def _collect_config(self) -> tuple[list[CharacterUnit], list[EnemyState], int, int, int]:
        """从 UI 读取配置。

        UI 表格中命途/属性显示中文，读取后转回英文枚举值传给模拟器。
        """
        characters = []
        for row in range(self.team_table.rowCount()):
            name_item = self.team_table.item(row, 0)
            if not name_item or not name_item.text().strip():
                continue
            name = name_item.text().strip()
            uid = f"char{row+1}"
            # 命途：中文 → 英文（若已是英文则保留）
            path_zh = self.team_table.item(row, 1).text().strip() if self.team_table.item(row, 1) else "存护"
            path = PATH_MAP_ZH_TO_EN.get(path_zh, path_zh)
            # 属性：中文 → 英文
            elem_zh = self.team_table.item(row, 2).text().strip() if self.team_table.item(row, 2) else "火"
            elem = ELEMENT_MAP_ZH_TO_EN.get(elem_zh, elem_zh)
            atk = float(self.team_table.item(row, 3).text() or "1000") if self.team_table.item(row, 3) else 1000
            spd = float(self.team_table.item(row, 4).text() or "100") if self.team_table.item(row, 4) else 100
            cr = float(self.team_table.item(row, 5).text() or "0.05") if self.team_table.item(row, 5) else 0.05
            cd = float(self.team_table.item(row, 6).text() or "0.5") if self.team_table.item(row, 6) else 0.5
            char = make_preset_character(uid, name, path, elem, atk, spd, cr, cd)
            characters.append(char)

        enemy_name = self.enemy_name_edit.toPlainText().strip() or "怪物"
        toughness = self.toughness_spin.value()
        # 弱点属性：中文 → 英文
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

    def _run_simulation(self) -> None:
        """运行战斗模拟。"""
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

        # 构造操作序列（根据模式）
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
        # action_mode == 0: 智能（传空列表，让 simulator 用默认逻辑）

        result = sim.run(actions=actions if actions else None)
        self._display_result(result, sim)

    def _display_result(self, result, sim: BattleSimulator) -> None:
        """展示模拟结果。"""
        # Tab 1: 行动日志
        self.log_table.setRowCount(len(result.logs))
        for i, log in enumerate(result.logs):
            self.log_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.log_table.setItem(i, 1, QTableWidgetItem(f"{log.av:.1f}"))
            self.log_table.setItem(i, 2, QTableWidgetItem(f"{log.total_av:.1f}"))
            self.log_table.setItem(i, 3, QTableWidgetItem(log.actor_name))
            action_names = {
                "normal": "普攻", "skill": "战技", "ultra": "终结技",
                "monster": "怪物行动", "aha_moment": "阿哈时刻",
            }
            self.log_table.setItem(i, 4, QTableWidgetItem(action_names.get(log.action_type, log.action_type)))
            dmg_str = ", ".join(f"{d:.0f}" for d in log.damages) if log.damages else "-"
            self.log_table.setItem(i, 5, QTableWidgetItem(dmg_str))
            self.log_table.setItem(i, 6, QTableWidgetItem(f"{log.total_damage:.0f}"))
            notes = log.notes
            if log.enemy_broken:
                notes = "【击破】" + notes
            if log.sp_after != 3:
                notes += f" SP={log.sp_after}"
            self.log_table.setItem(i, 7, QTableWidgetItem(notes))

        # Tab 2: 伤害明细
        detail_lines = []
        detail_lines.append("=" * 70)
        detail_lines.append("伤害明细（每段伤害）")
        detail_lines.append("=" * 70)
        for i, log in enumerate(result.logs):
            detail_lines.append(f"\n【回合 {i+1}】AV={log.av:.1f} 总AV={log.total_av:.1f} {log.actor_name} → {log.action_type}")
            if log.target_id:
                detail_lines.append(f"  目标: {log.target_id}")
            for j, dmg in enumerate(log.damages):
                detail_lines.append(f"  第 {j+1} 段: {dmg:.2f}")
            detail_lines.append(f"  小计: {log.total_damage:.2f}")
            if log.notes:
                detail_lines.append(f"  备注: {log.notes}")
        self.detail_text.setPlainText("\n".join(detail_lines))

        # Tab 3: AV 时间轴（按累计总行动值绘制）
        timeline_lines = []
        timeline_lines.append("=" * 70)
        timeline_lines.append("AV 时间轴（横轴 = 累计总行动值）")
        timeline_lines.append("=" * 70)
        # 收集所有单位的行动记录，用 total_av 作为横轴坐标
        unit_actions: dict[str, list[tuple[float, str]]] = {}
        for log in result.logs:
            if log.actor_id not in unit_actions:
                unit_actions[log.actor_id] = []
            action_names = {
                "normal": "普", "skill": "战", "ultra": "终",
                "monster": "怪", "aha_moment": "哈",
            }
            unit_actions[log.actor_id].append((log.total_av, action_names.get(log.action_type, "?")))

        # 绘制简易时间轴
        if result.logs:
            max_total_av = max(log.total_av for log in result.logs) + 10
            col_width = 8
            cols = int(max_total_av / col_width) + 1
            for uid, actions in unit_actions.items():
                name = next((c.name for c in self.characters if c.unit_id == uid), uid)
                if uid.startswith("enemy"):
                    name = next((e.name for e in self.enemies if e.unit_id == uid), uid)
                if uid == "__aha__":
                    name = "阿哈"
                line = list(" " * cols)
                for av, mark in actions:
                    col = int(av / col_width)
                    if col < cols:
                        line[col] = mark
                timeline_lines.append(f"{name:8s} |{''.join(line)}")
            # 横轴刻度
            scale = list(" " * cols)
            for c in range(0, cols, 5):
                av = c * col_width
                label = str(av)
                for k, ch in enumerate(label):
                    if c + k < cols:
                        scale[c + k] = ch
            timeline_lines.append(f"{'总AV':8s} |{''.join(scale)}")
        self.timeline_text.setPlainText("\n".join(timeline_lines))

        # Tab 4: 汇总
        summary_lines = []
        summary_lines.append("=" * 50)
        summary_lines.append("战斗汇总")
        summary_lines.append("=" * 50)
        summary_lines.append(f"总回合数: {result.total_turns}")
        summary_lines.append(f"总行动值: {result.total_av:.1f}")
        summary_lines.append(f"总伤害: {result.total_damage:.2f}")
        summary_lines.append(f"平均每回合: {result.total_damage / max(1, result.total_turns):.2f}")
        summary_lines.append(f"阿哈时刻触发: {result.aha_count} 次")
        summary_lines.append(f"最终 AV: {result.final_av:.1f}")
        summary_lines.append(f"最终 SP: {result.final_sp}")
        summary_lines.append(f"剩余笑点: {result.final_laugh_point:.0f}")
        summary_lines.append(f"结束原因: {result.end_reason.value}")
        summary_lines.append("")
        summary_lines.append("【角色最终状态】")
        for char in self.characters:
            stats = char.final_stats()
            path_zh = PATH_MAP.get(char.path, char.path)
            elem_zh = ELEMENT_MAP.get(char.element, char.element)
            summary_lines.append(f"  {char.name} ({path_zh}/{elem_zh})")
            summary_lines.append(f"    攻击: {stats.atk:.0f}  速度: {stats.spd:.0f}")
            summary_lines.append(f"    暴击: {stats.crit_rate*100:.1f}% / {stats.crit_dmg*100:.1f}%")
            summary_lines.append(f"    能量: {char.energy:.0f}/{stats.energy_max:.0f}")
            if char.is_elation:
                summary_lines.append(f"    笑点: {char.laugh_point:.0f}")
                summary_lines.append(f"    好活当赏: {stats.good_joke:.0f}")
        summary_lines.append("")
        summary_lines.append("【怪物状态】")
        for enemy in self.enemies:
            summary_lines.append(f"  {enemy.name}")
            summary_lines.append(f"    韧性: {enemy.current_toughness:.0f}/{enemy.max_toughness:.0f}")
            summary_lines.append(f"    击破: {'是' if enemy.is_broken else '否'}")
            weaknesses_zh = ", ".join(ELEMENT_MAP.get(w, w) for w in enemy.weakness_elements)
            summary_lines.append(f"    弱点: {weaknesses_zh}")
        self.summary_text.setPlainText("\n".join(summary_lines))


def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = BattleSimulatorWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
