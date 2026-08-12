"""伤害占比饼图控件。

使用 QtCharts 展示每个角色的伤害占比，配深色主题。
"""

from __future__ import annotations

from PySide6.QtCharts import QChart, QChartView, QPieSeries, QPieSlice
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QVBoxLayout, QWidget

from src.ui.theme import Colors

# 角色配色（循环使用）
CHART_COLORS = [
    QColor(212, 168, 87),    # 金
    QColor(78, 197, 241),    # 青
    QColor(181, 125, 238),   # 紫
    QColor(95, 201, 126),    # 绿
    QColor(229, 84, 78),     # 红
    QColor(232, 184, 87),    # 亮金
    QColor(126, 192, 224),   # 记忆蓝
    QColor(168, 86, 86),     # 暗红
]


class DamagePieChartWidget(QWidget):
    """伤害占比饼图。

    用法：
        widget = DamagePieChartWidget()
        widget.set_data([("角色A", 12345.0), ("角色B", 6789.0)])
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._chart = QChart()
        self._chart.setTitle("伤害占比")
        self._chart.setTitleFont(QFont("Microsoft YaHei UI", 12, QFont.DemiBold))
        self._chart.setTitleBrush(QColor(Colors.GOLD))
        self._chart.setAnimationOptions(QChart.SeriesAnimations)
        self._chart.legend().setAlignment(Qt.AlignRight)
        self._chart.legend().setLabelColor(Colors.TEXT_PRIMARY)
        self._chart.legend().setFont(QFont("Microsoft YaHei UI", 10))
        # 透明背景
        self._chart.setBackgroundVisible(False)
        self._chart.setPlotAreaBackgroundVisible(False)

        self._view = QChartView(self._chart)
        self._view.setRenderHint(QPainter.Antialiasing)
        self._view.setBackgroundBrush(QBrush(QColor(Colors.BG_PANEL)))
        layout.addWidget(self._view)

    def set_data(self, data: list[tuple[str, float]]) -> None:
        """设置饼图数据。

        Args:
            data: [(角色名, 总伤害), ...]，已按伤害降序
        """
        # 清空旧数据
        self._chart.removeAllSeries()

        if not data:
            return

        series = QPieSeries()
        # 过滤掉伤害为 0 的项
        total = sum(d for _, d in data)
        if total <= 0:
            return

        for i, (name, damage) in enumerate(data):
            if damage <= 0:
                continue
            pct = damage / total * 100
            slice_ = series.append(f"{name} ({pct:.1f}%)", damage)
            color = CHART_COLORS[i % len(CHART_COLORS)]
            slice_.setColor(color)
            slice_.setLabelColor(Colors.TEXT_PRIMARY)
            slice_.setLabelFont(QFont("Microsoft YaHei UI", 9))
            slice_.setLabelVisible(True)
            slice_.setLabelPosition(QPieSlice.LabelInsideHorizontal)
            # 边框
            slice_.setBorderWidth(2)
            slice_.setBorderColor(Colors.BG_DEEPEST)
            # 悬停效果
            slice_.setProperty("original_color", color)
            # QtCharts 没有直接 hover 信号，用 hovered
            slice_.hovered.connect(lambda state, s=slice_: self._on_slice_hover(state, s))

        # 突出最大占比
        slices = series.slices()
        if slices:
            slices[0].setExploded(True)
            slices[0].setLabelPosition(QPieSlice.LabelOutside)

        self._chart.addSeries(series)

    def _on_slice_hover(self, hovered: bool, slice_: QPieSlice) -> None:
        """悬停时突出显示。"""
        orig = slice_.property("original_color")
        if not isinstance(orig, QColor):
            return
        if hovered:
            # 亮一点
            lighter = orig.lighter(130)
            slice_.setColor(lighter)
            slice_.setLabelFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
        else:
            slice_.setColor(orig)
            slice_.setLabelFont(QFont("Microsoft YaHei UI", 9))

    def clear(self) -> None:
        """清空数据。"""
        self._chart.removeAllSeries()
