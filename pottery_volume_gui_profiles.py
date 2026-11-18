"""Manual contour editing canvas and dialog."""

from __future__ import annotations

import math
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from pottery_volume_core import apply_profile_overrides

_MAX_CONTROL_POINTS = 240  # Upper bound on manually added control points per canvas.


class ProfileCanvas(QWidget):
    """Show detected inner/outer contours over the source image and drag points."""

    def __init__(
        self,
        image: np.ndarray,
        profiles: Any,
        axis_x: float,
        sample_y: np.ndarray,
        inner: np.ndarray,
        outer: np.ndarray,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(620, 480)
        self.setMouseTracking(True)
        self.axis_x = float(axis_x)
        self.sample_y = sample_y
        self.inner = inner.copy()
        self.outer = outer.copy()
        self.y_px = profiles.y_px
        self.y_min = float(profiles.top_y_px)
        self.y_max = float(profiles.bottom_y_px)
        self.active_point: tuple[int, bool, float] | None = None
        self.on_drag: Any = None
        self.on_add_point: Any = None
        self.add_mode = False
        self.add_inner = True
        max_radius = float(np.max(profiles.r_out_px))
        x0 = max(0, int(math.floor(axis_x - max_radius - 36)))
        x1 = min(image.shape[1], int(math.ceil(axis_x + max_radius + 36)))
        y0 = max(0, int(math.floor(profiles.top_y_px - 18)))
        y1 = min(image.shape[0], int(math.ceil(profiles.bottom_y_px + 18)))
        if x1 <= x0 or y1 <= y0:
            x0, y0, x1, y1 = 0, 0, image.shape[1], image.shape[0]
        self.crop_x, self.crop_y = x0, y0
        crop = image[y0:y1, x0:x1]
        rgb = crop[:, :, ::-1].copy() if crop.ndim == 3 else cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
        height, width = rgb.shape[:2]
        qimage = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
        self.pixmap = QPixmap.fromImage(qimage)
        self._rendered_pixmap: Any = None
        self._rendered_size = (0, 0)
        self.crop_width, self.crop_height = width, height
        self.scale = min(1.0, 850 / width, 640 / height)
        self.offset_x = 8.0
        self.offset_y = 8.0
        self._user_panned = False

    def resizeEvent(self, event: Any) -> None:
        if not self._user_panned:
            self.scale = min(
                1.0,
                max(0.05, (self.width() - 16) / self.crop_width),
                max(0.05, (self.height() - 16) / self.crop_height),
            )
            self.offset_x = (self.width() - self.crop_width * self.scale) / 2
            self.offset_y = (self.height() - self.crop_height * self.scale) / 2
        super().resizeEvent(event)

    def set_profiles(
        self,
        sample_y: np.ndarray,
        inner: np.ndarray,
        outer: np.ndarray,
    ) -> None:
        self.sample_y = sample_y.copy()
        self.inner = inner.copy()
        self.outer = outer.copy()
        self.update()

    def _scaled_image(self) -> Any:
        size = (
            max(1, round(self.crop_width * self.scale)),
            max(1, round(self.crop_height * self.scale)),
        )
        if size != self._rendered_size:
            self._rendered_pixmap = self.pixmap.scaled(
                *size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            self._rendered_size = size
        return self._rendered_pixmap

    def set_add_mode(self, enabled: bool, add_inner: bool) -> None:
        self.add_mode = enabled
        self.add_inner = add_inner
        self.setCursor(Qt.CursorShape.CrossCursor if enabled else Qt.CursorShape.ArrowCursor)

    def _screen(self, radius: float, y: float, side: float = 1.0) -> QPointF:
        return QPointF(
            self.offset_x + (self.axis_x + side * radius - self.crop_x) * self.scale,
            self.offset_y + (y - self.crop_y) * self.scale,
        )

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172033"))
        shown = self._scaled_image()
        painter.drawPixmap(round(self.offset_x), round(self.offset_y), shown)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        axis_x = self.offset_x + (self.axis_x - self.crop_x) * self.scale
        painter.setPen(QPen(QColor("#f8fafc"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(round(axis_x), 0, round(axis_x), self.height())

        for values, color in ((self.inner, QColor("#fb923c")), (self.outer, QColor("#38bdf8"))):
            painter.setPen(QPen(color, 3))
            for side in (-1.0, 1.0):
                points = [
                    self._screen(float(radius), float(y), side)
                    for y, radius in zip(self.sample_y, values)
                ]
                for start, end in zip(points, points[1:]):
                    painter.drawLine(start, end)
                painter.setBrush(QColor("#ffffff"))
                for point in points:
                    painter.setPen(QPen(color, 2))
                    painter.drawEllipse(point, 5, 5)
        painter.end()

    def mousePressEvent(self, event: Any) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        if self.add_mode:
            image_x = (x - self.offset_x) / self.scale + self.crop_x
            image_y = (y - self.offset_y) / self.scale + self.crop_y
            if (
                self.crop_x <= image_x < self.crop_x + self.crop_width
                and self.y_min <= image_y <= self.y_max
                and self.on_add_point
            ):
                self.on_add_point(image_y, abs(image_x - self.axis_x), self.add_inner)
            return
        best: tuple[float, int, bool, float] | None = None
        for index, (row_y, inner, outer) in enumerate(zip(self.sample_y, self.inner, self.outer)):
            for is_inner, radius in ((True, inner), (False, outer)):
                for side in (-1.0, 1.0):
                    point = self._screen(float(radius), float(row_y), side)
                    distance = math.hypot(x - point.x(), y - point.y())
                    if best is None or distance < best[0]:
                        best = (distance, index, is_inner, side)
        if best is not None and best[0] <= 18:
            self.active_point = (best[1], best[2], best[3])
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event: Any) -> None:
        if self.active_point is None:
            return
        x = (event.position().x() - self.offset_x) / self.scale + self.crop_x
        radius = abs(x - self.axis_x)
        index, is_inner, _side = self.active_point
        if is_inner:
            self.inner[index] = min(radius, self.outer[index] - 0.25)
        else:
            self.outer[index] = max(radius, self.inner[index] + 0.25)
        self.update()
        if self.on_drag:
            self.on_drag(self.inner.copy(), self.outer.copy())

    def mouseReleaseEvent(self, _event: Any) -> None:
        self.active_point = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

class ProfileEditorDialog(QDialog):
    def __init__(self, profiles: Any, image: np.ndarray, axis_x: float, parent: Any) -> None:
        super().__init__(parent)
        self.setWindowTitle("断面輪郭を画像上で手動補正")
        self.resize(1180, 720)
        self.corrected_profiles = profiles
        sample_indices = np.unique(
            np.linspace(0, len(profiles.y_px) - 1, min(40, len(profiles.y_px)))
            .round()
            .astype(int)
        )
        self.sample_y = profiles.y_px[sample_indices]
        self.inner_values = profiles.r_in_px[sample_indices].copy()
        self.outer_values = profiles.r_out_px[sample_indices].copy()
        self.point_history: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "既存点をドラッグして調整できます。「点を追加」を押し、画像の左右どちらかを複数回クリックすると、"
            "指定した高さに補正点を追加できます。点の間は補間して再計算します。"
        ))
        point_controls = QHBoxLayout()
        self.surface_combo = QComboBox()
        self.surface_combo.addItem("内面輪郭を追加", True)
        self.surface_combo.addItem("外面輪郭を追加", False)
        self.add_points_button = QPushButton("点を追加")
        self.add_points_button.setCheckable(True)
        self.undo_point_button = QPushButton("直前の追加を取り消す")
        self.undo_point_button.setEnabled(False)
        point_controls.addWidget(QLabel("追加する輪郭:"))
        point_controls.addWidget(self.surface_combo)
        point_controls.addWidget(self.add_points_button)
        point_controls.addWidget(self.undo_point_button)
        point_controls.addWidget(QLabel("クリックした位置から軸までの距離を輪郭半径にします。"), 1)
        layout.addLayout(point_controls)
        body = QHBoxLayout()
        self.canvas = ProfileCanvas(
            image, profiles, axis_x, self.sample_y,
            self.inner_values, self.outer_values,
        )
        self.canvas.on_drag = self._canvas_changed
        self.canvas.on_add_point = self._add_control_point
        body.addWidget(self.canvas, 1)
        self.table = QTableWidget(len(self.sample_y), 3)
        self.table.setMinimumWidth(340)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setHorizontalHeaderLabels(["画像 y", "内面半径", "外面半径"])
        self.table.verticalHeader().setDefaultSectionSize(23)
        self._populate_table()
        self.table.cellChanged.connect(self._table_changed)
        body.addWidget(self.table)
        layout.addLayout(body, 1)
        self.add_points_button.toggled.connect(self._toggle_add_points)
        self.undo_point_button.clicked.connect(self._undo_added_point)
        self.surface_combo.currentIndexChanged.connect(self._surface_changed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("補正して再計算")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _table_values(self) -> tuple[np.ndarray, np.ndarray]:
        inner_values: list[float] = []
        outer_values: list[float] = []
        for row in range(self.table.rowCount()):
            inner_item = self.table.item(row, 1)
            outer_item = self.table.item(row, 2)
            if inner_item is None or outer_item is None:
                raise ValueError("輪郭の入力欄を確認してください。")
            inner_values.append(float(inner_item.text()))
            outer_values.append(float(outer_item.text()))
        inner = np.asarray(inner_values)
        outer = np.asarray(outer_values)
        return inner, outer

    def _populate_table(self) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(self.sample_y))
        for row, (y, inner, outer) in enumerate(zip(self.sample_y, self.inner_values, self.outer_values)):
            values = (y, inner, outer)
            for column, value in enumerate(values):
                item = QTableWidgetItem(f"{value:.2f}")
                if column == 0:
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(row, column, item)
        self.table.blockSignals(False)

    def _toggle_add_points(self, enabled: bool) -> None:
        self.add_points_button.setText("点の追加を終了" if enabled else "点を追加")
        self._surface_changed()

    def _surface_changed(self, *_args: Any) -> None:
        self.canvas.set_add_mode(
            self.add_points_button.isChecked(),
            bool(self.surface_combo.currentData()),
        )

    def _add_control_point(self, y: float, radius: float, is_inner: bool) -> None:
        if len(self.sample_y) >= _MAX_CONTROL_POINTS:
            QMessageBox.information(self, "点数の上限", f"手動補正点は{_MAX_CONTROL_POINTS}点まで追加できます。")
            return
        self.point_history.append(
            (self.sample_y.copy(), self.inner_values.copy(), self.outer_values.copy())
        )
        self.undo_point_button.setEnabled(True)
        nearest = int(np.argmin(np.abs(self.sample_y - y)))
        if abs(float(self.sample_y[nearest]) - y) < 0.75:
            index = nearest
        else:
            index = int(np.searchsorted(self.sample_y, y))
            new_y = np.insert(self.sample_y, index, y)
            self.inner_values = np.insert(
                self.inner_values,
                index,
                np.interp(y, self.sample_y, self.inner_values),
            )
            self.outer_values = np.insert(
                self.outer_values,
                index,
                np.interp(y, self.sample_y, self.outer_values),
            )
            self.sample_y = new_y
        if is_inner:
            self.inner_values[index] = min(radius, self.outer_values[index] - 0.25)
        else:
            self.outer_values[index] = max(radius, self.inner_values[index] + 0.25)
        self._populate_table()
        self.canvas.set_profiles(self.sample_y, self.inner_values, self.outer_values)

    def _undo_added_point(self) -> None:
        if not self.point_history:
            return
        self.sample_y, self.inner_values, self.outer_values = self.point_history.pop()
        self._populate_table()
        self.canvas.set_profiles(self.sample_y, self.inner_values, self.outer_values)
        self.undo_point_button.setEnabled(bool(self.point_history))

    def _table_changed(self, _row: int, _column: int) -> None:
        try:
            inner, outer = self._table_values()
        except (ValueError, AttributeError):
            return
        if not np.all(np.isfinite(inner)) or not np.all(np.isfinite(outer)):
            return
        if np.any(inner < 0) or np.any(outer <= inner):
            return
        self.inner_values, self.outer_values = inner, outer
        self.canvas.set_profiles(self.sample_y, inner, outer)

    def _canvas_changed(self, inner: np.ndarray, outer: np.ndarray) -> None:
        self.table.blockSignals(True)
        for row, (inner_value, outer_value) in enumerate(zip(inner, outer)):
            inner_item = self.table.item(row, 1)
            outer_item = self.table.item(row, 2)
            if inner_item is not None:
                inner_item.setText(f"{inner_value:.2f}")
            if outer_item is not None:
                outer_item.setText(f"{outer_value:.2f}")
        self.table.blockSignals(False)
        self.inner_values, self.outer_values = inner, outer

    def accept(self) -> None:
        try:
            inner, outer = self._table_values()
            if not np.all(np.isfinite(inner)) or not np.all(np.isfinite(outer)):
                raise ValueError("半径は有限の数値で入力してください。")
            if np.any(inner < 0) or np.any(outer <= inner):
                raise ValueError("外面半径は内面半径より大きくしてください。")
            y_px = self.corrected_profiles.y_px
            corrected_inner = np.interp(y_px, self.sample_y, inner)
            corrected_outer = np.interp(y_px, self.sample_y, outer)
            self.corrected_profiles = apply_profile_overrides(
                self.corrected_profiles,
                corrected_inner,
                corrected_outer,
                ["断面プロファイルを手動補正しました。"],
            )
        except (ValueError, TypeError) as exc:
            QMessageBox.warning(self, "入力を確認してください", str(exc))
            return
        super().accept()
