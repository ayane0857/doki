"""Background worker classes used by the desktop interface."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pottery_scale import analyze_scale_candidates, classify_pottery_and_scale_with_candidates
from pottery_volume_cli import analyze_detailed
from pottery_volume_core import read_image
from pottery_volume_gui_helpers import GUIArgumentParser


def create_worker_classes(qt: Any) -> tuple[type, type, type]:
    QObject, Signal, Slot = qt.QObject, qt.Signal, qt.Slot

    class AnalysisWorker(QObject):
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, arguments: list[str]) -> None:
            super().__init__()
            self.arguments = arguments

        @Slot()
        def run(self) -> None:
            try:
                self.finished.emit(
                    analyze_detailed(self.arguments, parser_class=GUIArgumentParser)
                )
            except Exception as exc:
                self.failed.emit(str(exc))

    class ScaleWorker(QObject):
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, path: Path, generation: int) -> None:
            super().__init__()
            self.path = path
            self.generation = generation

        @Slot()
        def run(self) -> None:
            try:
                labels, bars = analyze_scale_candidates(read_image(self.path))
                self.finished.emit((self.path, self.generation, labels, bars))
            except Exception as exc:
                self.failed.emit(str(exc))

    class PairWorker(QObject):
        finished = Signal(object)
        failed = Signal(str)

        def __init__(self, paths: list[Path]) -> None:
            super().__init__()
            self.paths = paths

        @Slot()
        def run(self) -> None:
            try:
                result = classify_pottery_and_scale_with_candidates(*self.paths)
                self.finished.emit(result)
            except Exception as exc:
                self.failed.emit(str(exc))

    return AnalysisWorker, ScaleWorker, PairWorker
