"""遗器套装选择器。

显示所有遗器套装图标与名称，支持名称搜索与类型筛选（外圈遗器 / 位面饰品），
并在底部展示所选套装的 2 件 / 4 件效果。

数据来源：nanoka.cc 遗器套装列表（含 zh 字段与套装效果描述）。
图标：首次访问时下载到 cache/icons/，后续直接读本地。

用法：
    picker = RelicPickerDialog(parent, current_id="115")
    if picker.exec() == QDialog.Accepted:
        relicset = picker.selected_relicset    # RelicSet | None（None 表示清空）
"""

from __future__ import annotations

import sys
import threading
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSize, Qt, QThread, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.api.client import download_icon, fetch_relicset_list, run_in_loop
from src.api.models import RelicSet
from src.api.transforms import transform_relicset_list
from src.ui.theme import Colors
from src.ui.widgets.character_picker import ICONS_DIR

if TYPE_CHECKING:
    pass

# 网格中单个套装图标的显示尺寸
ICON_SIZE = QSize(84, 84)

# 类型筛选项（data 为过滤标识）
TYPE_ALL = "all"
TYPE_OUTER = "outer"   # 外圈遗器：有 4 件套效果
TYPE_INNER = "inner"   # 位面饰品：只有 2 件套效果


def is_inner_set(relicset: RelicSet) -> bool:
    """是否为位面饰品（内圈：只有 2 件套效果）。"""
    return relicset.bonus_4pc is None


# ── 数据加载线程 ──────────────────────────────────────────


class _RelicSetLoaderWorker(QObject):
    """后台加载遗器套装列表 + 图标（共享事件循环 run_in_loop）。"""

    list_loaded = Signal(list)       # list[RelicSet]
    icon_loaded = Signal(str, str)   # (set_id, local_path)
    failed = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.cancel_event = threading.Event()

    def run(self) -> None:
        try:
            run_in_loop(self._load_all())
        except Exception as e:
            self.failed.emit(str(e))

    async def _load_all(self) -> None:
        raw = await fetch_relicset_list()
        relicsets = transform_relicset_list(raw)
        relicsets.sort(key=lambda r: r.name_zh or r.name_en or r.id)
        self.list_loaded.emit(relicsets)

        for rs in relicsets:
            if self.cancel_event.is_set():
                break
            icon_path = ICONS_DIR / f"relicset_{rs.id}.webp"
            if icon_path.exists() or not rs.icon_url:
                continue
            try:
                path = await download_icon(rs.icon_url, icon_path)
                self.icon_loaded.emit(rs.id, str(path))
            except Exception:
                # 单个图标失败不阻塞其他
                pass


# ── 图标加载辅助 ──────────────────────────────────────────

_PIXMAP_CACHE: dict[str, QPixmap] = {}


def _load_relicset_icon(set_id: str) -> QPixmap:
    """加载遗器套装图标 QPixmap（带内存缓存；无图返回占位图）。"""
    key = str(set_id)
    if key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[key]
    path = ICONS_DIR / f"relicset_{key}.webp"
    if path.exists():
        pix = QPixmap(str(path))
        if not pix.isNull():
            _PIXMAP_CACHE[key] = pix
            return pix
    placeholder = QPixmap(ICON_SIZE)
    placeholder.fill(Qt.darkGray)
    return placeholder


def _clear_icon_cache(set_id: str) -> None:
    _PIXMAP_CACHE.pop(str(set_id), None)


# ── 遗器套装选择对话框 ────────────────────────────────────


class RelicPickerDialog(QDialog):
    """遗器套装选择对话框。

    选中结果通过属性读取：
        selected_relicset: RelicSet | None   （None = 清空该部位）
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        current_id: str = "",
        title: str = "选择遗器套装",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(940, 720)

        self._relicsets: list[RelicSet] = []
        self._id_to_set: dict[str, RelicSet] = {}
        self._current_id = str(current_id or "")
        self.selected_relicset: RelicSet | None = None

        self._thread: QThread | None = None
        self._worker: _RelicSetLoaderWorker | None = None

        self._init_ui()
        self._start_loading()

    # ── UI 构建 ──────────────────────────────────────────

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入套装名（中文/英文）或套装编号")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_edit, stretch=1)

        toolbar.addWidget(QLabel("类型:"))
        self.type_combo = QComboBox()
        self.type_combo.addItem("全部", TYPE_ALL)
        self.type_combo.addItem("遗器（4 件套）", TYPE_OUTER)
        self.type_combo.addItem("位面饰品（2 件套）", TYPE_INNER)
        self.type_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.type_combo)

        layout.addLayout(toolbar)

        self.status_label = QLabel("加载遗器套装列表中...")
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setIconSize(ICON_SIZE)
        self.list_widget.setGridSize(QSize(132, 132))
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setWordWrap(True)
        self.list_widget.setSpacing(6)
        self.list_widget.itemDoubleClicked.connect(self._on_item_activated)
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget, stretch=1)

        # 套装效果预览
        self.effect_label = QLabel("选择套装后在此显示 2 件 / 4 件效果")
        self.effect_label.setWordWrap(True)
        self.effect_label.setMinimumHeight(64)
        self.effect_label.setStyleSheet(
            f"color: {Colors.TEXT_SECONDARY}; border: 1px solid {Colors.BORDER};"
            f" border-radius: 6px; padding: 6px;"
        )
        layout.addWidget(self.effect_label)

        btn_layout = QHBoxLayout()
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; border: none;")
        btn_layout.addWidget(self.info_label, stretch=1)

        self.clear_btn = QPushButton("清空该部位")
        self.clear_btn.setToolTip("把该部位设为未装备")
        self.clear_btn.clicked.connect(self._on_clear)
        btn_layout.addWidget(self.clear_btn)

        self.confirm_btn = QPushButton("确认")
        self.confirm_btn.setObjectName("primaryBtn")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._on_confirm)
        btn_layout.addWidget(self.confirm_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    # ── 后台加载 ────────────────────────────────────────

    def _start_loading(self) -> None:
        self._thread = QThread()
        self._worker = _RelicSetLoaderWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.list_loaded.connect(self._on_list_loaded)
        self._worker.icon_loaded.connect(self._on_icon_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._thread.finished.connect(self._on_loading_finished)
        self._thread.start()

    def _on_list_loaded(self, relicsets: list) -> None:
        self._relicsets = relicsets
        self._id_to_set = {rs.id: rs for rs in relicsets}
        self._refresh_list()
        cached = sum(
            1 for rs in relicsets
            if (ICONS_DIR / f"relicset_{rs.id}.webp").exists()
        )
        if cached == len(relicsets):
            self.status_label.setText(f"共 {len(relicsets)} 套遗器（图标已全部缓存）")
        else:
            self.status_label.setText(f"共 {len(relicsets)} 套遗器（正在下载图标…）")
        if self._current_id:
            self._select_by_id(self._current_id)

    def _on_icon_loaded(self, set_id: str, _path: str) -> None:
        _clear_icon_cache(set_id)
        pix = _load_relicset_icon(set_id)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == set_id:
                item.setIcon(QIcon(pix))
                break

    def _on_load_failed(self, err: str) -> None:
        self.status_label.setText(f"加载失败: {err}")

    def _on_loading_finished(self) -> None:
        if self._relicsets:
            missing = sum(
                1 for rs in self._relicsets
                if not (ICONS_DIR / f"relicset_{rs.id}.webp").exists()
            )
            if missing > 0:
                self.status_label.setText(
                    f"共 {len(self._relicsets)} 套遗器（{missing} 个图标下载失败）"
                )
            else:
                self.status_label.setText(f"共 {len(self._relicsets)} 套遗器（图标加载完成）")

    # ── 列表显示与筛选 ──────────────────────────────────

    def _refresh_list(self) -> None:
        self.list_widget.clear()

        type_filter = str(self.type_combo.currentData() or TYPE_ALL)
        keyword = self.search_edit.text().strip().lower()

        shown = 0
        for rs in self._relicsets:
            if type_filter == TYPE_OUTER and is_inner_set(rs):
                continue
            if type_filter == TYPE_INNER and not is_inner_set(rs):
                continue
            if keyword:
                name_zh = (rs.name_zh or "").lower()
                name_en = (rs.name_en or "").lower()
                if (
                    keyword not in name_zh
                    and keyword not in name_en
                    and keyword not in rs.id.lower()
                ):
                    continue

            display_name = rs.name_zh or rs.name_en or rs.id
            tooltip = f"{display_name}\n编号: {rs.id}\n{self._effect_text(rs)}"
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, rs.id)
            item.setToolTip(tooltip)
            item.setIcon(QIcon(_load_relicset_icon(rs.id)))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            if rs.id == self._current_id:
                item.setText(f"{display_name}（当前）")
            self.list_widget.addItem(item)
            shown += 1

        self.info_label.setText(f"显示 {shown} / {len(self._relicsets)} 套遗器")

    @staticmethod
    def _effect_text(rs: RelicSet) -> str:
        """拼装 2 件 / 4 件套装效果文本。"""
        parts = []
        if rs.bonus_2pc is not None:
            parts.append(f"2 件套：{rs.bonus_2pc.desc}")
        if rs.bonus_4pc is not None:
            parts.append(f"4 件套：{rs.bonus_4pc.desc}")
        return "\n".join(parts) if parts else "（无套装效果数据）"

    def _apply_filter(self) -> None:
        if self._relicsets:
            self._refresh_list()

    def _select_by_id(self, set_id: str) -> None:
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == set_id:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(item)
                self.selected_relicset = self._id_to_set.get(set_id)
                self.confirm_btn.setEnabled(True)
                return
        self.selected_relicset = None
        self.confirm_btn.setEnabled(False)

    # ── 选择与确认 ──────────────────────────────────────

    def _on_selection_changed(self) -> None:
        item = self.list_widget.currentItem()
        self.confirm_btn.setEnabled(item is not None)
        if item is None:
            self.selected_relicset = None
            self.effect_label.setText("选择套装后在此显示 2 件 / 4 件效果")
            return
        self.selected_relicset = self._id_to_set.get(item.data(Qt.UserRole))
        if self.selected_relicset is None:
            return
        self.effect_label.setText(
            f"{self.selected_relicset.name_zh}（编号 {self.selected_relicset.id}）\n"
            f"{self._effect_text(self.selected_relicset)}"
        )

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        self.selected_relicset = self._id_to_set.get(item.data(Qt.UserRole))
        if self.selected_relicset is not None:
            self.accept()

    def _on_confirm(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_relicset = self._id_to_set.get(item.data(Qt.UserRole))
        if self.selected_relicset is not None:
            self.accept()

    def _on_clear(self) -> None:
        self.selected_relicset = None
        self.accept()

    # ── 清理 ────────────────────────────────────────────

    def _stop_thread(self) -> None:
        if self._worker is not None:
            self._worker.cancel_event.set()
        if self._thread is not None and self._thread.isRunning():
            if not self._thread.wait(1000):
                self._thread.terminate()
                self._thread.wait(1000)

    def done(self, result) -> None:
        self._stop_thread()
        super().done(result)

    def closeEvent(self, event) -> None:
        self._stop_thread()
        super().closeEvent(event)


# ── 独立运行入口（调试用）──────────────────────────────────


def main() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dlg = RelicPickerDialog()
    if dlg.exec() == QDialog.Accepted and dlg.selected_relicset:
        rs = dlg.selected_relicset
        print(f"已选择: {rs.name_zh} ({rs.name_en})")
        print(f"  编号: {rs.id}")
        print(f"  {RelicPickerDialog._effect_text(rs)}")
    else:
        print("未选择")


if __name__ == "__main__":
    main()
