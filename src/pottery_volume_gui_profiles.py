"""Manual contour editing canvas and dialog."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import (
    QColor,
    QImage,
    QKeySequence,
    QPainter,
    QPen,
    QPixmap,
    QShortcut,
)
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

from pottery_volume_core import Profiles, apply_profile_overrides

_MAX_CONTROL_POINTS = 240  # Upper bound on manually added control points per canvas.
_MIN_SCALE = 0.05  # Smallest zoom factor of the canvas.
_MAX_SCALE = 16.0  # Largest zoom factor of the canvas.
_ZOOM_STEP = 1.15  # Zoom factor per wheel notch (120 angle-delta units).
_MAX_UNDO = 200  # Maximum number of undo steps kept in the dialog.


def _crop_to_pixmap(image: np.ndarray, bounds: tuple[int, int, int, int]) -> QPixmap:
    """Crop ``image`` to ``bounds`` (x0, y0, x1, y1) and convert it to a QPixmap."""
    x0, y0, x1, y1 = bounds
    crop = image[y0:y1, x0:x1]
    if crop.dtype != np.uint8:
        crop = np.clip(crop, 0, 255).astype(np.uint8)
    if crop.ndim == 3:
        rgb = crop[:, :, :3][:, :, ::-1].copy()
    else:
        rgb = cv2.cvtColor(crop, cv2.COLOR_GRAY2RGB)
    height, width = rgb.shape[:2]
    qimage = QImage(
        rgb.data, width, height, width * 3, QImage.Format.Format_RGB888
    ).copy()
    return QPixmap.fromImage(qimage)


def _denoised_image(
    image: np.ndarray, min_component_area: int, adaptive: bool
) -> np.ndarray:
    """二値化して小さな連結成分を除去した画像（白背景・黒線）を返す。

    README の自動検出手順（Otsu 二値化 → 前景量が極端なら適応的二値化 →
    小さい連結成分の除去）に沿った表示用の近似処理。計算結果には影響しない。
    """
    gray = image
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray[:, :, :3], cv2.COLOR_BGR2GRAY)
    _, mask = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    ratio = float(np.count_nonzero(mask)) / float(mask.size)
    if adaptive or ratio < 0.002 or ratio > 0.5:
        mask = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 31, 10
        )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    keep = np.zeros(count, dtype=bool)
    keep[1:] = stats[1:, cv2.CC_STAT_AREA] >= max(1, int(min_component_area))
    label_array: Any = np.asarray(labels)
    cleaned = keep[label_array]
    return np.where(cleaned, 0, 255).astype(np.uint8)


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
        min_component_area: int = 5,
        adaptive_threshold: bool = False,
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
        self._dragging_axis = False
        self.on_drag: Any = None
        self.on_drag_end: Any = None
        self.on_axis_drag: Any = None
        self.on_axis_drag_end: Any = None
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
        self._crop_bounds = (x0, y0, x1, y1)
        self._image = image
        self._min_component_area = int(min_component_area)
        self._adaptive_threshold = bool(adaptive_threshold)
        self.pixmap = _crop_to_pixmap(image, self._crop_bounds)
        self._denoised_pixmap: QPixmap | None = None  # 初回表示時に作成
        self.show_denoised = False
        self.crop_width, self.crop_height = self.pixmap.width(), self.pixmap.height()
        self.scale = min(1.0, 850 / self.crop_width, 640 / self.crop_height)
        self.offset_x = 8.0
        self.offset_y = 8.0
        self._user_panned = False
        self._pan_last: QPointF | None = None

    def set_show_denoised(self, enabled: bool) -> None:
        """True でノイズ除去後の画像、False で元の画像を表示する。"""
        self.show_denoised = bool(enabled)
        if self.show_denoised and self._denoised_pixmap is None:
            cleaned = _denoised_image(
                self._image, self._min_component_area, self._adaptive_threshold
            )
            self._denoised_pixmap = _crop_to_pixmap(cleaned, self._crop_bounds)
        self.update()

    def resizeEvent(self, event: Any) -> None:
        if not self._user_panned:
            self.scale = min(
                1.0,
                max(_MIN_SCALE, (self.width() - 16) / self.crop_width),
                max(_MIN_SCALE, (self.height() - 16) / self.crop_height),
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

    def set_axis_x(self, axis_x: float) -> None:
        self.axis_x = float(axis_x)
        self.update()

    def set_add_mode(self, enabled: bool, add_inner: bool) -> None:
        self.add_mode = enabled
        self.add_inner = add_inner
        self._restore_cursor()

    def _restore_cursor(self) -> None:
        self.setCursor(
            Qt.CursorShape.CrossCursor if self.add_mode else Qt.CursorShape.ArrowCursor
        )

    def wheelEvent(self, event: Any) -> None:
        """Ctrl+マウスホイールでカーソル位置を中心に拡大・縮小する。"""
        if not (event.modifiers() & Qt.KeyboardModifier.ControlModifier):
            event.ignore()
            return
        delta = event.angleDelta().y()
        if delta == 0:
            event.ignore()
            return
        new_scale = self.scale * (_ZOOM_STEP ** (delta / 120.0))
        new_scale = max(_MIN_SCALE, min(_MAX_SCALE, new_scale))
        if new_scale == self.scale:
            event.accept()
            return
        # カーソル直下の画像座標が動かないようにオフセットを調整する
        pos = event.position()
        image_x = (pos.x() - self.offset_x) / self.scale
        image_y = (pos.y() - self.offset_y) / self.scale
        self.scale = new_scale
        self.offset_x = pos.x() - image_x * new_scale
        self.offset_y = pos.y() - image_y * new_scale
        self._user_panned = True  # リサイズ時の自動フィットで倍率が戻らないようにする
        self.update()
        event.accept()

    def _screen(self, radius: float, y: float, side: float = 1.0) -> QPointF:
        return QPointF(
            self.offset_x + (self.axis_x + side * radius - self.crop_x) * self.scale,
            self.offset_y + (y - self.crop_y) * self.scale,
        )

    def paintEvent(self, _event: Any) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#172033"))

        # 画像は変換行列で描画する（高倍率でも巨大な拡大Pixmapを作らない）
        shown = (
            self._denoised_pixmap
            if self.show_denoised and self._denoised_pixmap
            else self.pixmap
        )
        painter.save()
        painter.setRenderHint(
            QPainter.RenderHint.SmoothPixmapTransform, self.scale < 2.0
        )
        painter.translate(self.offset_x, self.offset_y)
        painter.scale(self.scale, self.scale)
        painter.drawPixmap(0, 0, shown)
        painter.restore()

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        axis_x = self.offset_x + (self.axis_x - self.crop_x) * self.scale
        painter.setPen(QPen(QColor("#f8fafc"), 1, Qt.PenStyle.DashLine))
        painter.drawLine(round(axis_x), 0, round(axis_x), self.height())

        for values, color in (
            (self.inner, QColor("#fb923c")),
            (self.outer, QColor("#38bdf8")),
        ):
            painter.setPen(QPen(color, 3))
            for side in (-1.0, 1.0):
                points = [
                    self._screen(float(radius), float(y), side)
                    for y, radius in zip(self.sample_y, values, strict=False)
                ]
                for start, end in zip(points, points[1:], strict=False):
                    painter.drawLine(start, end)
                painter.setBrush(QColor("#ffffff"))
                for point in points:
                    painter.setPen(QPen(color, 2))
                    painter.drawEllipse(point, 5, 5)
        painter.end()

    def mousePressEvent(self, event: Any) -> None:
        # ホイール（中ボタン）を押しながらドラッグで画像を移動
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = event.position()
            self._user_panned = True
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        x, y = event.position().x(), event.position().y()
        if not self.add_mode:
            best: tuple[float, int, bool, float] | None = None
            for index, (row_y, inner, outer) in enumerate(
                zip(self.sample_y, self.inner, self.outer, strict=False)
            ):
                for is_inner, radius in ((True, inner), (False, outer)):
                    for side in (-1.0, 1.0):
                        point = self._screen(float(radius), float(row_y), side)
                        distance = math.hypot(x - point.x(), y - point.y())
                        if best is None or distance < best[0]:
                            best = (distance, index, is_inner, side)
            if best is not None and best[0] <= 18:
                self.active_point = (best[1], best[2], best[3])
                self.setCursor(Qt.CursorShape.ClosedHandCursor)
                event.accept()
                return
        axis_screen_x = self.offset_x + (self.axis_x - self.crop_x) * self.scale
        if abs(x - axis_screen_x) <= 10:
            self._dragging_axis = True
            self.setCursor(Qt.CursorShape.SizeHorCursor)
            event.accept()
            return
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

    def mouseMoveEvent(self, event: Any) -> None:
        if self._dragging_axis:
            image_x = (event.position().x() - self.offset_x) / self.scale + self.crop_x
            new_axis_x = min(
                self.crop_x + self.crop_width - 1,
                max(self.crop_x, image_x),
            )
            if new_axis_x != self.axis_x:
                self.axis_x = new_axis_x
                self.update()
                if self.on_axis_drag:
                    self.on_axis_drag(new_axis_x)
            return
        if self._pan_last is not None:
            pos = event.position()
            self.offset_x += pos.x() - self._pan_last.x()
            self.offset_y += pos.y() - self._pan_last.y()
            self._pan_last = pos
            self.update()
            return
        if self.active_point is None:
            axis_screen_x = self.offset_x + (self.axis_x - self.crop_x) * self.scale
            if abs(event.position().x() - axis_screen_x) <= 10:
                self.setCursor(Qt.CursorShape.SizeHorCursor)
            else:
                self._restore_cursor()
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

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_last = None
            self._restore_cursor()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._dragging_axis:
            self._dragging_axis = False
            self._restore_cursor()
            if self.on_axis_drag_end:
                self.on_axis_drag_end()
            return
        was_dragging = self.active_point is not None
        self.active_point = None
        self._restore_cursor()
        if was_dragging and self.on_drag_end:
            self.on_drag_end()  # ドラッグ1回分を元に戻す操作1回として記録する


class ProfileEditorDialog(QDialog):
    def __init__(
        self,
        profiles: Any,
        image: np.ndarray,
        axis_x: float,
        parent: Any,
        min_component_area: int = 5,
        adaptive_threshold: bool = False,
        original_image: np.ndarray | None = None,
        auto_profile_generator: Callable[[float], Profiles] | None = None,
    ) -> None:
        """
        ``min_component_area`` と ``adaptive_threshold`` は「ノイズ除去後の画像を表示」
        ボタンで使う（省略時は既定値 5 / 通常の二値化）。
        """
        super().__init__(parent)
        self.setWindowTitle("断面輪郭を画像上で手動補正")
        self.resize(1180, 720)
        self.corrected_profiles = profiles
        self.baseline_y = profiles.y_px.copy()
        self.baseline_inner = profiles.r_in_px.copy()
        self.baseline_outer = profiles.r_out_px.copy()
        sample_indices = np.unique(
            np.linspace(0, len(profiles.y_px) - 1, min(40, len(profiles.y_px)))
            .round()
            .astype(int)
        )
        self.sample_y = profiles.y_px[sample_indices]
        self.inner_values = profiles.r_in_px[sample_indices].copy()
        self.outer_values = profiles.r_out_px[sample_indices].copy()
        self.original_inner_values = self.inner_values.copy()
        self.original_outer_values = self.outer_values.copy()
        self.edited_inner_indices: set[int] = set()
        self.edited_outer_indices: set[int] = set()
        self.axis_x = float(axis_x)
        self.auto_profile_generator = auto_profile_generator
        # 元に戻す（Ctrl+Z）用の履歴。_last_state は「現在確定している状態」。
        self._undo_stack: list[tuple[Any, ...]] = []
        self._last_state: tuple[Any, ...] = self._snapshot()
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "既存点をドラッグして調整できます。「点を追加」を押し、画像の左右どちらかを複数回クリックすると、"
                "指定した高さに補正点を追加できます。点の間は補間して再計算します。"
                "白い破線の回転軸もドラッグして移動できます。"
                "Ctrl+マウスホイールで拡大・縮小、ホイールを押しながらドラッグで画像を移動、"
                "Ctrl+Z で直前の操作を元に戻せます。"
            )
        )
        point_controls = QHBoxLayout()
        self.surface_combo = QComboBox()
        self.surface_combo.addItem("内面輪郭を追加", True)
        self.surface_combo.addItem("外面輪郭を追加", False)
        self.add_points_button = QPushButton("点を追加")
        self.add_points_button.setCheckable(True)
        self.undo_button = QPushButton("元に戻す (Ctrl+Z)")
        self.undo_button.setEnabled(False)
        self.denoise_button = QPushButton("ノイズ除去後の画像を表示")
        self.denoise_button.setCheckable(True)
        self.denoise_button.setToolTip(
            "二値化して小さなノイズを除去した画像を表示します（表示のみで、計算結果には影響しません）。"
        )
        self.auto_profile_button = QPushButton("自動輪郭を生成")
        self.auto_profile_button.setEnabled(auto_profile_generator is not None)
        self.auto_profile_button.setToolTip(
            "現在の回転軸で解析時の断面から輪郭を再抽出し、手動補正を置き換えます。"
        )
        point_controls.addWidget(QLabel("追加する輪郭:"))
        point_controls.addWidget(self.surface_combo)
        point_controls.addWidget(self.add_points_button)
        point_controls.addWidget(self.undo_button)
        point_controls.addWidget(self.denoise_button)
        point_controls.addWidget(self.auto_profile_button)
        point_controls.addWidget(
            QLabel("クリックした位置から軸までの距離を輪郭半径にします。"), 1
        )
        layout.addLayout(point_controls)
        body = QHBoxLayout()
        self.canvas = ProfileCanvas(
            original_image if original_image is not None else image,
            profiles,
            axis_x,
            self.sample_y,
            self.inner_values,
            self.outer_values,
            min_component_area=min_component_area,
            adaptive_threshold=adaptive_threshold,
        )
        self.canvas.on_drag = self._canvas_changed
        self.canvas.on_drag_end = self._commit
        self.canvas.on_axis_drag = self._axis_changed
        self.canvas.on_axis_drag_end = self._commit
        self.canvas.on_add_point = self._add_control_point
        body.addWidget(self.canvas, 1)
        self.table = QTableWidget(len(self.sample_y), 3)
        self.table.setMinimumWidth(340)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self.table.setHorizontalHeaderLabels(["画像 y", "内面半径", "外面半径"])
        self.table.verticalHeader().setDefaultSectionSize(23)
        self._populate_table()
        self.table.cellChanged.connect(self._table_changed)
        body.addWidget(self.table)
        layout.addLayout(body, 1)
        self.add_points_button.toggled.connect(self._toggle_add_points)
        self.undo_button.clicked.connect(self._undo)
        self.denoise_button.toggled.connect(self._toggle_denoised)
        self.auto_profile_button.clicked.connect(self._generate_automatic_profiles)
        self.surface_combo.currentIndexChanged.connect(self._surface_changed)
        # セル編集中は QLineEdit 側の Ctrl+Z（文字入力の取り消し）が優先される
        self._undo_shortcut = QShortcut(QKeySequence.StandardKey.Undo, self)
        self._undo_shortcut.activated.connect(self._undo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("補正して再計算")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("キャンセル")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ---- 元に戻す（Ctrl+Z） ----

    def _snapshot(self) -> tuple[Any, ...]:
        return (
            self.sample_y.copy(),
            self.inner_values.copy(),
            self.outer_values.copy(),
            self.original_inner_values.copy(),
            self.original_outer_values.copy(),
            set(self.edited_inner_indices),
            set(self.edited_outer_indices),
            self.axis_x,
            self.baseline_y.copy(),
            self.baseline_inner.copy(),
            self.baseline_outer.copy(),
            self.corrected_profiles,
        )

    @staticmethod
    def _same_state(a: tuple[Any, ...], b: tuple[Any, ...]) -> bool:
        return (
            all(np.array_equal(x, y) for x, y in zip(a[:5], b[:5], strict=True))
            and a[5] == b[5]
            and a[6] == b[6]
            and a[7] == b[7]
            and all(np.array_equal(x, y) for x, y in zip(a[8:11], b[8:11], strict=True))
            and a[11] is b[11]
        )

    def _commit(self) -> None:
        """現在の状態を確定し、変更前の状態を元に戻す履歴へ積む。"""
        current = self._snapshot()
        if self._same_state(current, self._last_state):
            return
        self._undo_stack.append(self._last_state)
        if len(self._undo_stack) > _MAX_UNDO:
            del self._undo_stack[0]
        self._last_state = current
        self.undo_button.setEnabled(True)

    def _undo(self) -> None:
        if (
            not self._undo_stack
            or self.canvas.active_point is not None
            or self.canvas._dragging_axis
        ):
            return
        (
            sample_y,
            inner_values,
            outer_values,
            original_inner_values,
            original_outer_values,
            edited_inner_indices,
            edited_outer_indices,
            axis_x,
            baseline_y,
            baseline_inner,
            baseline_outer,
            corrected_profiles,
        ) = self._undo_stack.pop()
        self.sample_y = sample_y.copy()
        self.inner_values = inner_values.copy()
        self.outer_values = outer_values.copy()
        self.original_inner_values = original_inner_values.copy()
        self.original_outer_values = original_outer_values.copy()
        self.edited_inner_indices = set(edited_inner_indices)
        self.edited_outer_indices = set(edited_outer_indices)
        self.axis_x = axis_x
        self.baseline_y = baseline_y.copy()
        self.baseline_inner = baseline_inner.copy()
        self.baseline_outer = baseline_outer.copy()
        self.corrected_profiles = corrected_profiles
        self._populate_table()
        self.canvas.set_profiles(self.sample_y, self.inner_values, self.outer_values)
        self.canvas.set_axis_x(self.axis_x)
        self.canvas.y_min = float(self.baseline_y[0])
        self.canvas.y_max = float(self.baseline_y[-1])
        self._last_state = self._snapshot()
        self.undo_button.setEnabled(bool(self._undo_stack))

    # ---- 画像表示 ----

    def _toggle_denoised(self, enabled: bool) -> None:
        self.denoise_button.setText(
            "ノイズ除去前の画像に戻す" if enabled else "ノイズ除去後の画像を表示"
        )
        self.canvas.set_show_denoised(enabled)

    def _generate_automatic_profiles(self) -> None:
        if self.auto_profile_generator is None:
            return
        try:
            profiles = self.auto_profile_generator(self.axis_x)
        except ValueError as exc:
            QMessageBox.warning(self, "自動輪郭を生成できません", str(exc))
            return

        self.corrected_profiles = profiles
        self.baseline_y = profiles.y_px.copy()
        self.baseline_inner = profiles.r_in_px.copy()
        self.baseline_outer = profiles.r_out_px.copy()
        sample_indices = np.unique(
            np.linspace(0, len(profiles.y_px) - 1, min(40, len(profiles.y_px)))
            .round()
            .astype(int)
        )
        self.sample_y = profiles.y_px[sample_indices]
        self.inner_values = profiles.r_in_px[sample_indices].copy()
        self.outer_values = profiles.r_out_px[sample_indices].copy()
        self.original_inner_values = self.inner_values.copy()
        self.original_outer_values = self.outer_values.copy()
        self.edited_inner_indices.clear()
        self.edited_outer_indices.clear()
        self.canvas.y_min = float(profiles.top_y_px)
        self.canvas.y_max = float(profiles.bottom_y_px)
        self.canvas.set_profiles(self.sample_y, self.inner_values, self.outer_values)
        self._populate_table()
        self._commit()

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
        for row, (y, inner, outer) in enumerate(
            zip(self.sample_y, self.inner_values, self.outer_values, strict=False)
        ):
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
            QMessageBox.information(
                self,
                "点数の上限",
                f"手動補正点は{_MAX_CONTROL_POINTS}点まで追加できます。",
            )
            return
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
            baseline_inner_at_y = float(
                np.interp(y, self.baseline_y, self.baseline_inner)
            )
            baseline_outer_at_y = float(
                np.interp(y, self.baseline_y, self.baseline_outer)
            )
            self.original_inner_values = np.insert(
                self.original_inner_values, index, baseline_inner_at_y
            )
            self.original_outer_values = np.insert(
                self.original_outer_values, index, baseline_outer_at_y
            )
            self.sample_y = new_y
            # 挿入で後ろへずれた「編集済み」インデックスを補正する
            self.edited_inner_indices = {
                i + 1 if i >= index else i for i in self.edited_inner_indices
            }
            self.edited_outer_indices = {
                i + 1 if i >= index else i for i in self.edited_outer_indices
            }
        if is_inner:
            self.inner_values[index] = min(radius, self.outer_values[index] - 0.25)
            self.edited_inner_indices.add(index)
        else:
            self.outer_values[index] = max(radius, self.inner_values[index] + 0.25)
            self.edited_outer_indices.add(index)
        self._populate_table()
        self.canvas.set_profiles(self.sample_y, self.inner_values, self.outer_values)
        self._commit()

    def _table_changed(self, _row: int, _column: int) -> None:
        try:
            inner, outer = self._table_values()
        except (ValueError, AttributeError):
            return
        if not np.all(np.isfinite(inner)) or not np.all(np.isfinite(outer)):
            return
        if np.any(inner < 0) or np.any(outer <= inner):
            return
        if _column == 1:
            self.edited_inner_indices.update(
                index
                for index, (before, after) in enumerate(
                    zip(self.original_inner_values, inner, strict=False)
                )
                if before != after
            )
        if _column == 2:
            self.edited_outer_indices.update(
                index
                for index, (before, after) in enumerate(
                    zip(self.original_outer_values, outer, strict=False)
                )
                if before != after
            )
        self.inner_values, self.outer_values = inner, outer
        self.canvas.set_profiles(self.sample_y, inner, outer)
        self._commit()

    def _canvas_changed(self, inner: np.ndarray, outer: np.ndarray) -> None:
        self.edited_inner_indices.update(
            index
            for index, (before, after) in enumerate(
                zip(self.original_inner_values, inner, strict=False)
            )
            if before != after
        )
        self.edited_outer_indices.update(
            index
            for index, (before, after) in enumerate(
                zip(self.original_outer_values, outer, strict=False)
            )
            if before != after
        )
        self.table.blockSignals(True)
        for row, (inner_value, outer_value) in enumerate(
            zip(inner, outer, strict=False)
        ):
            inner_item = self.table.item(row, 1)
            outer_item = self.table.item(row, 2)
            if inner_item is not None:
                inner_item.setText(f"{inner_value:.2f}")
            if outer_item is not None:
                outer_item.setText(f"{outer_value:.2f}")
        self.table.blockSignals(False)
        self.inner_values, self.outer_values = inner, outer

    def _axis_changed(self, axis_x: float) -> None:
        self.axis_x = axis_x

    def accept(self) -> None:
        try:
            inner, outer = self._table_values()
            if not np.all(np.isfinite(inner)) or not np.all(np.isfinite(outer)):
                raise ValueError("半径は有限の数値で入力してください。")
            if np.any(inner < 0) or np.any(outer <= inner):
                raise ValueError("外面半径は内面半径より大きくしてください。")
            y_px = self.baseline_y

            def apply_deltas(
                baseline: np.ndarray,
                edited_indices: set[int],
                control_values: np.ndarray,
                original_control_values: np.ndarray,
            ) -> np.ndarray:
                if not edited_indices:
                    return baseline.copy()
                edit_indices = sorted(edited_indices)
                edit_y = self.sample_y[edit_indices]
                edit_delta = (
                    control_values[edit_indices] - original_control_values[edit_indices]
                )
                delta = np.interp(
                    y_px,
                    edit_y,
                    edit_delta,
                    left=edit_delta[0],
                    right=edit_delta[-1],
                )
                corrected = baseline + delta
                return np.where(corrected < 0, 0.0, corrected)

            corrected_inner = apply_deltas(
                self.baseline_inner,
                self.edited_inner_indices,
                inner,
                self.original_inner_values,
            )
            corrected_outer = apply_deltas(
                self.baseline_outer,
                self.edited_outer_indices,
                outer,
                self.original_outer_values,
            )
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
