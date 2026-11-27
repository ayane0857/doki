"""Image canvas for interactive contour editing."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QWidget

from doki.analysis.image import binarize_image, remove_small_components

_MIN_SCALE = 0.05  # Smallest zoom factor of the canvas.
_MAX_SCALE = 16.0  # Largest zoom factor of the canvas.
_ZOOM_STEP = 1.15  # Zoom factor per wheel notch (120 angle-delta units).


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
    qimage = QImage(rgb.data, width, height, width * 3, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(qimage)


def _denoised_image(image: np.ndarray, min_component_area: int, adaptive: bool) -> np.ndarray:
    """解析と同じ二値化・ノイズ除去を行い、表示用の白背景・黒線画像を返す。"""
    gray = image
    if gray.dtype != np.uint8:
        gray = np.clip(gray, 0, 255).astype(np.uint8)
    if gray.ndim == 3:
        gray = cv2.cvtColor(gray[:, :, :3], cv2.COLOR_BGR2GRAY)
    mask, _ = binarize_image(gray, adaptive)
    return cv2.bitwise_not(remove_small_components(mask, max(1, min_component_area)))


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
        self.on_axis_drag: Callable[[float], None] | None = None
        self.on_axis_drag_end: Callable[[], None] | None = None
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
        self.setCursor(Qt.CursorShape.CrossCursor if self.add_mode else Qt.CursorShape.ArrowCursor)

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
            self._denoised_pixmap if self.show_denoised and self._denoised_pixmap else self.pixmap
        )
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.scale < 2.0)
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
            if not self.add_mode and abs(event.position().x() - axis_screen_x) <= 10:
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
