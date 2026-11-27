"""Failure reporting tests for background GUI workers."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

import doki.gui.workers as workers_module
from doki.cli import AnalysisParams
from doki.gui.workers import (
    AnalysisFinished,
    AnalysisWorker,
    PairFinished,
    PairWorker,
    ScaleFinished,
    ScaleWorker,
    SetupDownloadWorker,
    WorkerFailed,
    _error_summary,
)


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (ValueError(""), "ValueError"),
        (ValueError("  first line  \nsecond line"), "ValueError: first line"),
        (RuntimeError("ordinary failure"), "RuntimeError: ordinary failure"),
    ],
)
def test_error_summary_handles_empty_and_multiline_messages(
    error: Exception,
    expected: str,
) -> None:
    assert _error_summary(error) == expected


def test_setup_download_cancel_sets_event_used_by_running_worker(
    monkeypatch,
    tmp_path: Path,
) -> None:
    observed: list[bool] = []

    def blocked_download(_commit, _destination, *, progress):
        observed.append(progress(0, 100))
        raise RuntimeError("download should have been cancelled")

    monkeypatch.setattr(workers_module, "download_setup", blocked_download)
    worker = SetupDownloadWorker("b" * 40, tmp_path / "PotteryVolume-Setup.exe")
    cancelled: list[bool] = []
    worker.cancelled.connect(lambda: cancelled.append(True))

    worker.cancel()
    worker.run()

    assert observed == [False]
    assert cancelled == [True]


def test_scale_worker_failure_includes_source_and_generation(caplog, tmp_path: Path):
    path = tmp_path / "missing-scale.png"
    worker = ScaleWorker(path, generation=27)
    failures: list[object] = []
    worker.failed.connect(failures.append)

    with caplog.at_level(logging.ERROR, logger=workers_module.__name__):
        worker.run()

    assert failures == [
        WorkerFailed(27, path, f"ValueError: 画像を読み込めません: {path}")
    ]
    assert any(record.exc_info for record in caplog.records)


def test_analysis_worker_failure_includes_generation_and_path(caplog, tmp_path: Path):
    path = tmp_path / "missing-pottery.png"
    worker = AnalysisWorker(AnalysisParams(input_path=path), generation=31)
    failures: list[object] = []
    worker.failed.connect(failures.append)

    with caplog.at_level(logging.ERROR, logger=workers_module.__name__):
        worker.run()

    assert failures == [
        WorkerFailed(31, path, f"ValueError: 画像を読み込めません: {path}")
    ]
    assert any(record.exc_info for record in caplog.records)


def test_scale_worker_emits_typed_finished_payload(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "scale.png"
    monkeypatch.setattr(workers_module, "read_image", lambda _path: object())
    monkeypatch.setattr(workers_module, "analyze_scale_candidates", lambda _image: ([], []))
    worker = ScaleWorker(path, generation=42)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == [ScaleFinished(42, path, [], [])]


def test_analysis_worker_emits_typed_finished_payload(monkeypatch, tmp_path: Path) -> None:
    path = tmp_path / "pottery.png"
    output = object()
    monkeypatch.setattr(workers_module, "analyze_detailed", lambda _params: output)
    worker = AnalysisWorker(AnalysisParams(input_path=path), generation=44)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == [AnalysisFinished(44, output)]


def test_pair_worker_uses_two_paths_and_emits_typed_payload(
    monkeypatch,
    tmp_path: Path,
) -> None:
    paths = (tmp_path / "pottery.png", tmp_path / "scale.png")
    result = (paths[0], paths[1], [], [])
    monkeypatch.setattr(
        workers_module,
        "classify_pottery_and_scale_with_candidates",
        lambda path_a, path_b: result,
    )
    worker = PairWorker(paths, generation=43)
    finished: list[object] = []
    worker.finished.connect(finished.append)

    worker.run()

    assert finished == [PairFinished(43, paths, result)]
