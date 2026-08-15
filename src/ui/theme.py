"""深色游戏风 QSS 主题。

设计灵感：《崩坏：星穹铁道》UI 配色
- 背景：深蓝黑（#0E1320 → #1A2030）
- 主色调：星轨金 #D4A857
- 强调色：以太青 #4EC5F1、虚数紫 #B57DEE
- 文字：浅灰白 #E4E7ED

使用：app.setStyleSheet(theme.DARK_STYLE)
"""

from __future__ import annotations

# ── 色板 ──────────────────────────────────────────────────

class Colors:
    """主题色板常量，供代码中直接引用。"""

    # 背景层
    BG_DEEPEST = "#0A0E17"      # 最深层（窗口背景）
    BG_DARK = "#0E1320"         # 主背景
    BG_PANEL = "#161C2C"        # 面板背景
    BG_CARD = "#1E2640"         # 卡片/单元格背景
    BG_HOVER = "#2A3450"        # 悬停态
    BG_SELECTED = "#3A4870"     # 选中态

    # 文字
    TEXT_PRIMARY = "#E4E7ED"    # 主文字
    TEXT_SECONDARY = "#9BA3B4"  # 次要文字
    TEXT_DISABLED = "#5C6478"   # 禁用文字

    # 主色
    GOLD = "#D4A857"            # 星轨金（主按钮、标题）
    GOLD_HOVER = "#E6BB6A"
    GOLD_PRESSED = "#B89045"

    # 强调色
    CYAN = "#4EC5F1"            # 以太青（链接、聚焦）
    PURPLE = "#B57DEE"          # 虚数紫
    RED = "#E5544E"             # 危险/伤害
    GREEN = "#5FC97E"           # 成功/治疗

    # 边框
    BORDER = "#2A3450"
    BORDER_FOCUS = "#4EC5F1"

    # 属性色（用于属性图标/标签）
    ELEMENT_PHYSICAL = "#C0C0C0"
    ELEMENT_FIRE = "#E8542E"
    ELEMENT_ICE = "#5BB5E8"
    ELEMENT_THUNDER = "#B57DEE"
    ELEMENT_WIND = "#5FC97E"
    ELEMENT_QUANTUM = "#9B6EDC"
    ELEMENT_IMAGINARY = "#E8B857"

    # 命途色（用于命途标签）
    PATH_KNIGHT = "#7E9CB8"     # 存护
    PATH_ROGUE = "#A85656"      # 巡猎
    PATH_MAGE = "#8E7BC0"       # 智识
    PATH_WARLOCK = "#7B5EA0"    # 虚无
    PATH_SHAMAN = "#D4A857"     # 同谐
    PATH_PRIEST = "#5FAC6B"     # 丰饶
    PATH_WARRIOR = "#C7622E"    # 毁灭
    PATH_MEMORY = "#7EC0E0"     # 记忆
    PATH_ELATION = "#E8B857"    # 欢愉


# ── QSS 样式表 ────────────────────────────────────────────

DARK_STYLE = f"""
/* ── 全局 ─────────────────────────────────────── */
QWidget {{
    background-color: {Colors.BG_DARK};
    color: {Colors.TEXT_PRIMARY};
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
}}

QMainWindow {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 {Colors.BG_DEEPEST},
        stop: 0.45 {Colors.BG_DARK},
        stop: 1 #0F1626
    );
}}
QDialog {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {Colors.BG_DARK},
        stop: 1 {Colors.BG_DEEPEST}
    );
}}

/* ── 滚动条 ───────────────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 2px;
    border-radius: 5px;
}}
QScrollBar::handle:vertical {{
    background: {Colors.BG_HOVER};
    min-height: 30px;
    border-radius: 5px;
    border: 1px solid {Colors.BORDER};
}}
QScrollBar::handle:vertical:hover {{
    background: {Colors.BG_SELECTED};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 2px;
    border-radius: 5px;
}}
QScrollBar::handle:horizontal {{
    background: {Colors.BG_HOVER};
    min-width: 30px;
    border-radius: 5px;
    border: 1px solid {Colors.BORDER};
}}
QScrollBar::handle:horizontal:hover {{
    background: {Colors.BG_SELECTED};
}}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ── 按钮 ─────────────────────────────────────── */
QPushButton {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {Colors.BG_CARD},
        stop: 1 {Colors.BG_PANEL}
    );
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    padding: 7px 16px;
    font-weight: 500;
}}
QPushButton:hover {{
    background: {Colors.BG_HOVER};
    border-color: {Colors.CYAN};
}}
QPushButton:pressed {{
    background: {Colors.BG_SELECTED};
    border-color: {Colors.CYAN};
}}
QPushButton:disabled {{
    color: {Colors.TEXT_DISABLED};
    background: {Colors.BG_PANEL};
    border-color: {Colors.BG_PANEL};
}}
QPushButton#primaryBtn {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #C89A45,
        stop: 0.5 {Colors.GOLD},
        stop: 1 #E4C06B
    );
    color: {Colors.BG_DEEPEST};
    border: 1px solid #E4C06B;
    font-weight: 700;
    padding: 10px 20px;
    min-height: 22px;
}}
QPushButton#primaryBtn:hover {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #D6A958,
        stop: 0.5 {Colors.GOLD_HOVER},
        stop: 1 #F0D08B
    );
    border-color: #F0D08B;
}}
QPushButton#primaryBtn:pressed {{
    background: {Colors.GOLD_PRESSED};
    border-color: {Colors.GOLD_PRESSED};
}}
QPushButton#dangerBtn {{
    background: transparent;
    color: {Colors.RED};
    border: 1px solid {Colors.RED};
}}
QPushButton#dangerBtn:hover {{
    background-color: {Colors.RED};
    color: {Colors.BG_DEEPEST};
}}

/* ── 输入控件 ─────────────────────────────────── */
QLineEdit,
QPlainTextEdit,
QTextEdit,
QSpinBox,
QComboBox {{
    background-color: {Colors.BG_PANEL};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {Colors.CYAN};
    selection-color: {Colors.BG_DEEPEST};
}}
QLineEdit:focus,
QPlainTextEdit:focus,
QTextEdit:focus,
QSpinBox:focus,
QComboBox:focus {{
    border: 1px solid {Colors.BORDER_FOCUS};
    background-color: #121A2B;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {Colors.GOLD};
    margin-right: 6px;
}}
QSpinBox::up-button,
QSpinBox::down-button {{
    width: 0px;
    border: none;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background-color: {Colors.BG_CARD};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER_FOCUS};
    border-radius: 6px;
    selection-background-color: {Colors.BG_SELECTED};
    outline: none;
    padding: 4px;
}}

/* ── 表格 ─────────────────────────────────────── */
QTableWidget {{
    background-color: {Colors.BG_PANEL};
    alternate-background-color: #151C2D;
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    gridline-color: #202A40;
    selection-background-color: {Colors.BG_SELECTED};
    selection-color: {Colors.TEXT_PRIMARY};
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {Colors.BG_SELECTED};
    color: #FFFFFF;
}}
QHeaderView::section {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {Colors.BG_CARD},
        stop: 1 {Colors.BG_DARK}
    );
    color: {Colors.GOLD};
    padding: 8px 8px;
    border: none;
    border-right: 1px solid {Colors.BORDER};
    border-bottom: 1px solid {Colors.GOLD_PRESSED};
    font-weight: 600;
}}
QTableCornerButton::section {{
    background-color: {Colors.BG_CARD};
    border: none;
    border-bottom: 1px solid {Colors.BORDER};
}}

/* ── 列表（角色选择器网格）───────────────────── */
QListWidget {{
    background-color: {Colors.BG_PANEL};
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    outline: none;
}}
QListWidget::item {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 0, y2: 1,
        stop: 0 {Colors.BG_CARD},
        stop: 1 {Colors.BG_PANEL}
    );
    border: 1px solid {Colors.BORDER};
    border-radius: 8px;
    margin: 4px;
    padding: 6px;
}}
QListWidget::item:hover {{
    background: {Colors.BG_HOVER};
    border: 1px solid {Colors.CYAN};
}}
QListWidget::item:selected {{
    background: {Colors.BG_SELECTED};
    border: 1px solid {Colors.GOLD};
}}

/* ── 标签 ─────────────────────────────────────── */
QLabel {{
    background: transparent;
    color: {Colors.TEXT_PRIMARY};
}}
QLabel#title {{
    color: {Colors.GOLD};
    font-size: 16px;
    font-weight: 700;
}}
QLabel#subtitle {{
    color: {Colors.TEXT_SECONDARY};
    font-size: 12px;
}}
QLabel#sectionLabel {{
    color: {Colors.GOLD};
    font-size: 13px;
    font-weight: 700;
    padding: 2px 0;
}}

/* ── 侧栏专属组件 ─────────────────────────────── */
QFrame#sidebarHeader {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 1,
        stop: 0 #141C30,
        stop: 0.5 #1C2338,
        stop: 1 #251F2E
    );
    border: 1px solid {Colors.BORDER};
    border-radius: 12px;
}}
QLabel#sidebarBrand {{
    color: {Colors.GOLD};
    font-size: 17px;
    font-weight: 800;
    letter-spacing: 1px;
}}
QLabel#sidebarSub {{
    color: {Colors.TEXT_SECONDARY};
    font-size: 10px;
    letter-spacing: 1px;
}}
QLabel#liveBadge {{
    background-color: rgba(78, 197, 241, 36);
    color: {Colors.CYAN};
    border: 1px solid {Colors.CYAN};
    border-radius: 8px;
    padding: 1px 7px;
    font-size: 10px;
    font-weight: 700;
}}
QFrame#previewPanel {{
    background-color: #101725;
    border: 1px solid {Colors.BORDER};
    border-radius: 10px;
}}
QLabel#previewRange {{
    color: {Colors.TEXT_SECONDARY};
    font-size: 10px;
}}
/* ── 分组框 ───────────────────────────────────── */
QGroupBox {{
    background-color: {Colors.BG_PANEL};
    border: 1px solid {Colors.BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 14px 10px 10px 10px;
    font-weight: 700;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 8px;
    color: {Colors.GOLD};
    background-color: {Colors.BG_DARK};
    border-radius: 4px;
}}

/* ── Tab ──────────────────────────────────────── */
QTabWidget::pane {{
    background-color: {Colors.BG_PANEL};
    border: 1px solid {Colors.BORDER};
    border-radius: 10px;
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {Colors.TEXT_SECONDARY};
    padding: 9px 20px;
    margin-right: 4px;
    border: 1px solid transparent;
    border-bottom: 2px solid transparent;
    border-radius: 8px 8px 0 0;
    font-weight: 600;
}}
QTabBar::tab:hover {{
    background-color: {Colors.BG_HOVER};
    color: {Colors.TEXT_PRIMARY};
}}
QTabBar::tab:selected {{
    background-color: {Colors.BG_PANEL};
    color: {Colors.GOLD};
    border-color: {Colors.BORDER};
    border-bottom: 2px solid {Colors.GOLD};
}}

/* ── 菜单 ─────────────────────────────────────── */
QMenuBar {{
    background-color: {Colors.BG_DEEPEST};
    color: {Colors.TEXT_PRIMARY};
    border-bottom: 1px solid {Colors.BORDER};
    padding: 2px;
}}
QMenuBar::item {{
    background: transparent;
    padding: 6px 12px;
    border-radius: 4px;
}}
QMenuBar::item:selected {{
    background-color: {Colors.BG_HOVER};
}}
QMenu {{
    background-color: {Colors.BG_CARD};
    border: 1px solid {Colors.BORDER_FOCUS};
    border-radius: 8px;
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 26px;
    border-radius: 5px;
}}
QMenu::item:selected {{
    background-color: {Colors.BG_SELECTED};
}}
QMenu::indicator {{
    width: 14px;
    height: 14px;
    border: 1px solid {Colors.TEXT_SECONDARY};
    border-radius: 3px;
    background-color: {Colors.BG_PANEL};
}}
QMenu::indicator:checked {{
    background-color: {Colors.GOLD};
    border-color: {Colors.GOLD};
}}
QMenu::separator {{
    height: 1px;
    background-color: {Colors.BORDER};
    margin: 4px 8px;
}}

/* ── 工具提示 ─────────────────────────────────── */
QToolTip {{
    background-color: {Colors.BG_CARD};
    color: {Colors.TEXT_PRIMARY};
    border: 1px solid {Colors.CYAN};
    border-radius: 6px;
    padding: 6px 9px;
}}

/* ── 复选框 ───────────────────────────────────── */
QCheckBox {{
    background: transparent;
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {Colors.BORDER};
    border-radius: 4px;
    background-color: {Colors.BG_PANEL};
}}
QCheckBox::indicator:hover {{
    border-color: {Colors.CYAN};
}}
QCheckBox::indicator:checked {{
    background-color: {Colors.GOLD};
    border-color: {Colors.GOLD};
}}

/* ── 进度条 ───────────────────────────────────── */
QProgressBar {{
    background-color: {Colors.BG_PANEL};
    border: 1px solid {Colors.BORDER};
    border-radius: 5px;
    text-align: center;
    color: {Colors.TEXT_PRIMARY};
}}
QProgressBar::chunk {{
    background: qlineargradient(
        x1: 0, y1: 0, x2: 1, y2: 0,
        stop: 0 #C89A45,
        stop: 1 {Colors.GOLD}
    );
    border-radius: 4px;
}}
"""

# ── 命途/属性 → 颜色映射（供自定义控件使用）──────────────

PATH_COLORS: dict[str, str] = {
    "Knight": Colors.PATH_KNIGHT,
    "Rogue": Colors.PATH_ROGUE,
    "Mage": Colors.PATH_MAGE,
    "Warlock": Colors.PATH_WARLOCK,
    "Shaman": Colors.PATH_SHAMAN,
    "Priest": Colors.PATH_PRIEST,
    "Warrior": Colors.PATH_WARRIOR,
    "Memory": Colors.PATH_MEMORY,
    "Elation": Colors.PATH_ELATION,
}

ELEMENT_COLORS: dict[str, str] = {
    "Physical": Colors.ELEMENT_PHYSICAL,
    "Fire": Colors.ELEMENT_FIRE,
    "Ice": Colors.ELEMENT_ICE,
    "Thunder": Colors.ELEMENT_THUNDER,
    "Wind": Colors.ELEMENT_WIND,
    "Quantum": Colors.ELEMENT_QUANTUM,
    "Imaginary": Colors.ELEMENT_IMAGINARY,
}
