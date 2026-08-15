"""敌方目标选择卡片：名称 + 血条 + 韧性条，点击选中。

用于交互模拟的敌方目标选择框。选中态由外部管理（互斥），
点击卡片时发出 clicked(unit_id) 信号，外部据此切换选中并记录主目标。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.ui.theme import Colors

WIDTH = 210
HEIGHT = 72

# 血条 / 韧性条配色
HP_COLOR = "#5FC97E"          # 生命（绿）
TOUGHNESS_COLOR = "#E8B857"   # 韧性（虚数金）
TOUGHNESS_BROKEN_COLOR = "#9BA3B4"  # 击破后（灰）
BAR_BG = "#2A3450"            # 条背景


class EnemyTargetWidget(QWidget):
    """敌方目标卡片：名称 + 血条 + 韧性条。"""

    clicked = Signal(str)          # unit_id
    double_clicked = Signal(str)   # unit_id

    def __init__(self, unit_id: str, name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._unit_id = unit_id
        self._name = name
        self._checked = False
        self._hp = 1.0
        self._hp_max = 1.0
        self._toughness = 1.0
        self._toughness_max = 1.0
        self._broken = False
        self.setFixedSize(WIDTH, HEIGHT)
        self.setCursor(Qt.PointingHandCursor)

    @property
    def unit_id(self) -> str:
        return self._unit_id

    def set_hp(self, current: float, maximum: float) -> None:
        """更新血条（current/maximum）。"""
        self._hp = max(0.0, current)
        self._hp_max = maximum if maximum > 0 else 1.0
        self.update()

    def set_toughness(self, current: float, maximum: float, broken: bool) -> None:
        """更新韧性条与击破标记。"""
        self._toughness = max(0.0, current)
        self._toughness_max = maximum if maximum > 0 else 1.0
        self._broken = broken
        self.update()

    def set_checked(self, checked: bool) -> None:
        """设置选中态（高亮边框）。"""
        self._checked = checked
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit(self._unit_id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit(self._unit_id)
        super().mouseDoubleClickEvent(event)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 卡片背景与选中边框
        border = Colors.GOLD if self._checked else Colors.BORDER
        painter.setPen(QPen(QColor(border), 2 if self._checked else 1))
        painter.setBrush(QColor(Colors.BG_CARD))
        painter.drawRoundedRect(
            QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0), 6, 6
        )

        # 名称（左侧，垂直居中）
        painter.setPen(QColor(Colors.TEXT_PRIMARY))
        name_font = QFont()
        name_font.setPointSize(9)
        name_font.setBold(True)
        painter.setFont(name_font)
        painter.drawText(
            QRectF(8, 0, 66, self.height()),
            Qt.AlignLeft | Qt.AlignVCenter,
            self._name,
        )

        # 右侧：血条 + 韧性条（纵向堆叠）
        bar_x = 80
        bar_w = self.width() - bar_x - 10
        self._draw_bar(
            painter, bar_x, 12, bar_w, 16,
            self._hp / self._hp_max, HP_COLOR,
            f"HP {self._hp:,.0f}/{self._hp_max:,.0f}",
        )
        tcolor = TOUGHNESS_BROKEN_COLOR if self._broken else TOUGHNESS_COLOR
        self._draw_bar(
            painter, bar_x, 40, bar_w, 16,
            self._toughness / self._toughness_max, tcolor,
            f"韧 {self._toughness:.0f}/{self._toughness_max:.0f}",
        )

    def _draw_bar(
        self,
        painter: QPainter,
        x: float,
        y: float,
        width: float,
        height: float,
        ratio: float,
        color: str,
        text: str,
    ) -> None:
        """绘制一条进度条（背景 + 填充 + 居中文字）。"""
        rect = QRectF(x, y, width, height)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(BAR_BG))
        painter.drawRoundedRect(rect, 4, 4)
        ratio = max(0.0, min(1.0, ratio))
        if ratio > 0:
            painter.setBrush(QColor(color))
            painter.drawRoundedRect(QRectF(x, y, width * ratio, height), 4, 4)
        # 文字
        painter.setPen(QColor(Colors.TEXT_PRIMARY))
        bar_font = QFont()
        bar_font.setPointSize(7)
        painter.setFont(bar_font)
        painter.drawText(rect, Qt.AlignCenter, text)
