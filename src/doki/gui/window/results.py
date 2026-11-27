"""Main window result presentation and manual profile correction."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QMessageBox,
)

from doki.analysis.core import compute_volumes, visualize
from doki.gui.profile_editor import ProfileEditorDialog

if TYPE_CHECKING:
    from doki.gui.window.main import MainWindow


def _refresh_result(self: MainWindow) -> None:
    output = self.current_analysis
    if output is None:
        return
    result = output.result
    path = Path(str(result["input"]))
    if output.params.json_out:
        try:
            output.params.json_out.parent.mkdir(parents=True, exist_ok=True)
            temp_path: Path | None = None
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=output.params.json_out.parent,
                prefix=f".{output.params.json_out.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_path = Path(temp_file.name)
                json.dump(result, temp_file, ensure_ascii=False, indent=2)
                temp_file.flush()
            temp_path.replace(output.params.json_out)
        except (OSError, UnicodeError) as exc:
            if "temp_path" in locals() and temp_path is not None:
                try:
                    temp_path.unlink(missing_ok=True)
                except OSError:
                    pass
            QMessageBox.warning(self, "JSON save failed", str(exc))
    self.last_info = {
        "title": path.stem,
        "image_name": path.name,
        "image_path": str(path),
        "result": result,
    }
    length = str(result["units"]["length"])
    if "capacity_ml" in result:
        capacity = result["capacity_ml"]
        wall = cast(float, result.get("wall_volume_ml"))
        pappus = cast(float, result.get("pappus_wall_volume_ml"))
        unit = "mL"
    else:
        capacity = result["capacity"]
        wall = result["wall_volume"]
        pappus = result["pappus_wall_volume"]
        unit = str(result["units"]["volume"])
    scale = result.get("mm_per_px")
    scale_text = (
        f"{scale:.4f} mm/px" if scale is not None else "\u672a\u6307\u5b9a (px)"
    )
    self.capacity_label.setText(f"{capacity:.2f} {unit}")
    self.wall_label.setText(f"{wall:.2f} {unit}")
    self.details_label.setText(
        f"\u5668\u9ad8: {result['vessel_height']:.2f} {length}\n"
        f"\u53e3\u5f84: {result['mouth_diameter']:.2f} {length}\n"
        f"\u6700\u5927\u5f84: {result['maximum_diameter']:.2f} {length}\n"
        f"\u5168\u5916\u5f62\u4f53\u7a4d: {capacity + wall:.2f} {unit}\n"
        f"\u30d1\u30c3\u30d7\u30b9\u691c\u7b97: {pappus:.2f} {unit} "
        f"({result['pappus_difference_percent']:.2f}%)\n"
        f"\u9069\u7528\u30b9\u30b1\u30fc\u30eb: {scale_text}"
    )
    log = [
        f"\u5bfe\u8c61\u30d5\u30a1\u30a4\u30eb: {path.name}",
        f"\u65ad\u9762\u30e2\u30fc\u30c9: {output.section_mode}",
        "\u8f2a\u90ed\u30fb\u56de\u8ee2\u8ef8\u306e\u691c\u51fa\u306f\u6b63\u5e38\u306b\u5b8c\u4e86\u3057\u307e\u3057\u305f\u3002",
    ]
    if output.warnings:
        log += ["", "\u3010\u6ce8\u610f\u30fb\u8b66\u544a\u3011"] + [
            f"\u30fb{item}" for item in output.warnings
        ]
    self.log.setPlainText("\n".join(log))
    self.status.setText(
        f"\u8a08\u7b97\u5b8c\u4e86: \u5bb9\u91cf {capacity:.2f} {unit}"
    )
    for button in self.result_copy_buttons:
        button.setEnabled(True)


def _copy_last_info(
    self: MainWindow,
    formatter: Any,
    include_header: bool = False,
) -> None:
    if self.last_info is None:
        return
    try:
        text = (
            formatter(self.last_info, include_header)
            if include_header
            else formatter(self.last_info)
        )
    except (KeyError, TypeError, ValueError) as exc:
        QMessageBox.warning(self, "コピーできません", str(exc))
        return
    QApplication.clipboard().setText(text)


def _copy_text_summary(self: MainWindow) -> None:
    if self.last_info is None:
        return
    QApplication.clipboard().setText(self.details_label.text())


def edit_profiles(self: MainWindow) -> None:
    output = self.current_analysis
    if output is None:
        return
    current_text = self.image_edit.text().strip().strip('"')
    if not current_text or not self._same_path(
        output.params.input_path, Path(current_text)
    ):
        QMessageBox.warning(
            self,
            "画像が一致しません",
            "表示中の画像と解析結果の画像が一致しないため輪郭を編集できません。",
        )
        return
    dialog = ProfileEditorDialog(
        output.profiles,
        output.image,
        float(output.result["axis_x_px"]),
        self,
        original_image=output.image,
    )
    if dialog.exec() != QDialog.DialogCode.Accepted:
        dialog.deleteLater()
        return
    try:
        corrected_profiles = dialog.corrected_profiles
        dialog.deleteLater()
        recomputed = compute_volumes(
            corrected_profiles,
            output.section.mask,
            float(output.result["axis_x_px"]),
            output.mm_per_px,
            output.section_mode,
        )
    except (OSError, ValueError) as exc:
        QMessageBox.critical(
            self, "\u518d\u8a08\u7b97\u3067\u304d\u307e\u305b\u3093", str(exc)
        )
        return
    output.profiles = corrected_profiles
    cast(dict[str, Any], output.result).update(cast(dict[str, Any], recomputed))
    output.warnings.append(
        "\u65ad\u9762\u30d7\u30ed\u30d5\u30a1\u30a4\u30eb\u3092\u624b\u52d5\u88dc\u6b63\u3057\u307e\u3057\u305f\u3002"
    )
    if output.params.debug_dir:
        try:
            visualize(
                output.image,
                float(output.result["axis_x_px"]),
                output.section,
                output.profiles,
                output.mm_per_px,
                output.params.debug_dir,
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "\u30c7\u30d0\u30c3\u30b0\u51fa\u529b\u3067\u304d\u307e\u305b\u3093",
                str(exc),
            )
    self._refresh_result()
    if self.history:
        self.history[-1] = self._history_row(
            output.result, Path(str(output.result["input"]))
        )
