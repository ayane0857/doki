"""Pure helpers shared by the pottery volume GUI."""

from __future__ import annotations

import argparse
import math
import warnings
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Never, TypedDict, cast

from pottery_volume_cli import AnalysisResult
from pottery_volume_geometry import pixel_distance

Result = AnalysisResult


class Info(TypedDict):
    """Analysis context consumed by TSV export helpers."""

    title: str
    image_name: str
    image_path: str
    result: Result


TSVSource = Literal["result", "image_name", "outer_volume", "scale"]
TSVUnit = Literal["", "length", "volume", "cm3", "percent", "scale"]
TSVCondition = Literal["always", "never", "scaled", "scale_available"]


class GUIArgumentParser(argparse.ArgumentParser):
    """Deprecated parser shim; GUI workers now receive ``AnalysisParams``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        warnings.warn(
            "GUIArgumentParser は非推奨です。AnalysisParams を直接使用してください。",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)

    def error(self, message: str) -> Never:
        raise ValueError(message)


@dataclass(frozen=True)
class TSVItem:
    """One spreadsheet field shared by horizontal and vertical TSV output."""

    label: str
    result_key: str | None
    unit: TSVUnit
    decimals: int | None
    scaled_key: str | None = None
    alternate_key: str | None = None
    source: TSVSource = "result"
    row_condition: TSVCondition = "always"
    table_condition: TSVCondition = "always"


_SCALE_TSV_ITEM = TSVItem(
    "スケール",
    "mm_per_px",
    "scale",
    4,
    alternate_key="scale_mm_per_px",
    source="scale",
    row_condition="scaled",
    table_condition="scale_available",
)


TSV_ITEMS: tuple[TSVItem, ...] = (
    TSVItem("画像ファイル", None, "", None, source="image_name"),
    TSVItem("器高", "vessel_height", "length", 2),
    TSVItem("口径", "mouth_diameter", "length", 2),
    TSVItem("最大径", "maximum_diameter", "length", 2),
    TSVItem("内腔容量", "capacity", "volume", 2, scaled_key="capacity_ml"),
    TSVItem(
        "内腔容量(cm³)",
        "capacity_cm3",
        "cm3",
        2,
        row_condition="never",
        table_condition="scaled",
    ),
    TSVItem("器壁体積", "wall_volume", "volume", 2, scaled_key="wall_volume_ml"),
    TSVItem("全外形体積", None, "volume", 2, source="outer_volume"),
    TSVItem(
        "パップス検算",
        "pappus_wall_volume",
        "volume",
        2,
        scaled_key="pappus_wall_volume_ml",
    ),
    TSVItem("パップス差", "pappus_difference_percent", "percent", 2),
    _SCALE_TSV_ITEM,
)


class _OutputContext:
    def __init__(self, info: Info) -> None:
        self.info = info
        self.result: Result = info["result"]
        # Core results always carry mm_per_px; keep capacity_ml as a fallback
        # for older hand-built TSV dictionaries that omit the canonical field.
        if "mm_per_px" in self.result:
            self.is_scaled = self.result["mm_per_px"] is not None
            self.scale_value = self.result["mm_per_px"]
        else:
            legacy_result = cast(Mapping[str, Any], self.result)
            self.is_scaled = "capacity_ml" in legacy_result
            self.scale_value = legacy_result.get("scale_mm_per_px")
        self.length_unit = str(self.result["units"]["length"])
        self.volume_unit = str(self.result["units"]["volume"])
        # Scaled results read from the *_ml keys, so the unit is always mL.
        self.row_volume_unit = "mL" if self.is_scaled else self.volume_unit


def _include(
    item: TSVItem,
    context: _OutputContext,
    output: Literal["row", "table"],
) -> bool:
    condition = item.row_condition if output == "row" else item.table_condition
    if condition == "never":
        return False
    if condition == "scaled":
        return context.is_scaled
    if condition == "scale_available":
        return context.scale_value is not None
    return True


def _item_value(item: TSVItem, context: _OutputContext) -> Any:
    result = cast(Mapping[str, Any], context.result)
    if item.source == "image_name":
        return context.info["image_name"]
    if item.source == "scale":
        return context.scale_value
    if item.source == "outer_volume":
        if context.is_scaled:
            return result["capacity_ml"] + result["wall_volume_ml"]
        return result["capacity"] + result["wall_volume"]

    result_key = (
        item.scaled_key if context.is_scaled and item.scaled_key else item.result_key
    )
    if result_key is None:
        raise KeyError(f"TSV項目 {item.label!r} に結果キーがありません")
    return result[result_key]


def _item_unit(
    item: TSVItem,
    context: _OutputContext,
    output: Literal["row", "table"],
) -> str:
    if item.unit == "length":
        return context.length_unit
    if item.unit == "volume":
        if output == "row":
            return context.row_volume_unit
        return "mL" if context.is_scaled else context.volume_unit
    if item.unit == "cm3":
        return "cm³"
    if item.unit == "percent":
        return "%"
    if item.unit == "scale":
        return "mm/px"
    return ""


def _row_header(item: TSVItem, context: _OutputContext) -> str:
    if item.unit == "":
        return item.label
    if item.unit == "scale":
        return "mm/px"
    return f"{item.label}({_item_unit(item, context, 'row')})"


def _format_value(value: Any, decimals: int | None) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value if decimals is None else _format_numeric_value(value, decimals)
    try:
        numeric_value = float(value)
    except TypeError, ValueError:
        return str(value)
    if not math.isfinite(numeric_value):
        return ""
    if decimals is None:
        return str(value)
    return f"{numeric_value:.{decimals}f}"


def _format_numeric_value(value: str, decimals: int) -> str:
    """Format a numeric string while keeping non-finite values out of TSV."""
    try:
        numeric_value = float(value)
    except ValueError:
        return value
    if not math.isfinite(numeric_value):
        return ""
    return f"{numeric_value:.{decimals}f}"


def _sanitize_cell(value: str, *, protect_formula: bool = False) -> str:
    """Keep one TSV cell and optionally neutralize spreadsheet formulas."""
    sanitized = value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
    if protect_formula and sanitized.startswith(("=", "+", "-", "@")):
        return "'" + sanitized
    return sanitized


def build_tsv_row(info: Info, include_header: bool = False) -> str:
    """Format analysis result into a single tab-separated line for Excel."""
    context = _OutputContext(info)
    items = [item for item in TSV_ITEMS if _include(item, context, "row")]
    lines: list[str] = []
    if include_header:
        headers = [_row_header(item, context) for item in items]
        lines.append("\t".join(_sanitize_cell(value) for value in headers))
    values = [
        _sanitize_cell(
            _format_value(_item_value(item, context), item.decimals),
            protect_formula=item.source == "image_name",
        )
        for item in items
    ]
    lines.append("\t".join(values))
    return "\n".join(lines)


def build_tsv_table(info: Info) -> str:
    """Format analysis result into vertical tab-separated table rows for Excel."""
    context = _OutputContext(info)
    rows = [("項目", "値", "単位")]
    for item in TSV_ITEMS:
        if not _include(item, context, "table"):
            continue
        value = _sanitize_cell(
            _format_value(_item_value(item, context), item.decimals),
            protect_formula=item.source == "image_name",
        )
        unit = _item_unit(item, context, "table")
        rows.append((item.label, value, unit))
    return "\n".join(
        "\t".join(_sanitize_cell(str(cell)) for cell in row).rstrip() for row in rows
    )


__all__ = [
    "GUIArgumentParser",
    "Info",
    "Result",
    "TSVItem",
    "TSV_ITEMS",
    "build_tsv_row",
    "build_tsv_table",
    "pixel_distance",
]
