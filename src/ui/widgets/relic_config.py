"""遗器配置对话框（6 部位：套装 + 主词条 + 副词条）。

与 freesr 导入等价的遗器配置入口：每个部位可分别选择
「套装 → 主词条 → 最多 4 条副词条（词条 / 强化次数 / 档位）」，
确定后由 `parse_relic()` 换算成 `FreesrRelic`（含主/副词条合并加成），
供 `compute_panel_breakdown()` 计算面板。

用法：
    dlg = RelicConfigDialog(parent, relics=当前遗器, set_names=已加载套装名)
    if dlg.exec() == QDialog.Accepted:
        relics = dlg.result_relics()      # list[FreesrRelic]
        names = dlg.result_set_names()    # {套装ID(str): 套装名}
"""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from src.core.freesr import (
    RELIC_MAIN_AFFIXES,
    RELIC_SUB_AFFIXES,
    FreesrRelic,
    calc_sub_affix,
    parse_relic,
)
from src.core.relics.labels import (
    MAX_SUB_AFFIXES,
    ORB_ELEMENTS,
    PCT_FIELDS,
    SLOT_NAMES,
    STAT_LABELS,
    SUB_AFFIX_LABELS,
    main_affix_label,
    main_affix_options,
    relic_slot_summary,
    sub_affix_label,
)
from src.ui.theme import Colors
from src.ui.widgets.relic_picker import RelicPickerDialog

# 兼容旧名（本模块内部原有 `_PCT_FIELDS` 常量）
_PCT_FIELDS = PCT_FIELDS


class _WheelBlocker(QObject):
    """事件过滤器：吞掉滚轮事件，防止下拉框被误滚改值。"""

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QEvent.Wheel:
            return True
        return super().eventFilter(obj, event)


# ── 部位状态 ─────────────────────────────────────────────


@dataclass
class _SlotState:
    """单个部位的配置状态。"""

    set_id: int = 0
    set_name: str = ""
    main_affix_id: int = 0
    subs: list[tuple[int, int, int]] = field(default_factory=list)  # (sub_id, count, step)


# ── 遗器配置对话框 ────────────────────────────────────────


class RelicConfigDialog(QDialog):
    """6 部位遗器配置对话框。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        relics: list[FreesrRelic] | None = None,
        set_names: dict[str, str] | None = None,
        char_name: str = "",
        char_id: str = "",
    ) -> None:
        super().__init__(parent)
        self._char_name = char_name or ""
        self._char_id = char_id or ""
        self.setWindowTitle(
            f"遗器配置 — {self._char_name}" if self._char_name else "遗器配置"
        )
        self.resize(860, 580)

        names = {str(k): v for k, v in (set_names or {}).items()}
        self._slots: dict[int, _SlotState] = {slot: _SlotState() for slot in SLOT_NAMES}
        for relic in relics or []:
            slot = int(relic.slot or 0)
            if slot not in self._slots:
                continue
            self._slots[slot] = _SlotState(
                set_id=int(relic.relic_set_id or 0),
                set_name=names.get(str(relic.relic_set_id), ""),
                main_affix_id=int(relic.main_affix_id or 0),
                subs=[
                    (int(sid), int(count), int(step))
                    for sid, count, step in relic.sub_affixes
                    if sid
                ][:MAX_SUB_AFFIXES],
            )

        # 副词条编辑区当前显示的部位（切换部位前先回写）
        self._editing_slot: int | None = None
        self._loading_editor = False

        self._set_buttons: dict[int, QPushButton] = {}
        self._main_combos: dict[int, QComboBox] = {}
        self.sub_combos: list[QComboBox] = []
        self.sub_counts: list[QSpinBox] = []
        self.sub_steps: list[QSpinBox] = []
        self.sub_value_labels: list[QLabel] = []

        self._init_ui()
        self._build_table()
        self._update_summary()

        # 默认选中第一个已配置的部位（都没有则第一行）
        initial_row = 0
        for row, slot in enumerate(sorted(SLOT_NAMES)):
            if self._slots[slot].set_id:
                initial_row = row
                break
        self.table.selectRow(initial_row)
        self._on_slot_selected()

    # ── UI 构建 ──────────────────────────────────────────

    def _init_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(8)

        body = QHBoxLayout()
        body.setSpacing(10)

        # 左侧：6 部位表格
        left = QVBoxLayout()
        self.table = QTableWidget(len(SLOT_NAMES), 3)
        self.table.setHorizontalHeaderLabels(["部位", "套装", "主词条"])
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.itemSelectionChanged.connect(self._on_slot_selected)
        left.addWidget(self.table, stretch=1)

        self.summary_label = QLabel("")
        self.summary_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; border: none;"
        )
        left.addWidget(self.summary_label)
        body.addLayout(left, stretch=1)

        # 右侧：副词条编辑
        right = QGroupBox("副词条（当前部位的 4 条词条）")
        right_box = QVBoxLayout(right)
        hint = QLabel(
            "最终值 = 最低档 × 次数 + (第二档 − 最低档) × 档位\n"
            "（与 freesr-data.json 的 count / step 语义一致）"
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; border: none;"
        )
        right_box.addWidget(hint)

        grid = QGridLayout()
        grid.setHorizontalSpacing(6)
        grid.setVerticalSpacing(6)
        for col, title in enumerate(("词条", "次数", "档位", "数值")):
            title_label = QLabel(title)
            title_label.setStyleSheet(
                f"color: {Colors.TEXT_SECONDARY}; font-size: 11px; border: none;"
            )
            grid.addWidget(title_label, 0, col)
        for i in range(MAX_SUB_AFFIXES):
            combo = QComboBox()
            combo.addItem("（无）", 0)
            for sub_id in sorted(RELIC_SUB_AFFIXES):
                combo.addItem(SUB_AFFIX_LABELS.get(sub_id, str(sub_id)), sub_id)
            combo.installEventFilter(_WheelBlocker(combo))
            combo.currentIndexChanged.connect(self._on_sub_changed)
            grid.addWidget(combo, i + 1, 0)
            self.sub_combos.append(combo)

            count_spin = QSpinBox()
            count_spin.setRange(0, 6)
            count_spin.setToolTip("该词条的强化次数（freesr 的 count）")
            count_spin.valueChanged.connect(self._on_sub_changed)
            grid.addWidget(count_spin, i + 1, 1)
            self.sub_counts.append(count_spin)

            step_spin = QSpinBox()
            step_spin.setRange(0, 10)
            step_spin.setToolTip("强化档位（freesr 的 step）：0 = 全部为最低档")
            step_spin.valueChanged.connect(self._on_sub_changed)
            grid.addWidget(step_spin, i + 1, 2)
            self.sub_steps.append(step_spin)

            value_label = QLabel("—")
            value_label.setMinimumWidth(70)
            value_label.setStyleSheet(
                f"color: {Colors.CYAN}; font-size: 11px; border: none;"
            )
            grid.addWidget(value_label, i + 1, 3)
            self.sub_value_labels.append(value_label)
        right_box.addLayout(grid)
        right_box.addStretch()

        self.clear_slot_btn = QPushButton("清空本部位")
        self.clear_slot_btn.clicked.connect(self._on_clear_slot)
        right_box.addWidget(self.clear_slot_btn)
        body.addWidget(right, stretch=0)

        outer.addLayout(body, stretch=1)

        btn_row = QHBoxLayout()
        clear_all_btn = QPushButton("清空全部")
        clear_all_btn.clicked.connect(self._on_clear_all)
        btn_row.addWidget(clear_all_btn)
        btn_row.addStretch()
        ok_btn = QPushButton("确定")
        ok_btn.setObjectName("primaryBtn")
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        outer.addLayout(btn_row)

    def _build_table(self) -> None:
        """首次构建表格（部位行 + 套装按钮 + 主词条下拉）。"""
        for row, slot in enumerate(sorted(SLOT_NAMES)):
            slot_item = QTableWidgetItem(SLOT_NAMES[slot])
            slot_item.setData(Qt.UserRole, slot)
            self.table.setItem(row, 0, slot_item)

            button = QPushButton("选择…")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, s=slot: self._choose_set(s))
            self._set_buttons[slot] = button
            self.table.setCellWidget(row, 1, button)

            combo = QComboBox()
            combo.installEventFilter(_WheelBlocker(combo))
            combo.currentIndexChanged.connect(
                lambda _index, s=slot: self._on_main_affix_changed(s)
            )
            self._main_combos[slot] = combo
            self.table.setCellWidget(row, 2, combo)

            self._refresh_row(slot)

    def _refresh_row(self, slot: int) -> None:
        """刷新单个部位的套装按钮与主词条下拉。"""
        state = self._slots[slot]
        button = self._set_buttons[slot]
        if state.set_id:
            button.setText(state.set_name or f"套装 {state.set_id}")
            button.setToolTip(f"套装编号 {state.set_id}\n点击重新选择")
        else:
            button.setText("选择…")
            button.setToolTip("点击选择该部位的遗器套装")

        combo = self._main_combos[slot]
        combo.blockSignals(True)
        combo.clear()
        for main_id, label in main_affix_options(slot):
            combo.addItem(label, main_id)
        index = combo.findData(state.main_affix_id)
        if index < 0 and combo.count() > 0:
            index = 0
            state.main_affix_id = int(combo.itemData(0))
        combo.setCurrentIndex(max(0, index))
        combo.setEnabled(bool(state.set_id))
        combo.blockSignals(False)

    def _update_summary(self) -> None:
        """刷新底部摘要（已配置部位数 + 各套装件数）。"""
        configured = [slot for slot in sorted(SLOT_NAMES) if self._slots[slot].set_id]
        if not configured:
            self.summary_label.setText("未配置任何部位（面板只含角色基础 + 行迹加成）")
            return
        counts: dict[int, int] = {}
        names: dict[int, str] = {}
        for slot in configured:
            state = self._slots[slot]
            counts[state.set_id] = counts.get(state.set_id, 0) + 1
            names.setdefault(state.set_id, state.set_name or str(state.set_id))
        detail = " · ".join(
            f"{names[set_id]}×{count}"
            for set_id, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        self.summary_label.setText(f"已配置 {len(configured)}/6 部位：{detail}")

    # ── 交互：套装 / 主词条 ──────────────────────────────

    def _choose_set(self, slot: int) -> None:
        """为指定部位选择套装。"""
        state = self._slots[slot]
        picker = RelicPickerDialog(
            self,
            current_id=str(state.set_id) if state.set_id else "",
            title=f"选择遗器套装 — {SLOT_NAMES[slot]}",
        )
        if picker.exec() != QDialog.Accepted:
            return
        picked = picker.selected_relicset
        if picked is None:
            state.set_id = 0
            state.set_name = ""
        else:
            state.set_id = int(picked.id)
            state.set_name = picked.name_zh or picked.name_en or str(picked.id)
            # 主词条不属于该部位时重置为该部位第一项
            if state.main_affix_id not in RELIC_MAIN_AFFIXES.get(slot, {}):
                options = main_affix_options(slot)
                state.main_affix_id = options[0][0] if options else 0
        self._refresh_row(slot)
        self._update_summary()

    def _on_main_affix_changed(self, slot: int) -> None:
        """主词条下拉变化 → 写回状态。"""
        combo = self._main_combos.get(slot)
        if combo is None or combo.count() == 0:
            return
        main_id = combo.currentData()
        if main_id is not None:
            self._slots[slot].main_affix_id = int(main_id)

    # ── 交互：副词条编辑区 ───────────────────────────────

    def _current_slot(self) -> int | None:
        """表格当前选中行对应的部位编号。"""
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        slot = item.data(Qt.UserRole)
        return int(slot) if slot is not None else None

    def _on_slot_selected(self) -> None:
        """切换部位：先回写旧部位副词条，再载入新部位。"""
        slot = self._current_slot()
        if slot == self._editing_slot:
            return
        self._commit_sub_affixes()
        self._editing_slot = slot
        self._load_sub_affixes(slot)

    def _load_sub_affixes(self, slot: int | None) -> None:
        """把某部位的副词条载入编辑区。"""
        self._loading_editor = True
        subs = self._slots[slot].subs if slot is not None else []
        for i in range(MAX_SUB_AFFIXES):
            combo = self.sub_combos[i]
            count_spin = self.sub_counts[i]
            step_spin = self.sub_steps[i]
            if i < len(subs):
                sub_id, count, step = subs[i]
            else:
                sub_id, count, step = 0, 0, 0
            combo.setCurrentIndex(max(0, combo.findData(sub_id)))
            count_spin.setValue(max(0, min(6, int(count))))
            step_spin.setValue(max(0, min(10, int(step))))
            combo.setEnabled(slot is not None)
            count_spin.setEnabled(slot is not None)
            step_spin.setEnabled(slot is not None)
        self._loading_editor = False
        self._refresh_sub_values()

    def _commit_sub_affixes(self) -> None:
        """把编辑区内容回写到当前部位状态。"""
        slot = self._editing_slot
        if slot is None:
            return
        subs: list[tuple[int, int, int]] = []
        for i in range(MAX_SUB_AFFIXES):
            raw_id = self.sub_combos[i].currentData()
            sub_id = int(raw_id) if raw_id else 0
            if not sub_id:
                continue
            subs.append((sub_id, self.sub_counts[i].value(), self.sub_steps[i].value()))
        self._slots[slot].subs = subs

    def _on_sub_changed(self) -> None:
        """副词条任一控件变化 → 回写状态并刷新数值预览。"""
        if self._loading_editor:
            return
        self._commit_sub_affixes()
        self._refresh_sub_values()

    def _refresh_sub_values(self) -> None:
        """刷新每行副词条换算后的数值文本。"""
        for i in range(MAX_SUB_AFFIXES):
            raw_id = self.sub_combos[i].currentData()
            sub_id = int(raw_id) if raw_id else 0
            count = self.sub_counts[i].value()
            step = self.sub_steps[i].value()
            label = self.sub_value_labels[i]
            entry = RELIC_SUB_AFFIXES.get(sub_id) if sub_id and count > 0 else None
            if entry is None:
                label.setText("—")
                continue
            field_name = entry[0]
            value = calc_sub_affix(sub_id, count, step)
            if field_name in _PCT_FIELDS:
                label.setText(f"+{value * 100:.2f}%")
            else:
                label.setText(f"+{value:.2f}")

    # ── 清空 / 确定 ─────────────────────────────────────

    def _on_clear_slot(self) -> None:
        slot = self._current_slot()
        if slot is None:
            return
        self._slots[slot] = _SlotState()
        self._editing_slot = slot
        self._refresh_row(slot)
        self._load_sub_affixes(slot)
        self._update_summary()

    def _on_clear_all(self) -> None:
        if not any(state.set_id or state.subs for state in self._slots.values()):
            return
        answer = QMessageBox.question(
            self, "清空全部", "确定清空全部 6 个部位的遗器配置？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        self._slots = {slot: _SlotState() for slot in SLOT_NAMES}
        for slot in SLOT_NAMES:
            self._refresh_row(slot)
        self._editing_slot = self._current_slot()
        self._load_sub_affixes(self._editing_slot)
        self._update_summary()

    def _on_accept(self) -> None:
        self._commit_sub_affixes()
        self.accept()

    # ── 结果 ────────────────────────────────────────────

    def result_relics(self) -> list[FreesrRelic]:
        """把当前配置换算为 `FreesrRelic` 列表（未配置的部位跳过）。"""
        self._commit_sub_affixes()
        relics: list[FreesrRelic] = []
        for slot in sorted(SLOT_NAMES):
            state = self._slots[slot]
            if not state.set_id:
                continue
            subs = [
                {"sub_affix_id": sub_id, "count": count, "step": step}
                for sub_id, count, step in state.subs
                if sub_id and count > 0
            ]
            raw = {
                "equip_avatar": self._char_id,
                # 伪 relic_id：末位必须是部位编号（parse_relic 用 % 10 取部位）
                "relic_id": state.set_id * 10000 + slot,
                "relic_set_id": state.set_id,
                "level": 15,
                "main_affix_id": state.main_affix_id,
                "sub_affixes": subs,
            }
            relics.append(parse_relic(raw))
        return relics

    def result_set_names(self) -> dict[str, str]:
        """已选套装的 {套装ID(str): 套装名} 映射（供 tooltip / 摘要显示）。"""
        return {
            str(state.set_id): state.set_name
            for state in self._slots.values()
            if state.set_id and state.set_name
        }
