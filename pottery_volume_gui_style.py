"""Qt stylesheet for the pottery volume desktop interface.

Plain, neutral look in the style of common open-source desktop tools:
light gray window, white inputs, thin borders and a single blue accent.
"""

COLOR_BG = "#f6f8fa"
COLOR_SURFACE = "#ffffff"
COLOR_BORDER = "#d0d7de"
COLOR_TEXT = "#1f2328"
COLOR_MUTED = "#656d76"
COLOR_ACCENT = "#0969da"
COLOR_ACCENT_DARK = "#0550ae"
COLOR_HOVER = "#eaeef2"
COLOR_PRESSED = "#d8dee4"
COLOR_SELECTION = "#ddf4ff"
COLOR_DISABLED = "#8c959f"

FONT_UI = "'Yu Gothic UI', 'Meiryo UI', 'Noto Sans CJK JP', 'Noto Sans JP', 'Hiragino Kaku Gothic ProN', sans-serif"
FONT_MONO = "'Cascadia Mono', Consolas, Menlo, 'DejaVu Sans Mono', monospace"

APP_STYLESHEET = f"""
QWidget {{ color: {COLOR_TEXT}; font-family: {FONT_UI}; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {COLOR_BG}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}

QLabel#status {{ color: {COLOR_MUTED}; background: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; padding: 6px 10px; }}
QLabel#caption {{ color: {COLOR_MUTED}; }}
QLabel#bigValue {{ font-size: 20pt; font-weight: 600; font-family: {FONT_MONO}; }}
QLabel#details {{ padding-top: 8px; }}

QGroupBox {{ background: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER}; border-radius: 6px; margin-top: 10px; padding: 12px 10px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {COLOR_MUTED}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser {{ background: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER}; border-radius: 5px; padding: 3px 6px; selection-background-color: {COLOR_SELECTION}; selection-color: {COLOR_TEXT}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextBrowser:focus {{ border: 1px solid {COLOR_ACCENT}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {COLOR_DISABLED}; background: {COLOR_BG}; }}
QPlainTextEdit, QTextBrowser {{ font-family: {FONT_MONO}; }}

QPushButton {{ background: {COLOR_BG}; border: 1px solid {COLOR_BORDER}; border-radius: 5px; padding: 5px 12px; }}
QPushButton:hover {{ background: {COLOR_HOVER}; }}
QPushButton:pressed {{ background: {COLOR_PRESSED}; }}
QPushButton:disabled {{ color: {COLOR_DISABLED}; background: {COLOR_BG}; }}
QPushButton#primaryAction {{ background: {COLOR_ACCENT}; border: 1px solid {COLOR_ACCENT_DARK}; color: #ffffff; font-weight: 600; padding: 7px 14px; }}
QPushButton#primaryAction:hover {{ background: {COLOR_ACCENT_DARK}; }}
QPushButton#primaryAction:disabled {{ background: #94c1f0; border-color: #94c1f0; }}

QSplitter::handle {{ background: {COLOR_BORDER}; }}
QSplitter::handle:horizontal {{ width: 1px; margin: 0 6px; }}

QTableWidget {{ background: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER}; gridline-color: {COLOR_BORDER}; selection-background-color: {COLOR_SELECTION}; selection-color: {COLOR_TEXT}; }}
QHeaderView::section {{ background: {COLOR_BG}; border: 0; border-right: 1px solid {COLOR_BORDER}; border-bottom: 1px solid {COLOR_BORDER}; padding: 4px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {COLOR_BG}; border: 0; border-right: 1px solid {COLOR_BORDER}; border-bottom: 1px solid {COLOR_BORDER}; }}

QMenu {{ background: {COLOR_SURFACE}; border: 1px solid {COLOR_BORDER}; padding: 4px; }}
QMenu::item {{ padding: 5px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {COLOR_SELECTION}; color: {COLOR_TEXT}; }}
QMenu::item:disabled {{ color: {COLOR_DISABLED}; }}
QMenu::separator {{ height: 1px; background: {COLOR_BORDER}; margin: 4px 6px; }}
QToolTip {{ background: {COLOR_SURFACE}; color: {COLOR_TEXT}; border: 1px solid {COLOR_BORDER}; padding: 3px; }}
"""
