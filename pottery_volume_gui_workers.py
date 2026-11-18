"""Background worker objects used by the desktop interface."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from pottery_scale import analyze_scale_candidates, classify_pottery_and_scale_with_candidates
from pottery_volume_cli import AnalysisParams, analyze_detailed
from pottery_volume_core import read_image

logger = logging.getLogger(__name__)


def _error_summary(error: Exception) -> str:
    """Keep GUI error text concise while the logger retains the traceback."""
    message = next((line.strip() for line in str(error).splitlines() if line.strip()), "")
    error_name = type(error).__name__
    return f"{error_name}: {message}" if message else error_name


class AnalysisWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, params: AnalysisParams, generation: int) -> None:
        super().__init__()
        self.params = params
        self.generation = generation

    @Slot()
    def run(self) -> None:
        try:
            output = analyze_detailed(self.params)
            self.finished.emit((self.generation, output))
        except Exception as exc:
            logger.exception("Analysis worker failed for %s", self.params.input_path)
            self.failed.emit((self.generation, self.params.input_path, _error_summary(exc)))


class ScaleWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)

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
            logger.exception("Scale worker failed for %s", self.path)
            self.failed.emit((self.path, self.generation, _error_summary(exc)))


class PairWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, paths: list[Path], generation: int) -> None:
        super().__init__()
        self.paths = paths
        self.generation = generation

    @Slot()
    def run(self) -> None:
        try:
            result = classify_pottery_and_scale_with_candidates(*self.paths)
            self.finished.emit((self.generation, result))
        except Exception as exc:
            logger.exception("Pair worker failed for %s", self.paths)
            self.failed.emit((self.generation, self.paths, _error_summary(exc)))
