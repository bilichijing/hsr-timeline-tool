"""角色选择器。

显示所有角色头像和名称，支持命途/属性筛选和名称搜索。

数据来源：nanoka.cc 角色列表（含 zh 字段）。
头像：首次访问时下载到 cache/icons/，后续直接读本地。

用法：
    picker = CharacterPickerDialog(parent)
    if picker.exec() == QDialog.Accepted:
        char = picker.selected_character
        # char: Character | None
"""

from __future__ import annotations

import asyncio
import sys
import threading
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import (
    QCoreApplication,
    QEventLoop,
    QObject,
    QSize,
    Qt,
    QThread,
    Signal,
)
from PySide6.QtGui import QIcon, QPixmap, QPixmapCache
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

from src.api.client import download_character_icon, fetch_character_list
from src.api.consts import ELEMENT_MAP, PATH_MAP
from src.api.models import Character
from src.api.transforms import transform_character_list

if TYPE_CHECKING:
    pass

# 头像本地缓存目录
ICONS_DIR = Path("./cache/icons")
ICONS_DIR.mkdir(parents=True, exist_ok=True)

# 网格中单个头像的显示尺寸
ICON_SIZE = QSize(96, 96)


# ── 数据加载线程 ──────────────────────────────────────────


class _CharacterLoaderWorker(QObject):
    """后台加载角色列表 + 头像。

    由于 httpx 是异步客户端，而 QThread 是同步线程，
    这里用 QEventLoop 驱动 asyncio。

    通过 cancel_event 可在下载循环中提前退出（避免对话框关闭时线程被强杀）。
    """

    list_loaded = Signal(list)   # list[Character]
    icon_loaded = Signal(str, str)  # (char_id, local_path)
    failed = Signal(str)         # 错误信息

    def __init__(self) -> None:
        super().__init__()
        self.cancel_event = threading.Event()

    def run(self) -> None:
        """加载角色列表，然后逐个下载头像。"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(self._load_all())
            finally:
                loop.close()
        except Exception as e:
            self.failed.emit(str(e))

    async def _load_all(self) -> None:
        # 1. 拉取角色列表
        raw = await fetch_character_list()
        chars = transform_character_list(raw)
        # 按中文名排序（空名排末尾）
        chars.sort(key=lambda c: c.name_zh or c.name_en or c.id)
        self.list_loaded.emit(chars)

        # 2. 只下载缺失的头像（已缓存的不处理，不 emit 信号）
        # _refresh_list 已经从本地加载了缓存的头像，无需重复处理
        for c in chars:
            if self.cancel_event.is_set():
                break
            icon_path = ICONS_DIR / f"character_{c.id}.webp"
            if icon_path.exists():
                continue  # 已缓存，跳过
            try:
                path = await download_character_icon(c.id, ICONS_DIR)
                self.icon_loaded.emit(c.id, str(path))
            except Exception:
                # 单个头像下载失败不阻塞其他
                pass


# ── 头像加载辅助 ──────────────────────────────────────────

# QPixmap 内存缓存（char_id -> QPixmap），避免重复从磁盘加载
_PIXMAP_CACHE: dict[str, QPixmap] = {}


def _load_character_icon(char_id: str) -> QPixmap:
    """加载角色头像 QPixmap，带内存缓存。

    本地无缓存文件则返回占位图。
    """
    # 先查内存缓存
    if char_id in _PIXMAP_CACHE:
        return _PIXMAP_CACHE[char_id]
    # 从磁盘加载
    path = ICONS_DIR / f"character_{char_id}.webp"
    if path.exists():
        pix = QPixmap(str(path))
        if not pix.isNull():
            _PIXMAP_CACHE[char_id] = pix
            return pix
    # 占位图（灰色方块）
    placeholder = QPixmap(ICON_SIZE)
    placeholder.fill(Qt.darkGray)
    return placeholder


# ── 角色选择对话框 ────────────────────────────────────────


class CharacterPickerDialog(QDialog):
    """角色选择对话框。

    显示角色头像网格，支持命途/属性筛选和名称搜索。
    选中后通过 `selected_character` 属性获取 Character 对象。
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择角色")
        self.resize(900, 700)

        self._characters: list[Character] = []
        self._id_to_char: dict[str, Character] = {}
        self.selected_character: Character | None = None

        # 后台加载线程
        self._thread: QThread | None = None
        self._worker: _CharacterLoaderWorker | None = None

        self._init_ui()
        self._start_loading()

    # ── UI 构建 ──────────────────────────────────────────

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)

        # 顶部工具栏：搜索 + 命途筛选 + 属性筛选
        toolbar = QHBoxLayout()

        toolbar.addWidget(QLabel("搜索:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入角色名（中文/英文）")
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

        toolbar.addWidget(QLabel("属性:"))
        self.element_combo = QComboBox()
        self.element_combo.addItem("全部", "")
        for en, zh in ELEMENT_MAP.items():
            self.element_combo.addItem(zh, en)
        self.element_combo.currentIndexChanged.connect(self._apply_filter)
        toolbar.addWidget(self.element_combo)

        layout.addLayout(toolbar)

        # 状态标签
        self.status_label = QLabel("加载角色列表中...")
        layout.addWidget(self.status_label)

        # 角色网格
        self.list_widget = QListWidget()
        self.list_widget.setViewMode(QListWidget.IconMode)
        self.list_widget.setIconSize(ICON_SIZE)
        self.list_widget.setResizeMode(QListWidget.Adjust)
        self.list_widget.setMovement(QListWidget.Static)
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setSpacing(8)
        self.list_widget.itemDoubleClicked.connect(self._on_item_activated)
        # 选中项变化时启用确认按钮
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget, stretch=1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        self.info_label = QLabel("")
        btn_layout.addWidget(self.info_label)
        btn_layout.addStretch()

        self.confirm_btn = QPushButton("确认")
        self.confirm_btn.setEnabled(False)
        self.confirm_btn.clicked.connect(self._on_confirm)
        btn_layout.addWidget(self.confirm_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

    # ── 后台加载 ────────────────────────────────────────

    def _start_loading(self) -> None:
        """启动后台线程加载角色列表和头像。"""
        self._thread = QThread()
        self._worker = _CharacterLoaderWorker()
        self._worker.moveToThread(self._thread)

        self._thread.started.connect(self._worker.run)
        self._worker.list_loaded.connect(self._on_list_loaded)
        self._worker.icon_loaded.connect(self._on_icon_loaded)
        self._worker.failed.connect(self._on_load_failed)
        # 线程结束时更新状态文本
        self._thread.finished.connect(self._on_loading_finished)

        self._thread.start()

    def _on_loading_finished(self) -> None:
        """后台线程全部任务完成（头像下载完毕或被取消）。"""
        if self._characters:
            # 统计缺失的头像数
            missing = sum(
                1 for c in self._characters
                if not (ICONS_DIR / f"character_{c.id}.webp").exists()
            )
            if missing > 0:
                self.status_label.setText(
                    f"共 {len(self._characters)} 个角色（{missing} 个头像下载失败）"
                )
            else:
                self.status_label.setText(
                    f"共 {len(self._characters)} 个角色（头像加载完成）"
                )

    def _on_list_loaded(self, chars: list) -> None:
        """角色列表加载完成。"""
        self._characters = chars
        self._id_to_char = {c.id: c for c in chars}
        self._refresh_list()
        # 统计已缓存/缺失的头像数
        cached = sum(
            1 for c in chars
            if (ICONS_DIR / f"character_{c.id}.webp").exists()
        )
        if cached == len(chars):
            self.status_label.setText(f"共 {len(chars)} 个角色（头像已全部缓存）")
        else:
            self.status_label.setText(
                f"共 {len(chars)} 个角色，正在下载头像（{cached}/{len(chars)}）..."
            )

    def _on_icon_loaded(self, char_id: str, path: str) -> None:
        """单个角色头像下载完成，更新对应 item。

        新下载的头像文件不在 _PIXMAP_CACHE 中，需要先加载到缓存。
        """
        # 清除旧缓存，重新加载（新下载的文件）
        _PIXMAP_CACHE.pop(char_id, None)
        pix = _load_character_icon(char_id)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(Qt.UserRole) == char_id:
                item.setIcon(QIcon(pix))
                break

    def _on_load_failed(self, err: str) -> None:
        """加载失败。"""
        self.status_label.setText(f"加载失败: {err}")

    # ── 列表显示与筛选 ──────────────────────────────────

    def _refresh_list(self) -> None:
        """根据当前筛选条件刷新列表。"""
        self.list_widget.clear()

        path_filter = self.path_combo.currentData()
        elem_filter = self.element_combo.currentData()
        keyword = self.search_edit.text().strip().lower()

        shown = 0
        for char in self._characters:
            # 命途筛选
            if path_filter and char.path != path_filter:
                continue
            # 属性筛选
            if elem_filter and char.element != elem_filter:
                continue
            # 关键词搜索（匹配中文名、英文名、ID）
            if keyword:
                name_zh = (char.name_zh or "").lower()
                name_en = (char.name_en or "").lower()
                if keyword not in name_zh and keyword not in name_en and keyword not in char.id.lower():
                    continue

            # 显示名：优先中文，回退英文
            display_name = char.name_zh or char.name_en or char.id
            # 命途/属性后缀（中文）
            path_zh = PATH_MAP.get(char.path, char.path)
            elem_zh = ELEMENT_MAP.get(char.element, char.element)
            tooltip = f"{display_name}\n命途: {path_zh}\n属性: {elem_zh}\n稀有度: {char.rarity}星"

            item = QListWidgetItem(display_name)
            item.setData(Qt.UserRole, char.id)
            item.setToolTip(tooltip)
            # 头像（可能尚未下载，先放占位）
            item.setIcon(QIcon(_load_character_icon(char.id)))
            self.list_widget.addItem(item)
            shown += 1

        self.info_label.setText(f"显示 {shown} / {len(self._characters)} 个角色")

    def _apply_filter(self) -> None:
        """筛选条件变化时刷新列表。"""
        if self._characters:
            self._refresh_list()

    # ── 选择与确认 ──────────────────────────────────────

    def _on_selection_changed(self) -> None:
        """列表选中项变化时启用/禁用确认按钮。"""
        has_selection = self.list_widget.currentItem() is not None
        self.confirm_btn.setEnabled(has_selection)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        """双击 item 直接确认选择。"""
        self._select_item(item)
        self.accept()

    def _select_item(self, item: QListWidgetItem) -> None:
        """标记当前选中项。"""
        char_id = item.data(Qt.UserRole)
        self.selected_character = self._id_to_char.get(char_id)

    def _on_confirm(self) -> None:
        """点击确认按钮。"""
        item = self.list_widget.currentItem()
        if item:
            self._select_item(item)
            self.accept()

    # ── 清理 ────────────────────────────────────────────

    def _stop_thread(self) -> None:
        """通知后台线程取消并等待其退出。

        必须等线程真正结束才能让 QThread 被销毁，否则会触发
        "QThread: Destroyed while thread is still running" 崩溃。
        若线程卡在网络请求上无法及时响应取消，则强制终止。
        """
        if self._worker is not None:
            self._worker.cancel_event.set()
        if self._thread is not None and self._thread.isRunning():
            # 等待线程检测到取消标志并退出（最多 1 秒）
            # 头像已缓存时线程通常已结束，wait 会立即返回
            if not self._thread.wait(1000):
                # 仍在运行（卡在网络请求），强制终止
                self._thread.terminate()
                self._thread.wait(1000)

    def done(self, result) -> None:
        """对话框关闭前停止线程。

        accept() / reject() / ESC / X 按钮 都会调用 done()，
        在此统一清理后台线程，避免线程在对话框销毁后仍在运行。
        """
        self._stop_thread()
        super().done(result)

    def closeEvent(self, event) -> None:
        """X 按钮关闭时也走 done() 的清理逻辑。"""
        self._stop_thread()
        super().closeEvent(event)


# ── 独立运行入口（调试用）──────────────────────────────────


def main() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dlg = CharacterPickerDialog()
    if dlg.exec() == QDialog.Accepted and dlg.selected_character:
        c = dlg.selected_character
        print(f"已选择: {c.name_zh} ({c.name_en})")
        print(f"  ID: {c.id}")
        print(f"  命途: {PATH_MAP.get(c.path, c.path)}")
        print(f"  属性: {ELEMENT_MAP.get(c.element, c.element)}")
        print(f"  稀有度: {c.rarity}星")
        print(f"  头像: {c.icon_url}")
    else:
        print("未选择")


if __name__ == "__main__":
    main()
