"""Pure helpers shared by the pottery volume GUI."""

from __future__ import annotations

import argparse
import math
from typing import Any

Info = dict[str, Any]
Result = dict[str, Any]


class GUIArgumentParser(argparse.ArgumentParser):
    """Raise readable validation errors instead of exiting a background worker."""

    def error(self, message: str) -> None:
        raise ValueError(message)


def pixel_distance(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    """Return the distance between two image points in pixels."""
    distance = math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
    if not math.isfinite(distance):
        raise ValueError("2点間の距離を計算できません。")
    return distance


def build_tsv_row(info: Info, include_header: bool = False) -> str:
    """Format analysis result into a single tab-separated line for Excel."""
    res: Result = info["result"]
    image_name = str(info["image_name"])
    length_unit = str(res["units"]["length"])
    volume_unit = str(res["units"]["volume"])
    is_mm = "capacity_ml" in res
    scale_mm_per_px = res.get("mm_per_px", res.get("scale_mm_per_px"))
    if is_mm and volume_unit in {"mm3", "mm³"}:
        volume_unit = "mL"
    headers = [
        "画像ファイル", f"器高({length_unit})", f"口径({length_unit})",
        f"最大径({length_unit})", f"内腔容量({volume_unit})",
        f"器壁体積({volume_unit})", f"全外形体積({volume_unit})",
        f"パップス検算({volume_unit})", "パップス差(%)",
    ]
    if is_mm:
        headers.append("mm/px")
        data = [
            image_name,
            f"{res['vessel_height']:.2f}", f"{res['mouth_diameter']:.2f}",
            f"{res['maximum_diameter']:.2f}", f"{res['capacity_ml']:.2f}",
            f"{res['wall_volume_ml']:.2f}",
            f"{res['capacity_ml'] + res['wall_volume_ml']:.2f}",
            f"{res['pappus_wall_volume_ml']:.2f}",
            f"{res['pappus_difference_percent']:.2f}",
            f"{scale_mm_per_px:.4f}" if scale_mm_per_px is not None else "",
        ]
    else:
        data = [
            image_name,
            f"{res['vessel_height']:.2f}", f"{res['mouth_diameter']:.2f}",
            f"{res['maximum_diameter']:.2f}", f"{res['capacity']:.2f}",
            f"{res['wall_volume']:.2f}", f"{res['capacity'] + res['wall_volume']:.2f}",
            f"{res['pappus_wall_volume']:.2f}",
            f"{res['pappus_difference_percent']:.2f}",
        ]
    lines = ["\t".join(headers)] if include_header else []
    lines.append("\t".join(data))
    return "\n".join(lines)


def build_tsv_table(info: Info) -> str:
    """Format analysis result into vertical tab-separated table rows for Excel."""
    res: Result = info["result"]
    image_name = str(info["image_name"])
    length_unit = str(res["units"]["length"])
    volume_unit = str(res["units"]["volume"])
    scale_mm_per_px = res.get("mm_per_px", res.get("scale_mm_per_px"))
    rows = [
        ("項目", "値", "単位"), ("画像ファイル", image_name, ""),
        ("器高", f"{res['vessel_height']:.2f}", length_unit),
        ("口径", f"{res['mouth_diameter']:.2f}", length_unit),
        ("最大径", f"{res['maximum_diameter']:.2f}", length_unit),
    ]
    if "capacity_ml" in res:
        rows.extend([
            ("内腔容量", f"{res['capacity_ml']:.2f}", "mL"),
            ("内腔容量(cm³)", f"{res['capacity_cm3']:.2f}", "cm³"),
            ("器壁体積", f"{res['wall_volume_ml']:.2f}", "mL"),
            ("全外形体積", f"{res['capacity_ml'] + res['wall_volume_ml']:.2f}", "mL"),
            ("パップス検算", f"{res['pappus_wall_volume_ml']:.2f}", "mL"),
            ("パップス差", f"{res['pappus_difference_percent']:.2f}", "%"),
        ])
        if scale_mm_per_px is not None:
            rows.append(("\u30b9\u30b1\u30fc\u30eb", f"{scale_mm_per_px:.4f}", "mm/px"))
    else:
        rows.extend([
            ("内腔容量", f"{res['capacity']:.2f}", volume_unit),
            ("器壁体積", f"{res['wall_volume']:.2f}", volume_unit),
            ("全外形体積", f"{res['capacity'] + res['wall_volume']:.2f}", volume_unit),
            ("パップス検算", f"{res['pappus_wall_volume']:.2f}", volume_unit),
            ("パップス差", f"{res['pappus_difference_percent']:.2f}", "%"),
        ])
    return "\n".join(f"{a}\t{b}\t{c}".rstrip() for a, b, c in rows)
