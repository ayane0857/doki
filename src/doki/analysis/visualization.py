"""Write diagnostic masks, drawing overlays, and radial profile plots."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from doki.analysis.image import SectionResult, write_image
from doki.analysis.profiles import Profiles


def visualize(
    image: np.ndarray,
    axis_x: float,
    section: SectionResult,
    profiles: Profiles,
    scale: float | None,
    debug_dir: Path,
) -> None:
    """Save an annotated detection overlay, radial profile plot, and masks."""
    import os

    os.environ.setdefault("MPLCONFIGDIR", str(debug_dir / ".mplconfig"))
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    debug_dir.mkdir(parents=True, exist_ok=True)
    overlay = image.copy()
    if overlay.ndim == 2:
        overlay = cv2.cvtColor(overlay, cv2.COLOR_GRAY2BGR)
    contour_mask = section.contour_mask
    if contour_mask is None:
        contour_mask = section.mask
    overlay[contour_mask > 0] = (40, 180, 80)
    if np.any(contour_mask):
        # Draw detected profile traces as red inner and blue outer curves.
        inside = np.column_stack(
            (np.rint(axis_x + profiles.r_in_px).astype(int), profiles.y_px.astype(int))
        )
        outside = np.column_stack(
            (np.rint(axis_x + profiles.r_out_px).astype(int), profiles.y_px.astype(int))
        )
        cv2.polylines(overlay, [inside], False, (0, 0, 255), 1, cv2.LINE_AA)
        cv2.polylines(overlay, [outside], False, (255, 0, 0), 1, cv2.LINE_AA)
    cv2.line(
        overlay,
        (int(round(axis_x)), 0),
        (int(round(axis_x)), image.shape[0] - 1),
        (255, 80, 0),
        1,
    )
    cv2.line(
        overlay,
        (0, int(round(profiles.liquid_y_px))),
        (image.shape[1] - 1, int(round(profiles.liquid_y_px))),
        (0, 180, 255),
        1,
    )
    write_image(debug_dir / "detection_overlay.png", overlay)
    write_image(debug_dir / "section_mask.png", section.mask)
    if section.closed_mask is not None:
        write_image(debug_dir / "section_closed.png", section.closed_mask)

    factor = scale if scale is not None else 1.0
    axis_label = "radius (mm)" if scale is not None else "radius (px)"
    height_label = "height from rim (mm)" if scale is not None else "image y (px)"
    fig, ax = plt.subplots(figsize=(7, 5), dpi=140)
    ax.plot(
        profiles.r_in_px * factor,
        (profiles.y_px - profiles.top_y_px) * factor,
        label="inner profile",
    )
    ax.plot(
        profiles.r_out_px * factor,
        (profiles.y_px - profiles.top_y_px) * factor,
        label="outer profile",
    )
    ax.invert_yaxis()
    ax.set_xlabel(axis_label)
    ax.set_ylabel(height_label)
    ax.set_title("Pottery radial profiles")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(debug_dir / "profiles.png")
    plt.close(fig)
