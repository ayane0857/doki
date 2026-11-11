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


IMAGE_TYPES = ["bmp", "jpeg", "jpg", "png", "tif", "tiff", "webp"]

st.set_page_config(page_title="土器体積推定", page_icon="🏺", layout="wide")
st.markdown(
    """
    <style>
    .block-container { max-width: 1180px; padding-top: 2rem; }
    [data-testid="stMetric"] { background: #f5f1e8; border: 1px solid #ded5c4;
        border-radius: 6px; padding: 0.8rem; }
    [data-testid="stFileUploader"] section { border: 1px dashed #9b8d78; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("土器体積推定")
st.caption("土器実測図を確認し、GUI版と同じ設定で容量と器壁体積を推定します。")

uploaded = st.file_uploader(
    "入力画像（PNG / JPEG / TIFF など）",
    type=IMAGE_TYPES,
    help="GUI版の「入力画像」に相当します。アップロード後、下のプレビューで画像を確認できます。",
)

if uploaded is not None:
    st.image(uploaded, caption=f"入力画像: {uploaded.name}", use_container_width=True)

with st.form("analysis_form"):
    st.subheader("スケール")
    scale_mode = st.selectbox(
        "指定方法",
        (
            "px（スケール未指定）",
            "mm/px を直接指定",
            "スケール線の px と mm",
            "2点座標と既知 mm",
            "器高から換算",
        ),
        help="実寸換算する場合は、GUI版と同じ5方式から選びます。未指定ならpx単位で出力します。",
    )
    scale_mm_per_px = 0.0
    scale_bar_px = 0.0
    scale_bar_mm = 0.0
    scale_points = ""
    vessel_height_mm = 0.0

    if scale_mode == "mm/px を直接指定":
        scale_mm_per_px = st.number_input(
            "mm/px", min_value=0.0, value=0.0, step=0.01, format="%.8f"
        )
    elif scale_mode == "スケール線の px と mm":
        bar_px_col, bar_mm_col = st.columns(2)
        with bar_px_col:
            scale_bar_px = st.number_input(
                "スケール線の画像上の長さ (px)", min_value=0.0, value=0.0, step=1.0
            )
        with bar_mm_col:
            scale_bar_mm = st.number_input(
                "スケール線の実寸 (mm)", min_value=0.0, value=0.0, step=1.0
            )
    elif scale_mode == "2点座標と既知 mm":
        scale_points = st.text_input(
            "2点の座標 x0,y0,x1,y1 (px)",
            placeholder="例: 40,20,140,20",
            help="画像プレビューを見ながら、既知長の両端を入力します。",
        )
        scale_bar_mm = st.number_input(
            "2点間の実寸 (mm)", min_value=0.0, value=0.0, step=1.0
        )
    elif scale_mode == "器高から換算":
        vessel_height_mm = st.number_input(
            "器高の実寸 (mm)", min_value=0.0, value=0.0, step=1.0
        )

    st.divider()
    st.subheader("自動検出の調整")
    st.caption("空欄の項目は自動検出に任せます。GUI版の「必要な場合のみ」の設定です。")
    detection_col1, detection_col2 = st.columns(2)
    with detection_col1:
        axis_x_text = st.text_input("回転軸 x (px)", placeholder="空欄なら自動検出")
        crop_text = st.text_input(
            "断面 crop x0,y0,x1,y1", placeholder="空欄なら画像全体"
        )
        liquid_level_text = st.text_input(
            "液面 y (px)", placeholder="空欄なら口縁"
        )
        min_component_area = st.number_input(
            "最小連結成分面積 (px)", min_value=1, value=5, step=1
        )
    with detection_col2:
        closing_kernel = st.number_input(
            "クロージングカーネル (px)", min_value=1, value=3, step=2
        )
        smooth_window = st.number_input(
            "平滑化窓 (奇数、0で無効)", min_value=0, value=5, step=2
        )
        profile_mode = st.selectbox(
            "断面抽出方式", ("auto", "filled", "lines")
        )
        adaptive_threshold = st.checkbox("適応的二値化を使う")

    st.divider()
    st.subheader("出力")
    save_debug = st.checkbox(
        "デバッグ画像を表示する", value=True,
        help="検出重ね合わせ、断面マスク、輪郭グラフを解析結果の下に表示します。",
    )
    submitted = st.form_submit_button("計算する", type="primary", use_container_width=True)


def add_optional_argument(arguments: list[str], option: str, value: str) -> None:
    if value.strip():
        arguments.extend((option, value.strip()))


if submitted:
    if uploaded is None:
        st.error("画像を選ぶか、画像ファイルをアップロードしてください。")
    else:
        suffix = Path(uploaded.name).suffix.lower() or ".png"
        try:
            with tempfile.TemporaryDirectory(prefix="pottery-volume-web-") as directory:
                image_path = Path(directory) / f"input{suffix}"
                image_path.write_bytes(uploaded.getvalue())
                arguments = [str(image_path)]

                if scale_mode == "mm/px を直接指定":
                    arguments.extend(("--scale-mm-per-px", str(scale_mm_per_px)))
                elif scale_mode == "スケール線の px と mm":
                    arguments.extend(
                        (
                            "--scale-bar-px",
                            str(scale_bar_px),
                            "--scale-bar-mm",
                            str(scale_bar_mm),
                        )
                    )
                elif scale_mode == "2点座標と既知 mm":
                    arguments.extend(
                        (
                            "--scale-points",
                            scale_points,
                            "--scale-bar-mm",
                            str(scale_bar_mm),
                        )
                    )
                elif scale_mode == "器高から換算":
                    arguments.extend(("--vessel-height-mm", str(vessel_height_mm)))

                add_optional_argument(arguments, "--axis-x", axis_x_text)
                add_optional_argument(arguments, "--crop", crop_text)
                add_optional_argument(arguments, "--liquid-level-y", liquid_level_text)
                arguments.extend(
                    (
                        "--closing-kernel",
                        str(int(closing_kernel)),
                        "--min-component-area",
                        str(int(min_component_area)),
                        "--smooth-window",
                        str(int(smooth_window)),
                        "--profile-mode",
                        profile_mode,
                    )
                )
                if adaptive_threshold:
                    arguments.append("--adaptive-threshold")

                if save_debug:
                    debug_dir = Path(directory) / "debug_out"
                    arguments.extend(("--debug-dir", str(debug_dir)))

                _, result, section_mode, warnings = analyze(arguments)
                result_json = json.dumps(result, ensure_ascii=False, indent=2)

                st.success("解析が完了しました。")
                st.subheader("推定結果")
                unit = result["units"]["length"]
                volume_unit = result["units"]["volume"]
                metrics = (
                    (f"器高 ({unit})", result["vessel_height"]),
                    (f"口径 ({unit})", result["mouth_diameter"]),
                    (f"最大径 ({unit})", result["maximum_diameter"]),
                    (f"容量 ({volume_unit})", result["capacity"]),
                    (f"器壁体積 ({volume_unit})", result["wall_volume"]),
                    ("パップス検算との差", result["pappus_difference_percent"]),
                )
                metric_columns = st.columns(3)
                for index, (label, value) in enumerate(metrics):
                    suffix_text = "%" if label == "パップス検算との差" else ""
                    metric_columns[index % 3].metric(
                        label, f"{value:.2f}{suffix_text}"
                    )

                if "capacity_ml" in result:
                    st.info(
                        f"容量: {result['capacity_ml']:.2f} mL / "
                        f"器壁体積: {result['wall_volume_ml']:.2f} mL"
                    )
                st.caption(f"断面抽出モード: {section_mode}")
                if warnings:
                    st.warning("\n".join(f"- {warning}" for warning in warnings))

                st.download_button(
                    "JSONをダウンロード",
                    data=result_json,
                    file_name="pottery_volume_result.json",
                    mime="application/json",
                )
                with st.expander("解析結果JSON"):
                    st.code(result_json, language="json")

                if save_debug:
                    st.subheader("デバッグ画像")
                    debug_images = {
                        "検出結果": "detection_overlay.png",
                        "断面マスク": "section_mask.png",
                        "輪郭プロファイル": "profiles.png",
                    }
                    debug_columns = st.columns(len(debug_images))
                    for column, (caption, filename) in zip(
                        debug_columns, debug_images.items()
                    ):
                        debug_path = debug_dir / filename
                        if debug_path.exists():
                            column.image(
                                str(debug_path),
                                caption=caption,
                                use_container_width=True,
                            )
        except (ValueError, OSError, cv2.error, SystemExit) as exc:
            st.error(f"画像の解析に失敗しました: {exc}")
