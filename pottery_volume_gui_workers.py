"""Background worker objects used by the desktop interface."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

from pottery_scale import (
    ScaleBarCandidate,
    ScaleTextCandidate,
    analyze_scale_candidates,
    classify_pottery_and_scale_with_candidates,
)
from pottery_volume_cli import AnalysisOutput, AnalysisParams, analyze_detailed
from pottery_volume_core import read_image
from pottery_volume_updater import download_setup, resolve_latest_release

logger = logging.getLogger(__name__)

PairPaths = tuple[Path, Path]
WorkerSource = Path | PairPaths
PairResult = tuple[Path, Path, list[ScaleTextCandidate], list[ScaleBarCandidate]]


@dataclass(frozen=True)
class AnalysisFinished:
    generation: int
    output: AnalysisOutput


@dataclass(frozen=True)
class ScaleFinished:
    generation: int
    path: Path
    labels: list[ScaleTextCandidate]
    bars: list[ScaleBarCandidate]


@dataclass(frozen=True)
class PairFinished:
    generation: int
    paths: PairPaths
    result: PairResult


@dataclass(frozen=True)
class WorkerFailed:
    generation: int
    source: WorkerSource
    summary: str


class UpdateCheckWorker(QObject):
    """Check the latest release without blocking the GUI event loop."""

    finished = Signal(str)
    failed = Signal(str)

    @Slot()
    def run(self) -> None:
        try:
            self.finished.emit(resolve_latest_release())
        except Exception as exc:
            logger.info("Update check failed", exc_info=True)
            self.failed.emit(str(exc))


class SetupDownloadWorker(QObject):
    """Download and verify the replacement installer in a worker thread."""

    progress = Signal(int, int)
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, commit: str, destination: Path) -> None:
        super().__init__()
        self.commit = commit
        self.destination = destination
        self._cancel_requested = threading.Event()

    def cancel(self) -> None:
        self._cancel_requested.set()

    @Slot()
    def run(self) -> None:
        def report_progress(received: int, total: int | None) -> bool:
            if self._cancel_requested.is_set():
                return False
            self.progress.emit(received, total or 0)
            return True

        try:
            path = download_setup(
                self.commit,
                self.destination,
                progress=report_progress,
            )
        except Exception as exc:
            if self._cancel_requested.is_set():
                self.cancelled.emit()
            else:
                logger.info("Setup download failed", exc_info=True)
                self.failed.emit(str(exc))
        else:
            self.finished.emit(path)


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
            self.finished.emit(AnalysisFinished(self.generation, output))
        except Exception as exc:
            logger.exception("Analysis worker failed for %s", self.params.input_path)
            self.failed.emit(
                WorkerFailed(
                    self.generation,
                    self.params.input_path,
                    _error_summary(exc),
                )
            )


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
            self.finished.emit(ScaleFinished(self.generation, self.path, labels, bars))
        except Exception as exc:
            logger.exception("Scale worker failed for %s", self.path)
            self.failed.emit(
                WorkerFailed(self.generation, self.path, _error_summary(exc))
            )


class PairWorker(QObject):
    finished = Signal(object)
    failed = Signal(object)

    def __init__(self, paths: PairPaths, generation: int) -> None:
        super().__init__()
        self.paths = paths
        self.generation = generation

    @Slot()
    def run(self) -> None:
        try:
            result = classify_pottery_and_scale_with_candidates(*self.paths)
            self.finished.emit(PairFinished(self.generation, self.paths, result))
        except Exception as exc:
            logger.exception("Pair worker failed for %s", self.paths)
            self.failed.emit(
                WorkerFailed(self.generation, self.paths, _error_summary(exc))
            )
