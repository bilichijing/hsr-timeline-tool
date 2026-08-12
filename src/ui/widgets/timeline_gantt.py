"""AV 时间轴甘特图控件。

用 QPainter 绘制行动队列，横轴为累计总行动值，每行一个单位（角色/怪物/阿哈）。
不同操作类型用不同颜色的圆点标记，悬停显示详细信息。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetrics,
    QMouseEvent,
    QPainter,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QToolTip, QWidget

from src.ui.theme import Colors

# ── 数据模型 ──────────────────────────────────────────────

@dataclass
class GanttAction:
    """甘特图上的单个行动标记。"""

    total_av: float           # 累计总行动值（横坐标）
    action_type: str          # normal/skill/ultra/monster/aha_moment
    damage: float = 0.0       # 总伤害
    note: str = ""            # 备注（如"击破"）


@dataclass
class GanttLane:
    """甘特图的一个行（对应一个单位）。"""

    unit_id: str
    name: str
    actions: list[GanttAction]


# ── 样式常量 ──────────────────────────────────────────────

# 不同操作类型的颜色
ACTION_COLORS: dict[str, QColor] = {
    "normal":     QColor(150, 160, 180),   # 灰蓝（普攻）
    "skill":      QColor(78, 197, 241),    # 青色（战技）
    "ultra":      QColor(212, 168, 87),    # 金色（终结技）
    "monster":    QColor(229, 84, 78),     # 红色（怪物）
    "aha_moment": QColor(232, 184, 87),    # 亮金（阿哈时刻）
    "follow_up":  QColor(168, 130, 212),   # 紫色（追加攻击）
}

ACTION_LABELS_ZH: dict[str, str] = {
    "normal": "普攻",
    "skill": "战技",
    "ultra": "终结技",
    "monster": "怪物行动",
    "aha_moment": "阿哈时刻",
    "follow_up": "追加攻击",
}

LANE_HEIGHT = 44
LANE_GAP = 8
LEFT_MARGIN = 100          # 左侧单位名标签宽度
RIGHT_MARGIN = 40
TOP_MARGIN = 36            # 顶部刻度
BOTTOM_MARGIN = 24
DOT_RADIUS = 10


class TimelineGanttWidget(QWidget):
    """AV 时间轴甘特图。

    用法：
        widget = TimelineGanttWidget()
        widget.set_data(lanes, max_av=300)
    """

    action_hovered = Signal(str, str)  # (unit_id, action_type)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._lanes: list[GanttLane] = []
        self._max_av: float = 300.0
        self._hover_pos: QPoint | None = None

        self.setMinimumHeight(300)
        self.setMouseTracking(True)
        # 启用背景绘制，否则透明
        self.setAutoFillBackground(True)

    # ── 公开接口 ──────────────────────────────────────

    def set_data(self, lanes: list[GanttLane], max_av: float | None = None) -> None:
        """设置甘特图数据。"""
        self._lanes = lanes
        if max_av is not None:
            self._max_av = max_av
        else:
            # 自动计算：取所有行动中最大的 total_av，向上取整到 50 的倍数
            all_avs = [a.total_av for lane in lanes for a in lane.actions]
            if all_avs:
                raw_max = max(all_avs)
                self._max_av = ((int(raw_max) // 50) + 1) * 50
            else:
                self._max_av = 300.0

        # 根据行数调整最小高度
        min_h = TOP_MARGIN + BOTTOM_MARGIN + len(self._lanes) * (LANE_HEIGHT + LANE_GAP)
        self.setMinimumHeight(min_h)
        self.update()

    def clear(self) -> None:
        """清空数据。"""
        self._lanes = []
        self.update()

    # ── 尺寸计算 ──────────────────────────────────────

    def sizeHint(self) -> QSize:
        h = TOP_MARGIN + BOTTOM_MARGIN + max(1, len(self._lanes)) * (LANE_HEIGHT + LANE_GAP)
        return QSize(800, h)

    def _av_to_x(self, av: float) -> float:
        """将行动值映射为画布 x 坐标。"""
        usable = max(1, self.width() - LEFT_MARGIN - RIGHT_MARGIN)
        return LEFT_MARGIN + (av / max(1.0, self._max_av)) * usable

    def _lane_y(self, lane_index: int) -> int:
        """行中心的 y 坐标。"""
        return TOP_MARGIN + lane_index * (LANE_HEIGHT + LANE_GAP) + LANE_HEIGHT // 2

    # ── 绘制 ──────────────────────────────────────────

    def paintEvent(self, event) -> None:
        if not self._lanes:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        self._draw_grid(painter)
        self._draw_scale(painter)
        for i, lane in enumerate(self._lanes):
            self._draw_lane(painter, lane, i)

    def _draw_grid(self, painter: QPainter) -> None:
        """绘制行背景与分隔线。"""
        painter.setPen(QPen(QColor(Colors.BORDER), 1))
        painter.setBrush(QBrush(QColor(Colors.BG_CARD)))

        for i, lane in enumerate(self._lanes):
            y = TOP_MARGIN + i * (LANE_HEIGHT + LANE_GAP)
            rect = QRect(LEFT_MARGIN, y, self.width() - LEFT_MARGIN - RIGHT_MARGIN, LANE_HEIGHT)
            painter.drawRoundedRect(rect, 4, 4)

            # 单位名标签
            painter.setPen(QPen(QColor(Colors.TEXT_PRIMARY)))
            font = QFont("Microsoft YaHei UI", 10, QFont.DemiBold)
            painter.setFont(font)
            painter.drawText(
                QRect(8, y, LEFT_MARGIN - 16, LANE_HEIGHT),
                Qt.AlignVCenter | Qt.AlignRight,
                lane.name,
            )
            painter.setPen(QPen(QColor(Colors.BORDER), 1))
            painter.setBrush(QBrush(QColor(Colors.BG_CARD)))

    def _draw_scale(self, painter: QPainter) -> None:
        """绘制顶部横轴刻度。"""
        painter.setPen(QPen(QColor(Colors.TEXT_SECONDARY)))
        font = QFont("Microsoft YaHei UI", 9)
        painter.setFont(font)

        # 每 50 AV 一个刻度
        step = 50
        if self._max_av > 600:
            step = 100
        av = 0.0
        while av <= self._max_av + 0.1:
            x = int(self._av_to_x(av))
            # 短刻度线
            painter.setPen(QPen(QColor(Colors.BORDER), 1, Qt.DashLine))
            painter.drawLine(x, TOP_MARGIN - 4, x, self.height() - BOTTOM_MARGIN)
            # 标签
            painter.setPen(QPen(QColor(Colors.TEXT_SECONDARY)))
            painter.drawText(
                QRect(x - 30, 4, 60, 20),
                Qt.AlignCenter,
                f"{int(av)}",
            )
            av += step

        # 标题
        painter.setPen(QPen(QColor(Colors.GOLD)))
        title_font = QFont("Microsoft YaHei UI", 9, QFont.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            QRect(LEFT_MARGIN - 40, self.height() - BOTTOM_MARGIN, 80, 20),
            Qt.AlignCenter,
            "总行动值",
        )

    def _draw_lane(self, painter: QPainter, lane: GanttLane, lane_index: int) -> None:
        """绘制一行（单个单位的行动点）。"""
        y = self._lane_y(lane_index)

        for action in lane.actions:
            x = self._av_to_x(action.total_av)
            color = ACTION_COLORS.get(action.action_type, QColor(150, 160, 180))

            # 外圈光晕
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
            painter.drawEllipse(QPoint(int(x), y), DOT_RADIUS + 4, DOT_RADIUS + 4)

            # 主圆点
            painter.setBrush(QBrush(color))
            painter.setPen(QPen(QColor(Colors.BG_DEEPEST), 1))
            painter.drawEllipse(QPoint(int(x), y), DOT_RADIUS, DOT_RADIUS)

            # 击破标记
            if "击破" in action.note:
                painter.setPen(QPen(QColor(Colors.RED), 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawEllipse(QPoint(int(x), y), DOT_RADIUS + 3, DOT_RADIUS + 3)

            # 操作类型字母（普/战/终/怪/哈）
            label_map = {"normal": "普", "skill": "战", "ultra": "终", "monster": "怪", "aha_moment": "哈", "follow_up": "追"}
            label = label_map.get(action.action_type, "?")
            painter.setPen(QPen(QColor(Colors.BG_DEEPEST)))
            font = QFont("Microsoft YaHei UI", 8, QFont.Bold)
            painter.setFont(font)
            painter.drawText(
                QRect(int(x) - DOT_RADIUS, y - DOT_RADIUS, DOT_RADIUS * 2, DOT_RADIUS * 2),
                Qt.AlignCenter,
                label,
            )

    # ── 鼠标交互 ──────────────────────────────────────

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """悬停显示行动详情。"""
        pos = event.position().toPoint()
        self._hover_pos = pos

        for i, lane in enumerate(self._lanes):
            lane_y = self._lane_y(i)
            for action in lane.actions:
                ax = self._av_to_x(action.total_av)
                dx = pos.x() - ax
                dy = pos.y() - lane_y
                if dx * dx + dy * dy <= (DOT_RADIUS + 2) ** 2:
                    action_label = ACTION_LABELS_ZH.get(action.action_type, action.action_type)
                    tip_lines = [
                        f"{lane.name} - {action_label}",
                        f"总行动值: {action.total_av:.1f}",
                    ]
                    if action.damage > 0:
                        tip_lines.append(f"伤害: {action.damage:.0f}")
                    if action.note:
                        tip_lines.append(f"备注: {action.note}")
                    QToolTip.showText(event.globalPosition().toPoint(), "\n".join(tip_lines), self)
                    self.action_hovered.emit(lane.unit_id, action.action_type)
                    return

        QToolTip.hideText()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        """点击空白区域不做处理（保留给未来扩展）。"""
        pass
