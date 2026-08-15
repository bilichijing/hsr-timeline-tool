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
    "technique":  QColor(120, 200, 170),   # 青绿（秘技）
    "countdown":  QColor(110, 180, 190),   # 青灰（倒计时，如无量忿怒）
    "enemy_attack": QColor(229, 84, 78),   # 红色（敌方攻击）
}

ACTION_LABELS_ZH: dict[str, str] = {
    "normal": "普攻",
    "skill": "战技",
    "ultra": "终结技",
    "monster": "怪物行动",
    "aha_moment": "阿哈时刻",
    "follow_up": "追加攻击",
    "technique": "秘技",
    "countdown": "倒计时",
    "enemy_attack": "敌方攻击",
}

LANE_HEIGHT = 80
LANE_GAP = 12
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
        # 横轴缩放/平移（滚轮缩放，按住拖动平移）
        self._zoom: float = 1.0
        self._scroll_offset: float = 0.0   # 可见窗口起点（AV）
        self._drag_start: QPoint | None = None
        self._drag_offset0: float = 0.0

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

    # ── 横轴缩放/平移 ────────────────────────────────

    def _visible_max_av(self) -> float:
        """当前可见的 AV 范围（缩放后）。"""
        return max(10.0, self._max_av / self._zoom)

    def wheelEvent(self, event) -> None:
        """滚轮缩放横轴（以鼠标位置为缩放中心）。"""
        factor = 1.25 if event.angleDelta().y() > 0 else 1 / 1.25
        new_zoom = min(max(self._zoom * factor, 0.5), 8.0)
        if new_zoom == self._zoom:
            return
        usable = max(1, self.width() - LEFT_MARGIN - RIGHT_MARGIN)
        visible = self._visible_max_av()
        # 鼠标位置对应的 AV（缩放前）
        av_at_mouse = self._scroll_offset + (event.position().x() - LEFT_MARGIN) / usable * visible
        self._zoom = new_zoom
        # 缩放后保持该 AV 仍在鼠标 x 处
        new_visible = self._visible_max_av()
        self._scroll_offset = av_at_mouse - (event.position().x() - LEFT_MARGIN) / usable * new_visible
        self._scroll_offset = max(0.0, self._scroll_offset)
        self.update()

    # ── 尺寸计算 ──────────────────────────────────────

    def sizeHint(self) -> QSize:
        h = TOP_MARGIN + BOTTOM_MARGIN + max(1, len(self._lanes)) * (LANE_HEIGHT + LANE_GAP)
        return QSize(800, h)

    def _av_to_x(self, av: float) -> float:
        """将行动值映射为画布 x 坐标（考虑缩放与平移）。"""
        usable = max(1, self.width() - LEFT_MARGIN - RIGHT_MARGIN)
        return LEFT_MARGIN + (av - self._scroll_offset) / self._visible_max_av() * usable

    def _lane_y(self, lane_index: int) -> int:
        """行中心的 y 坐标。"""
        return TOP_MARGIN + lane_index * (LANE_HEIGHT + LANE_GAP) + LANE_HEIGHT // 2

    # ── 绘制 ──────────────────────────────────────────

    def paintEvent(self, event) -> None:
        if not self._lanes:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 标签类（不裁剪）：行背景/角色名/刻度数字/底部标题
        self._draw_grid(painter)

        # 内容类（裁剪到甘特图区域 LEFT_MARGIN 右侧）：
        # 刻度数字/刻度线/行动点在拖动缩放时不会画进左侧标签区或超出右侧边界
        painter.save()
        painter.setClipRect(
            LEFT_MARGIN, 0,
            max(1, self.width() - LEFT_MARGIN - RIGHT_MARGIN),
            self.height(),
        )
        self._draw_scale(painter)
        self._draw_scale_lines(painter)
        for i, lane in enumerate(self._lanes):
            self._draw_lane(painter, lane, i)
        painter.restore()

        # 标题不裁剪（完整显示）
        self._draw_scale_title(painter)

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
        """绘制顶部横轴刻度数字（调用方已裁剪到甘特图区域）。"""
        painter.setPen(QPen(QColor(Colors.TEXT_SECONDARY)))
        font = QFont("Microsoft YaHei UI", 9)
        painter.setFont(font)

        # 步长按可见范围自适应：缩放越大刻度越密
        visible = self._visible_max_av()
        if visible <= 60:
            step = 5
        elif visible <= 120:
            step = 10
        elif visible <= 300:
            step = 25
        elif visible <= 600:
            step = 50
        else:
            step = 100
        # 可见窗口起点对齐步长
        start_av = max(0.0, int(self._scroll_offset // step) * step)
        av = start_av
        end_av = self._scroll_offset + visible
        while av <= end_av + 0.1:
            x = int(self._av_to_x(av))
            painter.drawText(
                QRect(x - 30, 4, 60, 20),
                Qt.AlignCenter,
                f"{int(av)}",
            )
            av += step

    def _draw_scale_title(self, painter: QPainter) -> None:
        """绘制顶部标题「总行动值」（不裁剪，完整显示）。"""
        painter.setPen(QPen(QColor(Colors.GOLD)))
        title_font = QFont("Microsoft YaHei UI", 9, QFont.DemiBold)
        painter.setFont(title_font)
        painter.drawText(
            # y 必须 ≥0（TOP_MARGIN-50 会越出控件顶部被边界裁剪，只剩下半截）
            QRect(LEFT_MARGIN - 10, self.height() - BOTTOM_MARGIN, 80, 20),
            Qt.AlignCenter,
            "总行动值",
        )

    def _draw_scale_lines(self, painter: QPainter) -> None:
        """绘制顶部刻度竖线（调用方已裁剪到甘特图区域）。"""
        visible = self._visible_max_av()
        if visible <= 60:
            step = 5
        elif visible <= 120:
            step = 10
        elif visible <= 300:
            step = 25
        elif visible <= 600:
            step = 50
        else:
            step = 100
        start_av = max(0.0, int(self._scroll_offset // step) * step)
        av = start_av
        end_av = self._scroll_offset + visible
        painter.setPen(QPen(QColor(Colors.BORDER), 1, Qt.DashLine))
        while av <= end_av + 0.1:
            x = int(self._av_to_x(av))
            painter.drawLine(x, TOP_MARGIN - 4, x, self.height() - BOTTOM_MARGIN)
            av += step

    def _draw_lane(self, painter: QPainter, lane: GanttLane, lane_index: int) -> None:
        """绘制一行（单个单位的行动点）。

        同一行动值（total_av）的多个事件（如终结技 + 追加攻击）按顺序
        从上到下纵向排列，避免重叠覆盖。
        """
        lane_y = self._lane_y(lane_index)
        # 稳定排序：同 AV 组内保持原始顺序（终结技在前、追加攻击在后）
        sorted_actions = sorted(lane.actions, key=lambda a: a.total_av)

        spacing = DOT_RADIUS * 2   # 同 AV 事件纵向间距
        i = 0
        while i < len(sorted_actions):
            av = sorted_actions[i].total_av
            j = i
            while j < len(sorted_actions) and sorted_actions[j].total_av == av:
                j += 1
            group = sorted_actions[i:j]
            # 组内纵向居中排列
            start_y = lane_y - (len(group) - 1) * spacing / 2
            for k, action in enumerate(group):
                self._draw_dot(painter, action, av, start_y + k * spacing)
            i = j

    def _draw_dot(self, painter: QPainter, action: GanttAction, av: float, y: float) -> None:
        """绘制单个行动点。"""
        x = self._av_to_x(av)
        color = ACTION_COLORS.get(action.action_type, QColor(150, 160, 180))

        # 外圈光晕
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 60)))
        painter.drawEllipse(QPoint(int(x), int(y)), DOT_RADIUS + 4, DOT_RADIUS + 4)

        # 主圆点
        painter.setBrush(QBrush(color))
        painter.setPen(QPen(QColor(Colors.BG_DEEPEST), 1))
        painter.drawEllipse(QPoint(int(x), int(y)), DOT_RADIUS, DOT_RADIUS)

        # 击破标记
        if "击破" in action.note:
            painter.setPen(QPen(QColor(Colors.RED), 2))
            painter.setBrush(Qt.NoBrush)
            painter.drawEllipse(QPoint(int(x), int(y)), DOT_RADIUS + 3, DOT_RADIUS + 3)

        # 操作类型字母（普/战/终/怪/哈/追/秘/倒）
        label_map = {"normal": "普", "skill": "战", "ultra": "终", "monster": "怪", "aha_moment": "哈", "follow_up": "追", "technique": "秘", "countdown": "倒"}
        label = label_map.get(action.action_type, "?")
        painter.setPen(QPen(QColor(Colors.BG_DEEPEST)))
        font = QFont("Microsoft YaHei UI", 8, QFont.Bold)
        painter.setFont(font)
        painter.drawText(
            QRect(int(x) - DOT_RADIUS, int(y) - DOT_RADIUS, DOT_RADIUS * 2, DOT_RADIUS * 2),
            Qt.AlignCenter,
            label,
        )

    # ── 鼠标交互 ──────────────────────────────────────

    def _action_positions(self, lane: GanttLane, lane_y: int) -> list[tuple[GanttAction, float, float]]:
        """返回 (action, x, y) 列表（与绘制一致的纵向排列位置）。"""
        result = []
        sorted_actions = sorted(lane.actions, key=lambda a: a.total_av)
        spacing = DOT_RADIUS * 2 + 8  # 同 AV 事件纵向间距（配合加大后的行高）
        i = 0
        while i < len(sorted_actions):
            av = sorted_actions[i].total_av
            j = i
            while j < len(sorted_actions) and sorted_actions[j].total_av == av:
                j += 1
            group = sorted_actions[i:j]
            start_y = lane_y - (len(group) - 1) * spacing / 2
            for k, action in enumerate(group):
                result.append((action, self._av_to_x(av), start_y + k * spacing))
            i = j
        return result

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        """悬停显示行动详情；按住左键拖动平移横轴。"""
        pos = event.position().toPoint()
        self._hover_pos = pos

        # 拖动平移
        if self._drag_start is not None:
            usable = max(1, self.width() - LEFT_MARGIN - RIGHT_MARGIN)
            dx_av = (self._drag_start.x() - pos.x()) / usable * self._visible_max_av()
            self._scroll_offset = max(0.0, self._drag_offset0 + dx_av)
            self.update()
            return

        for i, lane in enumerate(self._lanes):
            lane_y = self._lane_y(i)
            for action, ax, ay in self._action_positions(lane, lane_y):
                dx = pos.x() - ax
                dy = pos.y() - ay
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
        """按住左键开始拖动平移横轴。"""
        if event.button() == Qt.LeftButton:
            self._drag_start = event.position().toPoint()
            self._drag_offset0 = self._scroll_offset

    def mouseReleaseEvent(self, event) -> None:
        """松开左键结束拖动。"""
        if event.button() == Qt.LeftButton:
            self._drag_start = None
