"""Recognize and parse metric scale labels."""

from __future__ import annotations

import math
import re
import threading
import unicodedata
from functools import lru_cache
from typing import Any

import numpy as np

from doki.scale.models import ScaleTextCandidate

# A number directly followed by a unit. Whitespace is only allowed between the
# number and its unit, so "0 5 10cm" reads as 10 cm (not 510 cm).
_SCALE_TEXT = re.compile(
    r"(?<![\d.,])([+-]?\s*[0-9oil|]+(?:[.,][0-9oil|]+)?)\s*(mm|cm|m)(?![a-z])",
    re.IGNORECASE,
)
_UNIT_TO_MM = {"mm": 1.0, "cm": 10.0, "m": 1000.0}


def parse_metric_length(text: str) -> tuple[float, str, float] | None:
    """Parse a length such as ``10cm`` and return value, unit, and millimetres.

    When several lengths appear (``0 5 10cm``), the last one is used because a
    scale bar's full length is printed at its far end.
    """
    normalized = unicodedata.normalize("NFKC", text).replace("\u2212", "-").lower()
    normalized = normalized.replace("μ", "u").replace("µ", "u")
    best: tuple[float, str, float] | None = None
    for match in _SCALE_TEXT.finditer(normalized):
        number_text = "".join(match.group(1).split())
        if not any(char.isdigit() for char in number_text):
            continue  # "aim", "il m": OCR look-alike letters only
        for source, replacement in (("o", "0"), ("i", "1"), ("l", "1"), ("|", "1")):
            number_text = number_text.replace(source, replacement)
        number_text = number_text.replace(",", ".")
        try:
            value = float(number_text)
        except ValueError:
            continue
        unit = match.group(2).lower()
        length_mm = value * _UNIT_TO_MM[unit]
        if math.isfinite(length_mm) and value > 0:
            best = (value, unit, length_mm)
    return best


@lru_cache(maxsize=1)
def _ocr_engine() -> Any:
    """Create RapidOCR only when a user opens the calibration tool."""
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError(
            "OCRエンジンを読み込めません。RapidOCRとONNX Runtimeをインストールしてください。"
        ) from exc
    return RapidOCR()


_ocr_lock = threading.Lock()


def recognize_scale_text(image: np.ndarray) -> list[ScaleTextCandidate]:
    """Read metric length labels from an image using the bundled OCR engine."""
    with _ocr_lock:
        result = _ocr_engine()(image)
    texts = getattr(result, "txts", None)
    if texts is None:
        texts = ()
    boxes = getattr(result, "boxes", None)
    scores = getattr(result, "scores", None)
    candidates: list[ScaleTextCandidate] = []
    for index, text in enumerate(texts):
        parsed = parse_metric_length(str(text))
        if parsed is None:
            continue
        value, unit, length_mm = parsed
        if boxes is not None and index < len(boxes):
            points = np.asarray(boxes[index], dtype=float).reshape(-1, 2)
            x0, y0 = float(np.min(points[:, 0])), float(np.min(points[:, 1]))
            x1, y1 = float(np.max(points[:, 0])), float(np.max(points[:, 1]))
            bounds = (x0, y0, x1, y1)
        else:
            bounds = (0.0, 0.0, 0.0, 0.0)
        confidence = (
            float(scores[index]) if scores is not None and index < len(scores) else 0.0
        )
        candidates.append(
            ScaleTextCandidate(str(text), value, unit, length_mm, confidence, bounds)
        )
    return sorted(candidates, key=lambda item: item.confidence, reverse=True)
