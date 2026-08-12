"""战技点（SP）图标控件。

用于交互模拟中直观显示当前战技点：
- 5 个菱形图标横向排列（SP 上限为 5）
- 已有 SP 的菱形填充金色渐变并发光
- 未激活的菱形暗灰色
- 顶端显示 "SP: 当前/上限"
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.ui.theme import Colors

SP_MAX = 5  # SP 上限


class SPIndicatorWidget(QWidget):
    """战技点图标控件（5 个菱形）。

    用法：
        sp = SPIndicatorWidget()
        sp.set_sp(3)  # 当前 3 点 SP
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sp = 0
        self._max_sp = SP_MAX
        self.setMinimumSize(160, 90)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_sp(self, sp: int) -> None:
        """设置当前 SP 值。"""
        self._sp = max(0, min(int(sp), self._max_sp))
        self.update()

    def paintEvent(self, event) -> None:
        """绘制 SP 图标（5 个菱形 + 顶部数值 + 底部标签）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        text_h = 16
        label_h = 14
        # 使用固定尺寸，避免控件高度变化导致菱形被放大
        diamond_h = 44
        diamond_w = 28  # 菱形宽高比

        # 5 个菱形横向居中排列
        gap = 4
        total_w = SP_MAX * diamond_w + (SP_MAX - 1) * gap
        start_x = (w - total_w) / 2
        # 菱形在文本和标签之间垂直居中
        avail_h = h - text_h - label_h
        center_y = text_h + (avail_h - diamond_h) / 2 + diamond_h / 2

        # 1. 顶部数值 "SP: 3/5"
        font = QFont("Microsoft YaHei UI", 9)
        font.setBold(True)
        painter.setFont(font)
        sp_text = f"SP: {self._sp}/{self._max_sp}"
        # SP 为 0 时红色警示
        text_color = QColor(Colors.RED) if self._sp == 0 else QColor(Colors.GOLD)
        painter.setPen(text_color)
        text_rect = QRectF(0, 0, w, text_h)
        painter.drawText(text_rect, Qt.AlignCenter, sp_text)

        # 2. 绘制 5 个菱形
        for i in range(SP_MAX):
            cx = start_x + i * (diamond_w + gap) + diamond_w / 2
            cy = center_y
            self._draw_diamond(painter, cx, cy, diamond_w, diamond_h, active=(i < self._sp))

        # 3. 底部标签
        font2 = QFont("Microsoft YaHei UI", 9)
        painter.setFont(font2)
        painter.setPen(QColor(Colors.TEXT_SECONDARY))
        label_rect = QRectF(0, h - label_h, w, label_h)
        painter.drawText(label_rect, Qt.AlignCenter, "战技点")

    def _draw_diamond(
        self,
        painter: QPainter,
        cx: float,
        cy: float,
        w: float,
        h: float,
        active: bool,
    ) -> None:
        """绘制单个菱形（钻石）图标。

        Args:
            cx, cy: 菱形中心坐标
            w, h: 菱形宽高
            active: 是否激活（已有 SP）
        """
        # 菱形四个顶点：上、右、下、左
        path = QPainterPath()
        path.moveTo(cx, cy - h / 2)          # 上
        path.lineTo(cx + w / 2, cy)          # 右
        path.lineTo(cx, cy + h / 2)          # 下
        path.lineTo(cx - w / 2, cy)          # 左
        path.closeSubpath()

        if active:
            # 激活：金色渐变填充
            gradient = QLinearGradient(
                QPointF(cx, cy - h / 2),
                QPointF(cx, cy + h / 2),
            )
            top_color = QColor(Colors.GOLD_HOVER)
            bottom_color = QColor(Colors.GOLD)
            gradient.setColorAt(0.0, top_color)
            gradient.setColorAt(1.0, bottom_color)
            painter.setBrush(QBrush(gradient))
            painter.setPen(QPen(QColor(Colors.GOLD), 1.5))

            # 发光效果：先绘制一层半透明大菱形
            painter.save()
            glow_path = QPainterPath()
            glow_w = w + 4
            glow_h = h + 4
            glow_path.moveTo(cx, cy - glow_h / 2)
            glow_path.lineTo(cx + glow_w / 2, cy)
            glow_path.lineTo(cx, cy + glow_h / 2)
            glow_path.lineTo(cx - glow_w / 2, cy)
            glow_path.closeSubpath()
            glow_color = QColor(Colors.GOLD)
            glow_color.setAlpha(60)
            painter.setBrush(QBrush(glow_color))
            painter.setPen(Qt.NoPen)
            painter.drawPath(glow_path)
            painter.restore()

            # 再绘制主菱形
            painter.setBrush(QBrush(gradient))
            painter.setPen(QPen(QColor(Colors.GOLD), 1.5))
            painter.drawPath(path)

            # 高光：上半部分浅色三角
            highlight = QPainterPath()
            highlight.moveTo(cx, cy - h / 2)
            highlight.lineTo(cx + w / 2, cy)
            highlight.lineTo(cx - w / 2, cy)
            highlight.closeSubpath()
            highlight_color = QColor(255, 255, 255, 50)
            painter.setBrush(QBrush(highlight_color))
            painter.setPen(Qt.NoPen)
            painter.drawPath(highlight)
        else:
            # 未激活：暗灰色
            painter.setBrush(QBrush(QColor(Colors.BG_CARD)))
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.drawPath(path)
