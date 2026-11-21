"""Lazy Qt exports retained for compatibility with older GUI imports."""

from __future__ import annotations

import sys
from importlib import import_module
from types import ModuleType
from typing import Any

_QT_EXPORTS = {
    "QObject": "PySide6.QtCore",
    "QPointF": "PySide6.QtCore",
    "Qt": "PySide6.QtCore",
    "QThread": "PySide6.QtCore",
    "Signal": "PySide6.QtCore",
    "Slot": "PySide6.QtCore",
    "QColor": "PySide6.QtGui",
    "QImage": "PySide6.QtGui",
    "QPainter": "PySide6.QtGui",
    "QPen": "PySide6.QtGui",
    "QPixmap": "PySide6.QtGui",
    "QApplication": "PySide6.QtWidgets",
    "QCheckBox": "PySide6.QtWidgets",
    "QComboBox": "PySide6.QtWidgets",
    "QDialog": "PySide6.QtWidgets",
    "QDialogButtonBox": "PySide6.QtWidgets",
    "QDoubleSpinBox": "PySide6.QtWidgets",
    "QFileDialog": "PySide6.QtWidgets",
    "QFormLayout": "PySide6.QtWidgets",
    "QGridLayout": "PySide6.QtWidgets",
    "QGroupBox": "PySide6.QtWidgets",
    "QHeaderView": "PySide6.QtWidgets",
    "QHBoxLayout": "PySide6.QtWidgets",
    "QLabel": "PySide6.QtWidgets",
    "QLineEdit": "PySide6.QtWidgets",
    "QMainWindow": "PySide6.QtWidgets",
    "QMessageBox": "PySide6.QtWidgets",
    "QPlainTextEdit": "PySide6.QtWidgets",
    "QPushButton": "PySide6.QtWidgets",
    "QScrollArea": "PySide6.QtWidgets",
    "QSpinBox": "PySide6.QtWidgets",
    "QSplitter": "PySide6.QtWidgets",
    "QTableWidget": "PySide6.QtWidgets",
    "QTableWidgetItem": "PySide6.QtWidgets",
    "QTextBrowser": "PySide6.QtWidgets",
    "QVBoxLayout": "PySide6.QtWidgets",
    "QWidget": "PySide6.QtWidgets",
}

__all__ = list(_QT_EXPORTS) + ["load_qt"]


def __getattr__(name: str) -> Any:
    module_name = _QT_EXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module_name), name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_QT_EXPORTS))


def load_qt() -> ModuleType:
    """Return this module; Qt symbols load only when an export is accessed."""
    return sys.modules[__name__]
