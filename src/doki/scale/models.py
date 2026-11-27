"""Candidate data shared by scale OCR, detection, and matching."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class ScaleTextCandidate:
    """An OCR text box containing a metric length."""

    text: str
    value: float
    unit: str
    length_mm: float
    confidence: float
    bounds: tuple[float, float, float, float]


@dataclass(frozen=True)
class ScaleBarCandidate:
    """A detected straight horizontal line that may be a scale bar."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float = 0.0
    tick_support: int = 0

    @property
    def pixels(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)
