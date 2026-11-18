"""Failure reporting tests for background GUI workers."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from pottery_volume_cli import AnalysisParams
from pottery_volume_gui_workers import AnalysisWorker, ScaleWorker, _error_summary


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


def test_scale_worker_failure_includes_source_and_generation(caplog, tmp_path: Path):
    path = tmp_path / "missing-scale.png"
    worker = ScaleWorker(path, generation=27)
    failures: list[object] = []
    worker.failed.connect(failures.append)

    with caplog.at_level(logging.ERROR, logger="pottery_volume_gui_workers"):
        worker.run()

    assert failures == [(path, 27, f"ValueError: 画像を読み込めません: {path}")]
    assert any(record.exc_info for record in caplog.records)


def test_analysis_worker_failure_includes_generation_and_path(caplog, tmp_path: Path):
    path = tmp_path / "missing-pottery.png"
    worker = AnalysisWorker(AnalysisParams(input_path=path), generation=31)
    failures: list[object] = []
    worker.failed.connect(failures.append)

    with caplog.at_level(logging.ERROR, logger="pottery_volume_gui_workers"):
        worker.run()

    assert failures == [(31, path, f"ValueError: 画像を読み込めません: {path}")]
    assert any(record.exc_info for record in caplog.records)
