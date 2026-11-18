"""Qt stylesheet shared by the pottery volume desktop interface."""

COLOR_TEXT = "#172033"
COLOR_TITLE = "#111827"
COLOR_WINDOW = "#f3f6fb"
COLOR_STATUS_BACKGROUND = "#e8f0ff"
COLOR_STATUS_TEXT = "#1e3a66"
COLOR_STATUS_BORDER = "#cbdaf5"
COLOR_SURFACE = "#ffffff"
COLOR_GROUP_BORDER = "#d8e0eb"
COLOR_GROUP_TITLE = "#334155"
COLOR_CONTROL_BORDER = "#cbd5e1"
COLOR_SELECTION = "#bfdbfe"
COLOR_FOCUS = "#4f8de8"
COLOR_BUTTON_HOVER = "#eff6ff"
COLOR_BUTTON_HOVER_BORDER = "#93b4e8"
COLOR_BUTTON_PRESSED = "#dbeafe"
COLOR_DISABLED_TEXT = "#94a3b8"
COLOR_DISABLED_BACKGROUND = "#eef1f5"
COLOR_PRIMARY = "#2563eb"
COLOR_PRIMARY_BORDER = "#1d4ed8"
COLOR_SPLITTER = "#e2e8f0"
COLOR_TABLE_HEADER = "#eef3f9"

APP_STYLESHEET = f"""
QWidget {{ color: {COLOR_TEXT}; font-family: 'Yu Gothic UI', 'Meiryo UI', 'Noto Sans CJK JP', 'Noto Sans JP', 'Hiragino Kaku Gothic ProN', sans-serif; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {COLOR_WINDOW}; }}
QLabel#appTitle {{ color: {COLOR_TITLE}; font-size: 21pt; font-weight: 700; }}
QLabel#statusMessage {{ background: {COLOR_STATUS_BACKGROUND}; color: {COLOR_STATUS_TEXT}; border: 1px solid {COLOR_STATUS_BORDER}; border-radius: 8px; padding: 9px 12px; }}
QGroupBox {{ background: {COLOR_SURFACE}; border: 1px solid {COLOR_GROUP_BORDER}; border-radius: 9px; margin-top: 12px; padding: 12px 10px 10px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 12px; padding: 0 5px; color: {COLOR_GROUP_TITLE}; }}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser, QTableWidget {{ background: {COLOR_SURFACE}; border: 1px solid {COLOR_CONTROL_BORDER}; border-radius: 6px; padding: 5px 7px; selection-background-color: {COLOR_SELECTION}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextBrowser:focus, QTableWidget:focus {{ border: 1px solid {COLOR_FOCUS}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled, QPlainTextEdit:disabled, QTextBrowser:disabled, QTableWidget:disabled {{ color: {COLOR_DISABLED_TEXT}; background: {COLOR_DISABLED_BACKGROUND}; }}
QPushButton {{ background: {COLOR_SURFACE}; border: 1px solid {COLOR_CONTROL_BORDER}; border-radius: 7px; padding: 7px 11px; }}
QPushButton:hover {{ background: {COLOR_BUTTON_HOVER}; border-color: {COLOR_BUTTON_HOVER_BORDER}; }}
QPushButton:pressed {{ background: {COLOR_BUTTON_PRESSED}; }}
QPushButton:disabled {{ color: {COLOR_DISABLED_TEXT}; background: {COLOR_DISABLED_BACKGROUND}; }}
QPushButton#primaryAction {{ background: {COLOR_PRIMARY}; border: 1px solid {COLOR_PRIMARY_BORDER}; color: {COLOR_SURFACE}; font-weight: 700; padding: 10px 14px; }}
QPushButton#primaryAction:hover {{ background: {COLOR_PRIMARY_BORDER}; }}
QSplitter::handle {{ background: {COLOR_SPLITTER}; width: 5px; }}
QHeaderView::section {{ background: {COLOR_TABLE_HEADER}; border: 0; border-bottom: 1px solid {COLOR_GROUP_BORDER}; padding: 6px; font-weight: 600; }}
"""
