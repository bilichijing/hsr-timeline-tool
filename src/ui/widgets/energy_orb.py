"""圆形能量图标控件。

用于交互模拟中直观显示角色能量：
- 圆形图标，按能量百分比从底部向上填充颜色
- 图标顶端显示具体能量数值
- 满能量时高亮边框提示可释放终结技
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
    QPixmap,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from src.ui.theme import Colors


class EnergyOrbWidget(QWidget):
    """圆形能量图标（左侧带角色头像）。

    用法：
        orb = EnergyOrbWidget(name="角色A", max_energy=120)
        orb.set_energy(60)  # 设置当前能量
        orb.set_avatar(pixmap)  # 设置角色头像
    """

    def __init__(
        self,
        name: str = "",
        max_energy: float = 120.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._name = name
        self._max_energy = max_energy
        self._energy = 0.0
        self._is_active = False  # 是否当前行动者
        self._avatar: QPixmap | None = None  # 角色头像
        self.setMinimumSize(130, 100)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)

    def set_name(self, name: str) -> None:
        self._name = name
        self.update()

    def set_max_energy(self, max_energy: float) -> None:
        self._max_energy = max(1.0, max_energy)
        self.update()

    def set_energy(self, energy: float) -> None:
        self._energy = max(0.0, min(energy, self._max_energy))
        self.update()

    def set_active(self, active: bool) -> None:
        """标记为当前行动者（高亮外圈）。"""
        self._is_active = active
        self.update()

    def set_avatar(self, pixmap: QPixmap | None) -> None:
        """设置角色头像（左侧显示）。"""
        self._avatar = pixmap
        self.update()

    def is_full(self) -> bool:
        return self._energy >= self._max_energy

    def paintEvent(self, event) -> None:
        """绘制圆形能量图标（左侧头像 + 右侧能量圆）。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w = self.width()
        h = self.height()

        # 布局：左侧头像 + 右侧能量圆
        # 头像尺寸与圆形一致
        text_h = 18
        name_h = 16
        gap = 6  # 头像与圆形之间的间距

        # 计算圆形尺寸（右侧）
        circle_size = min(
            (w - gap) / 2 - 4,
            h - text_h - name_h - 4,
        )
        if circle_size < 30:
            circle_size = 30

        # 头像尺寸与圆形相同（左侧）
        avatar_size = circle_size
        avatar_x = 4
        avatar_y = text_h + 2 + (h - text_h - name_h - 4 - avatar_size) / 2

        # 圆形位置（右侧）
        circle_x = avatar_x + avatar_size + gap
        circle_y = text_h + 2 + (h - text_h - name_h - 4 - circle_size) / 2
        circle_rect = QRectF(circle_x, circle_y, circle_size, circle_size)
        avatar_rect = QRectF(avatar_x, avatar_y, avatar_size, avatar_size)

        # 1. 绘制顶部能量数值（居中于圆形上方）
        font = QFont("Microsoft YaHei UI", 9)
        font.setBold(True)
        painter.setFont(font)
        energy_text = f"{self._energy:.0f}/{self._max_energy:.0f}"
        text_color = QColor(Colors.GOLD) if self.is_full() else QColor(Colors.TEXT_PRIMARY)
        painter.setPen(text_color)
        text_rect = QRectF(circle_x - 4, 0, circle_size + 8, text_h)
        painter.drawText(text_rect, Qt.AlignCenter, energy_text)

        # 2. 绘制左侧角色头像
        if self._avatar and not self._avatar.isNull():
            painter.save()
            # 圆形裁剪区域
            clip_path = QPainterPath()
            clip_path.addEllipse(avatar_rect)
            painter.setClipPath(clip_path)
            # 缩放绘制头像
            scaled = self._avatar.scaled(
                int(avatar_size), int(avatar_size),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            # 居中绘制
            dx = avatar_rect.center().x() - scaled.width() / 2
            dy = avatar_rect.center().y() - scaled.height() / 2
            painter.drawPixmap(QPointF(dx, dy), scaled)
            painter.restore()
        else:
            # 无头像占位
            painter.setBrush(QBrush(QColor(Colors.BG_CARD)))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(avatar_rect)
            painter.setPen(QColor(Colors.TEXT_DISABLED))
            painter.drawText(avatar_rect, Qt.AlignCenter, "?")

        # 头像边框
        avatar_border = QColor(Colors.CYAN) if self._is_active else QColor(Colors.BORDER)
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(avatar_border, 2 if self._is_active else 1))
        painter.drawEllipse(avatar_rect)

        # 3. 绘制圆形背景（深色底）
        painter.setBrush(QBrush(QColor(Colors.BG_DEEPEST)))
        painter.setPen(QPen(QColor(Colors.BORDER), 1))
        painter.drawEllipse(circle_rect)

        # 4. 绘制能量填充（从底部向上按百分比填充）
        if self._energy > 0:
            ratio = self._energy / self._max_energy
            painter.save()
            painter.setClipPath(self._circle_fill_path(circle_rect, ratio))

            # 渐变色：低能量青色，高能量金色，满能量红色
            if self.is_full():
                fill_color = QColor(Colors.RED)
            elif ratio >= 0.7:
                fill_color = QColor(Colors.GOLD)
            else:
                fill_color = QColor(Colors.CYAN)

            gradient = QLinearGradient(
                QPointF(circle_rect.center().x(), circle_rect.bottom()),
                QPointF(circle_rect.center().x(), circle_rect.top()),
            )
            light = QColor(fill_color)
            light.setAlpha(180)
            gradient.setColorAt(0.0, fill_color)
            gradient.setColorAt(1.0, light)

            painter.setBrush(QBrush(gradient))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(circle_rect)
            painter.restore()

        # 5. 绘制圆形边框
        border_color = QColor(Colors.GOLD) if self.is_full() else QColor(Colors.BORDER)
        border_width = 2 if self.is_full() else 1
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(border_color, border_width))
        painter.drawEllipse(circle_rect)

        # 6. 绘制底部名称（横跨头像+圆形）
        font2 = QFont("Microsoft YaHei UI", 9)
        painter.setFont(font2)
        painter.setPen(QColor(Colors.TEXT_SECONDARY))
        name_rect = QRectF(avatar_x - 4, h - name_h, avatar_size + gap + circle_size + 8, name_h)
        painter.drawText(name_rect, Qt.AlignCenter, self._name)

    def _circle_fill_path(self, rect: QRectF, fill_ratio: float) -> QPainterPath:
        """生成圆形填充裁剪路径：圆形与底部矩形的交集。

        保留下方 fill_ratio 比例的部分，实现从底部向上填充的效果。
        """
        # 圆形路径
        circle_path = QPainterPath()
        circle_path.addEllipse(rect)

        # 填充矩形：从圆底部向上 fill_ratio 比例的高度
        fill_height = fill_ratio * rect.height()
        fill_rect = QRectF(
            rect.left(),
            rect.bottom() - fill_height,
            rect.width(),
            fill_height,
        )
        fill_path = QPainterPath()
        fill_path.addRect(fill_rect)

        # 取交集：只保留圆形内且在填充矩形内的部分
        return circle_path.intersected(fill_path)
