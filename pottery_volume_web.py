"""Streamlit interface for pottery volume estimation.

Run with ``streamlit run pottery_volume_web.py``.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import streamlit as st

from pottery_volume_cli import analyze


st.set_page_config(page_title="土器体積推定", page_icon="🏺", layout="centered")
st.title("土器体積推定")
st.caption("画像をアップロードし、必要ならスケールや検出設定を指定してください。")


uploaded = st.file_uploader(
    "入力画像",
    type=["bmp", "jpeg", "jpg", "png", "tif", "tiff", "webp"],
)

with st.form("analysis_form"):
    scale_mode = st.radio(
        "スケール指定",
        ("指定なし", "mm/pxを直接指定", "スケール線から指定"),
        horizontal=True,
    )
    if scale_mode == "mm/pxを直接指定":
        scale_mm_per_px = st.number_input(
            "mm/px", min_value=0.0, value=0.0, step=0.01, format="%.6f"
        )
    else:
        scale_mm_per_px = 0.0
    if scale_mode == "スケール線から指定":
        scale_bar_px = st.number_input(
            "スケール線の画像上の長さ (px)",
            min_value=0.0,
            value=0.0,
            step=1.0,
        )
        scale_bar_mm = st.number_input(
            "スケール線の実寸 (mm)",
            min_value=0.0,
            value=0.0,
            step=1.0,
        )
    else:
        scale_bar_px = scale_bar_mm = 0.0

    col1, col2 = st.columns(2)
    with col1:
        axis_x = st.number_input("回転軸 x (px、任意)", value=0.0, step=1.0)
        liquid_level_y = st.number_input("液面 y (px、任意)", value=0.0, step=1.0)
        closing_kernel = st.number_input(
            "クロージングカーネル", min_value=1, value=3, step=2
        )
    with col2:
        profile_mode = st.selectbox("断面抽出方式", ("auto", "filled", "lines"))
        smooth_window = st.number_input(
            "平滑化窓（0で無効）", min_value=0, value=5, step=2
        )
        adaptive_threshold = st.checkbox("適応的二値化を強制")

    submitted = st.form_submit_button("計算する", type="primary")


if submitted:
    if uploaded is None:
        st.error("画像ファイルを選択してください。")
    else:
        suffix = Path(uploaded.name).suffix.lower() or ".png"
        try:
            with tempfile.TemporaryDirectory(prefix="pottery-volume-web-") as directory:
                image_path = Path(directory) / f"input{suffix}"
                image_path.write_bytes(uploaded.getvalue())

                arguments = [str(image_path)]
                if scale_mm_per_px > 0:
                    arguments.extend(("--scale-mm-per-px", str(scale_mm_per_px)))
                elif scale_bar_px > 0 or scale_bar_mm > 0:
                    arguments.extend(
                        (
                            "--scale-bar-px",
                            str(scale_bar_px),
                            "--scale-bar-mm",
                            str(scale_bar_mm),
                        )
                    )
                if axis_x != 0:
                    arguments.extend(("--axis-x", str(axis_x)))
                if liquid_level_y != 0:
                    arguments.extend(("--liquid-level-y", str(liquid_level_y)))
                arguments.extend(
                    (
                        "--closing-kernel",
                        str(int(closing_kernel)),
                        "--smooth-window",
                        str(int(smooth_window)),
                        "--profile-mode",
                        profile_mode,
                    )
                )
                if adaptive_threshold:
                    arguments.append("--adaptive-threshold")

                _, result, _, warnings = analyze(arguments)
        except (ValueError, OSError, cv2.error) as exc:
            st.error(f"画像の解析に失敗しました: {exc}")
        else:
            st.success("解析が完了しました。")
            unit = result["units"]["length"]
            volume_unit = result["units"]["volume"]
            metrics = {
                f"器高 ({unit})": result["vessel_height"],
                f"口径 ({unit})": result["mouth_diameter"],
                f"最大径 ({unit})": result["maximum_diameter"],
                f"容量 ({volume_unit})": result["capacity"],
                f"器壁体積 ({volume_unit})": result["wall_volume"],
            }
            columns = st.columns(len(metrics))
            for column, (label, value) in zip(columns, metrics.items()):
                column.metric(label, f"{value:.2f}")

            if "capacity_ml" in result:
                st.info(
                    f"容量: {result['capacity_ml']:.2f} mL / "
                    f"器壁体積: {result['wall_volume_ml']:.2f} mL"
                )
            if warnings:
                st.warning("\n".join(f"- {warning}" for warning in warnings))
            with st.expander("解析結果JSON"):
                st.code(json.dumps(result, ensure_ascii=False, indent=2), language="json")
