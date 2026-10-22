"""光锥选择器。

显示所有光锥图标与名称，支持命途/稀有度筛选、名称搜索，并可选择叠影等级（1~5）。

数据来源：nanoka.cc 光锥列表（含 zh 字段）。
图标：首次访问时下载到 cache/icons/，后续直接读本地。

用法：
    picker = LightconePickerDialog(parent, current_id="23056", current_rank=1)
    if picker.exec() == QDialog.Accepted:
        lc = picker.selected_lightcone    # Lightcone | None（None 表示不装备）
        rank = picker.selected_rank       # 1~5 叠影等级
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
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.api.client import download_icon, fetch_lightcone_list, run_in_loop
from src.api.consts import PATH_MAP
from src.api.models import Lightcone
from src.api.transforms import transform_lightcone_list
from src.ui.theme import Colors
from src.ui.widgets.character_picker import ICONS_DIR

if TYPE_CHECKING:
    pass

# 网格中单个光锥图标的显示尺寸
ICON_SIZE = QSize(84, 84)


# ── 数据加载线程 ──────────────────────────────────────────


class _LightconeLoaderWorker(QObject):
    """后台加载光锥列表 + 图标。

    通过 client.run_in_loop 在共享事件循环上执行异步请求
    （httpx 全局单例 client 绑定该循环，避免跨循环复用）。
    cancel_event 用于对话框关闭时提前退出下载循环。
    """

    list_loaded = Signal(list)       # list[Lightcone]
    icon_loaded = Signal(str, str)   # (lightcone_id, local_path)
    failed = Signal(str)             # 错误信息

    def __init__(self) -> None:
        super().__init__()
        self.cancel_event = threading.Event()

    def run(self) -> None:
        """加载光锥列表，然后逐个下载缺失图标。"""
        try:
            run_in_loop(self._load_all())
        except Exception as e:
            self.failed.emit(str(e))

    async def _load_all(self) -> None:
        raw = await fetch_lightcone_list()
        lightcones = transform_lightcone_list(raw)
        # 按中文名排序（空名排末尾）
        lightcones.sort(key=lambda c: c.name_zh or c.name_en or c.id)
        self.list_loaded.emit(lightcones)

        for lc in lightcones:
            if self.cancel_event.is_set():
                break
            icon_path = ICONS_DIR / f"lightcone_{lc.id}.webp"
            if icon_path.exists():
                continue  # 已缓存
            if not lc.icon_url:
                continue
            try:
                path = await download_icon(lc.icon_url, icon_path)
                self.icon_loaded.emit(lc.id, str(path))
            except Exception:
                # 单个图标失败不阻塞其他
                pass


# ── 图标加载辅助 ──────────────────────────────────────────

# QPixmap 内存缓存（lightcone_id -> QPixmap）
_PIXMAP_CACHE: dict[str, QPixmap] = {}


def _load_lightcone_icon(lightcone_id: str) -> QPixmap:
    """加载光锥图标 QPixmap（带内存缓存；本地无图返回占位图）。"""
    key = str(lightcone_id)
    if key in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[key]
    path = ICONS_DIR / f"lightcone_{key}.webp"
    if path.exists():
        pix = QPixmap(str(path))
        if not pix.isNull():
            _PIXMAP_CACHE[key] = pix
            return pix
    placeholder = QPixmap(ICON_SIZE)
    placeholder.fill(Qt.darkGray)
    return placeholder


def _clear_icon_cache(lightcone_id: str) -> None:
    """清除单个图标的内存缓存（新下载后重新加载）。"""
    _PIXMAP_CACHE.pop(str(lightcone_id), None)


# ── 光锥选择对话框 ────────────────────────────────────────


class LightconePickerDialog(QDialog):
    """光锥选择对话框。

    显示光锥图标网格，支持命途/稀有度筛选与名称搜索；
    底部可设置叠影等级（1~5）。

    选中结果通过属性读取：
        selected_lightcone: Lightcone | None   （None = 不装备 / 清除）
        selected_rank: int                     （1~5）
    """

    def __init__(
        self,
        parent: QWidget | None = None,
        current_id: str = "",
        current_rank: int = 1,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择光锥")
        self.resize(940, 720)

        self._lightcones: list[Lightcone] = []
        self._id_to_lightcone: dict[str, Lightcone] = {}
        self._current_id = str(current_id or "")
        self.selected_lightcone: Lightcone | None = None
        self.selected_rank: int = max(1, min(5, int(current_rank or 1)))

        self._thread: QThread | None = None
        self._worker: _LightconeLoaderWorker | None = None

        self._init_ui()
        self._start_loading()

    # ── UI 构建 ──────────────────────────────────────────

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 顶部工具栏：搜索 + 命途 + 稀有度 + 叠影
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入光锥名（中文/英文）或 ID")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_filter)
        toolbar.addWidget(self.search_edit, stretch=1)

        toolbar.addWidget(QLabel("命途:"))
        self.path_combo = QComboBox()
        self.path_combo.addItem("全部", "")
        for en, zh in PATH_MAP.items():
            self.path_combo.addItem(zh, en)
        self.path_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.path_combo)

        toolbar.addWidget(QLabel("稀有度:"))
        self.rarity_combo = QComboBox()
        self.rarity_combo.addItem("全部", 0)
        for stars in (5, 4, 3):
            self.rarity_combo.addItem(f"{stars} 星", stars)
        self.rarity_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.rarity_combo)

        toolbar.addWidget(QLabel("叠影:"))
        self.rank_spin = QSpinBox()
        self.rank_spin.setRange(1, 5)
        self.rank_spin.setValue(self.selected_rank)
        self.rank_spin.setPrefix("叠影 ")
        self.rank_spin.setToolTip("光锥叠影等级（1~5），决定战斗内效果数值")
        self.rank_spin.valueChanged.connect(self._on_rank_changed)
        toolbar.addWidget(self.rank_spin)

        layout.addLayout(toolbar)

        # 状态标签
        self.status_label = QLabel("加载光锥列表中...")
        layout.addWidget(self.status_label)

        # 光锥网格
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

        # 底部：选中详情 + 按钮
        btn_layout = QHBoxLayout()
        self.info_label = QLabel("")
        self.info_label.setStyleSheet(f"color: {Colors.TEXT_SECONDARY}; border: none;")
        btn_layout.addWidget(self.info_label, stretch=1)

        self.clear_btn = QPushButton("不装备")
        self.clear_btn.setToolTip("清除该角色已装备的光锥")
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
        """启动后台线程加载光锥列表和图标。"""
        self._thread = QThread()
        self._worker = _LightconeLoaderWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.list_loaded.connect(self._on_list_loaded)
        self._worker.icon_loaded.connect(self._on_icon_loaded)
        self._worker.failed.connect(self._on_load_failed)
        self._thread.finished.connect(self._on_loading_finished)

        self._thread.start()

    def _on_list_loaded(self, lightcones: list) -> None:
        """光锥列表加载完成。"""
        self._lightcones = lightcones
        self._id_to_lightcone = {lc.id: lc for lc in lightcones}
        self._refresh_list()
        cached = sum(
            1 for lc in lightcones
            if (ICONS_DIR / f"lightcone_{lc.id}.webp").exists()
        )
        if cached == len(lightcones):
            self.status_label.setText(f"共 {len(lightcones)} 个光锥（图标已全部缓存）")
        else:
            self.status_label.setText(f"共 {len(lightcones)} 个光锥（正在下载图标…）")
        # 预选中当前光锥
        if self._current_id:
            self._select_by_id(self._current_id)

    def _on_icon_loaded(self, lightcone_id: str, _path: str) -> None:
        """单个图标下载完成，更新对应 item。"""
        _clear_icon_cache(lightcone_id)
        pix = _load_lightcone_icon(lightcone_id)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == lightcone_id:
                item.setIcon(QIcon(pix))
                break

    def _on_load_failed(self, err: str) -> None:
        self.status_label.setText(f"加载失败: {err}")

    def _on_loading_finished(self) -> None:
        if self._lightcones:
            missing = sum(
                1 for lc in self._lightcones
                if not (ICONS_DIR / f"lightcone_{lc.id}.webp").exists()
            )
            if missing > 0:
                self.status_label.setText(
                    f"共 {len(self._lightcones)} 个光锥（{missing} 个图标下载失败）"
                )
            else:
                self.status_label.setText(f"共 {len(self._lightcones)} 个光锥（图标加载完成）")

    # ── 列表显示与筛选 ──────────────────────────────────

    def _refresh_list(self) -> None:
        """根据当前筛选条件刷新列表。"""
        self.list_widget.clear()

        path_filter = self.path_combo.currentData()
        rarity_filter = int(self.rarity_combo.currentData() or 0)
        keyword = self.search_edit.text().strip().lower()

        shown = 0
        for lc in self._lightcones:
            if path_filter and lc.path != path_filter:
                continue
            if rarity_filter and int(lc.rarity) != rarity_filter:
                continue
            if keyword:
                name_zh = (lc.name_zh or "").lower()
                name_en = (lc.name_en or "").lower()
                if (
                    keyword not in name_zh
                    and keyword not in name_en
                    and keyword not in lc.id.lower()
                ):
                    continue

            display_name = lc.name_zh or lc.name_en or lc.id
            path_zh = PATH_MAP.get(lc.path, lc.path)
            tooltip = (
                f"{display_name}\nID: {lc.id}\n命途: {path_zh}\n"
                f"稀有度: {int(lc.rarity)}星\n基础攻击力: {lc.atk}"
            )
            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, lc.id)
            item.setToolTip(tooltip)
            item.setIcon(QIcon(_load_lightcone_icon(lc.id)))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            if lc.id == self._current_id:
                item.setText(f"{display_name}（当前）")
            self.list_widget.addItem(item)
            shown += 1

        self.info_label.setText(f"显示 {shown} / {len(self._lightcones)} 个光锥")

    def _apply_filter(self) -> None:
        """筛选条件变化时刷新列表。"""
        if self._lightcones:
            self._refresh_list()

    def _select_by_id(self, lightcone_id: str) -> None:
        """按 ID 选中列表项（找不到则清除选择）。"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == lightcone_id:
                self.list_widget.setCurrentItem(item)
                self.list_widget.scrollToItem(item)
                self.selected_lightcone = self._id_to_lightcone.get(lightcone_id)
                self.confirm_btn.setEnabled(True)
                return
        self.selected_lightcone = None
        self.confirm_btn.setEnabled(False)

    # ── 选择与确认 ──────────────────────────────────────

    def _on_selection_changed(self) -> None:
        """选中项变化：更新选中对象与详情文本。"""
        item = self.list_widget.currentItem()
        has_selection = item is not None
        self.confirm_btn.setEnabled(has_selection)
        if not has_selection:
            self.selected_lightcone = None
            return
        lightcone_id = item.data(Qt.UserRole)
        self.selected_lightcone = self._id_to_lightcone.get(lightcone_id)
        lc = self.selected_lightcone
        if lc is None:
            return
        path_zh = PATH_MAP.get(lc.path, lc.path)
        self.info_label.setText(
            f"{lc.name_zh or lc.name_en}（ID {lc.id}）· {int(lc.rarity)}星 · {path_zh}"
            f" · 基础攻击力 {lc.atk} · {self.rank_spin.value()} 叠影"
        )

    def _on_rank_changed(self, value: int) -> None:
        """叠影等级变化：记录并刷新详情文本。"""
        self.selected_rank = max(1, min(5, int(value)))
        if self.list_widget.currentItem() is not None:
            self._on_selection_changed()

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        """双击直接确认。"""
        self.selected_lightcone = self._id_to_lightcone.get(item.data(Qt.UserRole))
        self.selected_rank = self.rank_spin.value()
        if self.selected_lightcone is not None:
            self.accept()

    def _on_confirm(self) -> None:
        """点击确认按钮。"""
        item = self.list_widget.currentItem()
        if item is None:
            return
        self.selected_lightcone = self._id_to_lightcone.get(item.data(Qt.UserRole))
        self.selected_rank = self.rank_spin.value()
        if self.selected_lightcone is not None:
            self.accept()

    def _on_clear(self) -> None:
        """不装备：以 selected_lightcone = None 接受。"""
        self.selected_lightcone = None
        self.selected_rank = 1
        self.accept()

    # ── 清理 ────────────────────────────────────────────

    def _stop_thread(self) -> None:
        """通知后台线程取消并等待退出（避免 QThread 未结束就被销毁）。"""
        if self._worker is not None:
            self._worker.cancel_event.set()
        if self._thread is not None and self._thread.isRunning():
            if not self._thread.wait(1000):
                self._thread.terminate()
                self._thread.wait(1000)

    def done(self, result) -> None:
        """accept / reject / ESC / 关闭按钮统一清理线程。"""
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
    dlg = LightconePickerDialog()
    if dlg.exec() == QDialog.Accepted and dlg.selected_lightcone:
        lc = dlg.selected_lightcone
        print(f"已选择: {lc.name_zh} ({lc.name_en})")
        print(f"  ID: {lc.id}")
        print(f"  命途: {PATH_MAP.get(lc.path, lc.path)}")
        print(f"  稀有度: {int(lc.rarity)}星")
        print(f"  叠影: {dlg.selected_rank}")
    else:
        print("未选择")


if __name__ == "__main__":
    main()
