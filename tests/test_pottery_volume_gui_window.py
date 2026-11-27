"""Stale-result handling for the desktop window."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetSelectionRange, QWidget

from doki.gui.window.main import HistoryTable, MainWindow
from doki.gui.workers import AnalysisFinished, WorkerFailed


@pytest.fixture
def qt_widget(qt_app: QApplication) -> Iterator[Callable[[QWidget], None]]:
    widgets: list[QWidget] = []
    yield widgets.append

    for widget in reversed(widgets):
        widget.close()
        widget.deleteLater()
        # processEvents() alone does not deliver DeferredDelete without an event loop.
        QCoreApplication.sendPostedEvents(widget, QEvent.Type.DeferredDelete)
    qt_app.processEvents()


def test_old_worker_failures_and_results_are_discarded(tmp_path: Path, qt_widget):
    window = MainWindow(None)
    qt_widget(window)

    window.scale_image_edit.setText(str(tmp_path / "new-scale.png"))
    old_scale_generation = window.scale_generation - 1
    window._scale_failed(
        WorkerFailed(old_scale_generation, tmp_path / "old-scale.png", "old error")
    )
    assert "古い解析エラーを破棄" in window.status.text()

    window.image_edit.setText(str(tmp_path / "new-pottery.png"))
    old_analysis_generation = window.analysis_generation - 1
    window._analysis_finished(AnalysisFinished(old_analysis_generation, None))
    assert window.current_analysis is None
    assert "古い解析結果を破棄" in window.status.text()


def test_scale_auto_apply_uses_the_confident_label_for_the_selected_bar(tmp_path: Path, qt_widget):
    from doki.scale.calibration import (
        ScaleBarCandidate,
        ScaleTextCandidate,
        associate_label_with_bar,
    )

    window = MainWindow(None)
    qt_widget(window)
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.59, (190, 50, 220, 70))
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.95, (260, 50, 300, 70))
    bar = ScaleBarCandidate(20, 60, 220, 60, 0.95, 1)
    labels = associate_label_with_bar([label_10cm, label_5cm], bar)
    window.known_mm_edit.setText("999")

    assert labels[0] == label_5cm
    window._apply_scale_result(labels, [bar], tmp_path / "scale.png")

    assert window.known_mm_edit.text() == "100"
    assert window.bar_px_edit.text() == "200.00"
    assert "10cm" in window.status.text()
    assert window.scale_applied_label == label_10cm
    assert window.scale_applied_bar == bar


def test_applied_mm_precision_still_matches_ocr_label_in_dialog(qt_widget):
    from doki.gui.scale_dialog import ScaleCalibrationDialog
    from doki.scale.calibration import ScaleBarCandidate, ScaleTextCandidate

    window = MainWindow(None)
    qt_widget(window)
    image_path = Path(__file__).parent / "fixtures" / "scale_image.png"
    label = ScaleTextCandidate(
        "12.3456789cm", 12.3456789, "cm", 123.456789, 0.99, (260, 50, 300, 70)
    )
    bar = ScaleBarCandidate(20, 60, 220, 60, 0.95, 1)

    window._apply_scale_result([label], [bar], image_path)
    default_mm = float(window.known_mm_edit.text())
    dialog = ScaleCalibrationDialog(
        image_path,
        [label],
        [bar],
        default_mm,
        None,
        selected_label=label,
        selected_bar=bar,
    )
    qt_widget(dialog)

    assert window.known_mm_edit.text() == "123.456789"
    assert dialog.label_combo.currentData() == label
    assert dialog.label_combo.count() == 1
    assert dialog.length_spin.value() == pytest.approx(123.456789)
    dialog.accept()
    assert dialog.length_mm == pytest.approx(123.456789)
    assert dialog.mm_per_px == pytest.approx(123.456789 / 200)


def test_scale_dialog_keeps_applied_pair_until_label_is_explicitly_changed(monkeypatch, qt_widget):
    import doki.gui.scale_dialog as scale_dialog_module
    from doki.gui.scale_dialog import ScaleCalibrationDialog
    from doki.scale.calibration import ScaleBarCandidate, ScaleTextCandidate

    image_path = Path(__file__).parent / "fixtures" / "scale_image.png"
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.90, (30, 30, 70, 50))
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.95, (450, 30, 540, 50))
    bar_5cm = ScaleBarCandidate(30, 100, 230, 100, 0.90, 1)
    bar_10cm = ScaleBarCandidate(250, 100, 450, 100, 0.90, 1)

    def rank(_bars, label, _image_shape):
        return [bar_5cm, bar_10cm] if label == label_10cm else [bar_10cm, bar_5cm]

    monkeypatch.setattr(scale_dialog_module, "rank_scale_bars", rank)
    dialog = ScaleCalibrationDialog(
        image_path,
        [label_5cm, label_10cm],
        [bar_5cm, bar_10cm],
        100,
        None,
        selected_label=label_10cm,
        selected_bar=bar_10cm,
    )
    qt_widget(dialog)

    assert dialog.label_combo.currentData() == label_10cm
    assert dialog.length_spin.value() == 100
    assert dialog.unit_combo.currentText() == "mm"
    assert dialog.bars == [bar_5cm, bar_10cm]
    assert dialog.bar_combo.currentIndex() == 1

    dialog.label_combo.setCurrentIndex(0)

    assert dialog.length_spin.value() == 5
    assert dialog.unit_combo.currentText() == "cm"
    assert dialog.bars == [bar_10cm, bar_5cm]
    assert dialog.bar_combo.currentIndex() == 0


def test_scale_dialog_offers_keep_current_when_no_ocr_length_matches(qt_widget):
    from doki.gui.scale_dialog import ScaleCalibrationDialog
    from doki.scale.calibration import ScaleBarCandidate, ScaleTextCandidate

    image_path = Path(__file__).parent / "fixtures" / "scale_image.png"
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.90, (30, 30, 70, 50))
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.95, (450, 30, 540, 50))
    bar = ScaleBarCandidate(30, 100, 230, 100, 0.90, 1)
    dialog = ScaleCalibrationDialog(
        image_path, [label_5cm, label_10cm], [bar], 75, None,
        selected_label=label_5cm, selected_bar=bar,
    )
    qt_widget(dialog)

    assert "長さを維持" in dialog.label_combo.currentText()
    assert dialog.label_combo.currentData() is None
    assert dialog.length_spin.value() == 75
    assert dialog.unit_combo.currentText() == "mm"

    dialog.label_combo.setCurrentIndex(2)
    assert dialog.length_spin.value() == 10
    assert dialog.unit_combo.currentText() == "cm"

    dialog.label_combo.setCurrentIndex(0)
    assert dialog.length_spin.value() == 75
    assert dialog.unit_combo.currentText() == "mm"
    dialog.accept()
    assert dialog.length_mm == pytest.approx(75)
    assert dialog.mm_per_px == pytest.approx(0.375)


def test_measure_scale_passes_applied_pair_for_same_image(monkeypatch, qt_widget):
    from PySide6.QtWidgets import QDialog

    from doki.gui.scale_dialog import ScaleCalibrationDialog
    from doki.gui.window import inputs as inputs_module
    from doki.scale.calibration import ScaleBarCandidate, ScaleTextCandidate

    window = MainWindow(None)
    qt_widget(window)
    image_path = Path(__file__).parent / "fixtures" / "scale_image.png"
    label_5cm = ScaleTextCandidate("5cm", 5, "cm", 50, 0.95, (190, 50, 220, 70))
    label_10cm = ScaleTextCandidate("10cm", 10, "cm", 100, 0.95, (260, 50, 300, 70))
    automatic_bar = ScaleBarCandidate(20, 100, 220, 100, 0.95, 1)
    corrected_bar = ScaleBarCandidate(30, 100, 230, 100, 0.92, 1)
    corrected_points = ((30.0, 100.0), (430.0, 100.0))
    captured_selections = []

    class DialogStub:
        def __init__(
            self,
            _path,
            _labels,
            _bars,
            default_mm,
            _parent,
            *,
            selected_label=None,
            selected_bar=None,
            selected_points=None,
        ):
            captured_selections.append(
                (default_mm, selected_label, selected_bar, selected_points)
            )
            self.mm_per_px = 0.125
            self.line_pixels = 400.0
            self.length_mm = 50.0
            self.line_points = corrected_points
            self.bars = [automatic_bar, corrected_bar]

            class LabelCombo:
                def currentData(self):
                    return label_5cm

            class BarCombo:
                def currentIndex(self):
                    return 1

            self.label_combo = LabelCombo()
            self.bar_combo = BarCombo()

        def exec(self):
            return QDialog.DialogCode.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(inputs_module, "ScaleCalibrationDialog", DialogStub)
    window.scale_image_edit.setText(str(image_path))
    window.scale_labels = [label_5cm, label_10cm]
    window.scale_bars = [automatic_bar, corrected_bar]
    window.scale_detection_path = image_path.resolve()
    window.scale_applied_path = image_path.resolve()
    window.scale_applied_label = label_10cm
    window.scale_applied_bar = automatic_bar
    window.scale_applied_points = ((20.0, 100.0), (220.0, 100.0))
    window.known_mm_edit.setText("100")

    window.measure_scale()
    assert window.scale_applied_bar == corrected_bar
    assert window.scale_applied_label == label_5cm
    assert window.scale_applied_points == corrected_points
    assert window.known_mm_edit.text() == "50"
    assert window.bar_px_edit.text() == "400.00"
    assert window.direct_edit.text() == "0.125"
    assert window.scale_mode.currentText() == "mm/px を直接指定"
    window.measure_scale()

    assert captured_selections == [
        (100.0, label_10cm, automatic_bar, ((20.0, 100.0), (220.0, 100.0))),
        (50.0, label_5cm, corrected_bar, corrected_points),
    ]

    dialog = ScaleCalibrationDialog(
        image_path,
        window.scale_labels,
        window.scale_bars,
        float(window.known_mm_edit.text()),
        None,
        selected_label=window.scale_applied_label,
        selected_bar=window.scale_applied_bar,
        selected_points=window.scale_applied_points,
    )
    qt_widget(dialog)
    assert dialog.label_combo.currentData() == label_5cm
    assert dialog.bars[dialog.bar_combo.currentIndex()] == corrected_bar
    assert dialog._selected_points() == list(corrected_points)
    dialog.accept()
    assert dialog.length_mm == pytest.approx(50)
    assert dialog.line_pixels == pytest.approx(400)
    assert dialog.line_points == corrected_points
    assert dialog.mm_per_px == pytest.approx(0.125)


def test_manual_endpoints_persist_on_reopen_without_detected_candidates(monkeypatch, qt_widget):
    from PySide6.QtWidgets import QDialog

    from doki.gui.scale_dialog import ScaleCalibrationDialog
    from doki.gui.window import inputs as inputs_module

    window = MainWindow(None)
    qt_widget(window)
    image_path = Path(__file__).parent / "fixtures" / "scale_image.png"
    manual_points = ((20.0, 100.0), (420.0, 100.0))
    captured_points = []

    class DialogStub:
        def __init__(self, _path, _labels, _bars, _default_mm, _parent, **kwargs):
            captured_points.append(kwargs.get("selected_points"))
            self.mm_per_px = 0.25
            self.line_pixels = 400.0
            self.length_mm = 100.0
            self.line_points = manual_points
            self.bars = []

            class LabelCombo:
                def currentData(self):
                    return None

            class BarCombo:
                def currentIndex(self):
                    return 0

            self.label_combo = LabelCombo()
            self.bar_combo = BarCombo()

        def exec(self):
            return QDialog.DialogCode.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(inputs_module, "ScaleCalibrationDialog", DialogStub)
    window.scale_image_edit.setText(str(image_path))
    window.known_mm_edit.setText("100")

    window.measure_scale()

    assert window.scale_applied_path == image_path.resolve()
    assert window.scale_applied_bar is None
    assert window.scale_applied_points == manual_points
    assert window.bar_px_edit.text() == "400.00"
    assert window.direct_edit.text() == "0.25"

    dialog = ScaleCalibrationDialog(
        image_path,
        [],
        [],
        100,
        None,
        selected_points=window.scale_applied_points,
    )
    qt_widget(dialog)
    assert dialog._selected_points() == list(manual_points)
    dialog.accept()
    assert dialog.length_mm == pytest.approx(100)
    assert dialog.line_pixels == pytest.approx(400)
    assert dialog.mm_per_px == pytest.approx(0.25)
    assert dialog.line_points == manual_points


@pytest.mark.parametrize("change_path", [False, True])
def test_stale_dialog_does_not_overwrite_new_detection_state(
    tmp_path: Path, monkeypatch, change_path: bool, qt_widget
):
    from PySide6.QtWidgets import QDialog

    from doki.gui.window import inputs as inputs_module
    from doki.scale.calibration import ScaleBarCandidate, ScaleTextCandidate

    window = MainWindow(None)
    qt_widget(window)
    image_path = Path(__file__).parent / "fixtures" / "scale_image.png"
    new_path = tmp_path / "new-scale.png" if change_path else image_path
    old_label = ScaleTextCandidate("10cm", 10, "cm", 100, 0.95, (260, 50, 300, 70))
    old_bar = ScaleBarCandidate(20, 60, 220, 60, 0.95, 1)
    stale_bar = ScaleBarCandidate(30, 70, 230, 70, 0.92, 1)
    new_label = ScaleTextCandidate("20cm", 20, "cm", 200, 0.99, (260, 50, 320, 70))
    new_bar = ScaleBarCandidate(20, 60, 320, 60, 0.95, 1)

    class DialogStub:
        def __init__(self, *_args, **_kwargs):
            self.mm_per_px = 0.25
            self.line_pixels = 200.0
            self.length_mm = 50.0
            self.label_combo = type("LabelCombo", (), {"currentData": lambda _self: old_label})()
            self.bars = [old_bar, stale_bar]
            self.bar_combo = type("BarCombo", (), {"currentIndex": lambda _self: 1})()

        def exec(self):
            window._apply_scale_result([new_label], [new_bar], new_path)
            window.direct_edit.setText("0.75")
            return QDialog.DialogCode.Accepted

        def deleteLater(self):
            pass

    monkeypatch.setattr(inputs_module, "ScaleCalibrationDialog", DialogStub)
    window.scale_image_edit.setText(str(image_path))
    window.scale_labels = [old_label]
    window.scale_bars = [old_bar, stale_bar]
    window.scale_detection_path = image_path.resolve()
    window.scale_applied_label = old_label
    window.scale_applied_bar = old_bar
    window.known_mm_edit.setText("100")

    generation = window.scale_generation
    window.measure_scale()

    assert window.scale_detection_path == new_path.resolve()
    assert window.scale_applied_label == new_label
    assert window.scale_applied_bar == new_bar
    assert window.known_mm_edit.text() == "200"
    assert window.bar_px_edit.text() == "300.00"
    assert window.direct_edit.text() == "0.75"
    assert window.scale_mode.currentText() == "スケール線の px と mm"
    assert window.scale_generation == generation


@pytest.mark.parametrize("key", [Qt.Key.Key_Delete, Qt.Key.Key_Backspace])
def test_history_table_clears_selected_cells_with_delete_or_backspace(key, qt_app, qt_widget):
    records = [
        {
            "画像ファイル": "vessel.png",
            "器高": "12.3",
            "最大径": "45.6",
        }
    ]
    table = HistoryTable(records)
    qt_widget(table)
    table.show()
    table.setRangeSelected(QTableWidgetSelectionRange(0, 0, 0, 1), True)
    table.setFocus()
    qt_app.processEvents()

    QTest.keyClick(table, key)

    assert table.item(0, 0).text() == ""
    assert table.item(0, 1).text() == ""
    assert table.item(0, 3).text() == "45.6"
    assert records[0]["画像ファイル"] == ""
    assert records[0]["器高"] == ""
    assert records[0]["最大径"] == "45.6"
