"""Lazy PySide6 imports shared by GUI components."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any


def load_qt() -> Any:
    """Import the Qt bindings only when the desktop interface is opened."""
    from PySide6.QtCore import QObject, QPointF, Qt, QThread, Signal, Slot  # type: ignore[reportMissingImports]
    from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap  # type: ignore[reportMissingImports]
    from PySide6.QtWidgets import (  # type: ignore[reportMissingImports]
        QApplication,
        QCheckBox,
        QComboBox,
        QDialog,
        QDialogButtonBox,
        QDoubleSpinBox,
        QFileDialog,
        QFormLayout,
        QGridLayout,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QScrollArea,
        QSpinBox,
        QSplitter,
        QTableWidget,
        QTableWidgetItem,
        QTextBrowser,
        QVBoxLayout,
        QWidget,
    )

    return SimpleNamespace(
        QObject=QObject,
        QPointF=QPointF,
        Qt=Qt,
        QThread=QThread,
        Signal=Signal,
        Slot=Slot,
        QColor=QColor,
        QImage=QImage,
        QPainter=QPainter,
        QPen=QPen,
        QPixmap=QPixmap,
        QApplication=QApplication,
        QCheckBox=QCheckBox,
        QComboBox=QComboBox,
        QDialog=QDialog,
        QDialogButtonBox=QDialogButtonBox,
        QDoubleSpinBox=QDoubleSpinBox,
        QFileDialog=QFileDialog,
        QFormLayout=QFormLayout,
        QGridLayout=QGridLayout,
        QGroupBox=QGroupBox,
        QHBoxLayout=QHBoxLayout,
        QLabel=QLabel,
        QLineEdit=QLineEdit,
        QMainWindow=QMainWindow,
        QMessageBox=QMessageBox,
        QPlainTextEdit=QPlainTextEdit,
        QPushButton=QPushButton,
        QScrollArea=QScrollArea,
        QSpinBox=QSpinBox,
        QSplitter=QSplitter,
        QTableWidget=QTableWidget,
        QTableWidgetItem=QTableWidgetItem,
        QTextBrowser=QTextBrowser,
        QVBoxLayout=QVBoxLayout,
        QWidget=QWidget,
    )
