"""TSV formatting and spreadsheet safety tests."""

from __future__ import annotations

import math

import pytest

from doki.analysis.geometry import pixel_distance
from doki.gui.helpers import (
    GUIArgumentParser,
    _format_value,
    build_tsv_row,
    build_tsv_table,
)
from doki.gui.helpers import (
    pixel_distance as helper_pixel_distance,
)


def _info(image_name: str, *, scaled: bool = True) -> dict[str, object]:
    result: dict[str, object] = {
        "units": {"length": "mm" if scaled else "px", "volume": "mm3" if scaled else "px3"},
        "vessel_height": 10.0,
        "mouth_diameter": 4.0,
        "maximum_diameter": 6.0,
        "capacity": 20.0,
        "wall_volume": -3.0,
        "pappus_wall_volume": 3.1,
        "pappus_difference_percent": 3.3,
        "mm_per_px": 0.25 if scaled else None,
    }
    if scaled:
        result.update(
            {
                "capacity_ml": 0.02,
                "capacity_cm3": 0.02,
                "wall_volume_ml": -0.003,
                "wall_volume_cm3": -0.003,
                "pappus_wall_volume_ml": 0.0031,
            }
        )
    return {"image_name": image_name, "result": result}


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@"])
def test_filename_formula_prefix_is_neutralized_in_row_and_table(prefix: str) -> None:
    info = _info(f"{prefix}1+1.png")

    row = build_tsv_row(info)
    table = build_tsv_table(info)

    assert row.split("\t", maxsplit=1)[0] == f"'{prefix}1+1.png"
    assert table.splitlines()[1].split("\t")[1] == f"'{prefix}1+1.png"
    assert row.split("\t")[5] == "-0.00"


def test_filename_tabs_and_newlines_are_sanitized_before_formula_prefix() -> None:
    info = _info("=1\t+2\r\n@3.png")

    row = build_tsv_row(info)
    table = build_tsv_table(info)

    assert row.split("\t", maxsplit=1)[0] == "'=1 +2  @3.png"
    assert table.splitlines()[1].split("\t")[1] == "'=1 +2  @3.png"
    assert len(row.split("\t")) == 10


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numeric_values_are_blank(value: float) -> None:
    assert _format_value(value, 2) == ""


def test_non_finite_tsv_values_are_blank_and_pixel_scale_is_omitted() -> None:
    info = _info("vessel.png", scaled=False)
    result = info["result"]
    assert isinstance(result, dict)
    result["capacity"] = math.nan
    result["pappus_wall_volume"] = math.inf

    row = build_tsv_row(info)
    table = build_tsv_table(info)

    assert row.split("\t")[4] == ""
    assert row.split("\t")[7] == ""
    assert len(row.split("\t")) == 9
    assert all("mm/px" not in line for line in table.splitlines())
    assert table.splitlines()[5].split("\t")[1] == ""
    assert table.splitlines()[8].split("\t")[1] == ""


def test_explicit_none_scale_keeps_pixel_units_even_with_scaled_legacy_keys() -> None:
    info = _info("vessel.png", scaled=True)
    result = info["result"]
    assert isinstance(result, dict)
    result["units"] = {"length": "px", "volume": "px3"}
    result["mm_per_px"] = None

    row = build_tsv_row(info, include_header=True)
    table = build_tsv_table(info)

    header, values = row.splitlines()
    assert header.split("\t")[4].endswith("(px3)")
    assert "mm/px" not in header
    assert values.split("\t")[4] == "20.00"
    assert "20.00\tpx3" in table
    assert "mL" not in table


def test_pixel_distance_keeps_legacy_helper_import_path() -> None:
    assert helper_pixel_distance is pixel_distance
    assert pixel_distance((1.0, 2.0), (4.0, 6.0)) == 5.0


def test_gui_argument_parser_warns_but_remains_usable() -> None:
    with pytest.warns(DeprecationWarning, match="GUIArgumentParser"):
        parser = GUIArgumentParser()

    with pytest.raises(ValueError):
        parser.error("bad arguments")
