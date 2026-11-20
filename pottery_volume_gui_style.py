"""Qt stylesheets for the pottery volume desktop interface."""

from typing import Any

from PySide6.QtCore import Qt

FONT_UI = "'Yu Gothic UI', 'Meiryo UI', 'Noto Sans CJK JP', 'Noto Sans JP', 'Hiragino Kaku Gothic ProN', sans-serif"
FONT_MONO = "'Cascadia Mono', Consolas, Menlo, 'DejaVu Sans Mono', monospace"

def build_stylesheet(colors: dict[str, str]) -> str:
    return f"""
QWidget {{ color: {colors["text"]}; font-family: {FONT_UI}; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {colors["bg"]}; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; }}

QLabel#status {{ color: {colors["muted"]}; background: {colors["surface"]}; border: 1px solid {colors["border"]}; border-radius: 6px; padding: 6px 10px; }}
QLabel#caption {{ color: {colors["muted"]}; }}
QLabel#bigValue {{ font-size: 20pt; font-weight: 600; font-family: {FONT_MONO}; }}
QLabel#details {{ padding-top: 8px; }}

QGroupBox {{ background: {colors["surface"]}; border: 1px solid {colors["border"]}; border-radius: 6px; margin-top: 10px; padding: 12px 10px 8px; font-weight: 600; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 10px; padding: 0 4px; color: {colors["muted"]}; }}

QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTextBrowser {{ background: {colors["surface"]}; border: 1px solid {colors["border"]}; border-radius: 5px; padding: 3px 6px; selection-background-color: {colors["selection"]}; selection-color: {colors["text"]}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextBrowser:focus {{ border: 1px solid {colors["accent"]}; }}
QLineEdit:disabled, QComboBox:disabled, QSpinBox:disabled, QDoubleSpinBox:disabled {{ color: {colors["disabled"]}; background: {colors["bg"]}; }}
QPlainTextEdit, QTextBrowser {{ font-family: {FONT_MONO}; }}

QPushButton {{ background: {colors["bg"]}; border: 1px solid {colors["border"]}; border-radius: 5px; padding: 5px 12px; }}
QPushButton:hover {{ background: {colors["hover"]}; }}
QPushButton:pressed {{ background: {colors["pressed"]}; }}
QPushButton:disabled {{ color: {colors["disabled"]}; background: {colors["bg"]}; }}
QPushButton#primaryAction {{ background: {colors["accent"]}; border: 1px solid {colors["accent_dark"]}; color: #ffffff; font-weight: 600; padding: 7px 14px; }}
QPushButton#primaryAction:hover {{ background: {colors["accent_dark"]}; }}
QPushButton#primaryAction:disabled {{ background: {colors["accent_disabled"]}; border-color: {colors["accent_disabled"]}; }}

QSplitter::handle {{ background: {colors["border"]}; }}
QSplitter::handle:horizontal {{ width: 1px; margin: 0 6px; }}

QTableWidget {{ background: {colors["surface"]}; border: 1px solid {colors["border"]}; gridline-color: {colors["border"]}; selection-background-color: {colors["selection"]}; selection-color: {colors["text"]}; }}
QHeaderView::section {{ background: {colors["bg"]}; border: 0; border-right: 1px solid {colors["border"]}; border-bottom: 1px solid {colors["border"]}; padding: 4px 8px; font-weight: 600; }}
QTableCornerButton::section {{ background: {colors["bg"]}; border: 0; border-right: 1px solid {colors["border"]}; border-bottom: 1px solid {colors["border"]}; }}

QMenu {{ background: {colors["surface"]}; border: 1px solid {colors["border"]}; padding: 4px; }}
QMenu::item {{ padding: 5px 20px; border-radius: 4px; }}
QMenu::item:selected {{ background: {colors["selection"]}; color: {colors["text"]}; }}
QMenu::item:disabled {{ color: {colors["disabled"]}; }}
QMenu::separator {{ height: 1px; background: {colors["border"]}; margin: 4px 6px; }}
QToolTip {{ background: {colors["surface"]}; color: {colors["text"]}; border: 1px solid {colors["border"]}; padding: 3px; }}
"""


LIGHT_COLORS = {
    "bg": "#f6f8fa",
    "surface": "#ffffff",
    "border": "#d0d7de",
    "text": "#1f2328",
    "muted": "#656d76",
    "accent": "#0969da",
    "accent_dark": "#0550ae",
    "hover": "#eaeef2",
    "pressed": "#d8dee4",
    "selection": "#ddf4ff",
    "disabled": "#8c959f",
    "accent_disabled": "#94c1f0",
}

DARK_COLORS = {
    "bg": "#1e1f22",
    "surface": "#2b2d31",
    "border": "#4b4f58",
    "text": "#f2f3f5",
    "muted": "#b5bac1",
    "accent": "#4c9aff",
    "accent_dark": "#2f7dd1",
    "hover": "#383b42",
    "pressed": "#454952",
    "selection": "#254f78",
    "disabled": "#7d828b",
    "accent_disabled": "#315d8c",
}

LIGHT_STYLESHEET = build_stylesheet(LIGHT_COLORS)
DARK_STYLESHEET = build_stylesheet(DARK_COLORS)
APP_STYLESHEET = LIGHT_STYLESHEET


def stylesheet_for_theme(theme: str, app: Any) -> str:
    """Return the stylesheet for a saved theme mode."""
    if theme == "dark":
        return DARK_STYLESHEET
    if theme == "system" and app.styleHints().colorScheme() == Qt.ColorScheme.Dark:
        return DARK_STYLESHEET
    return LIGHT_STYLESHEET
