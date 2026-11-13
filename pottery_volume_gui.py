"""Tkinter GUI for pottery volume estimation."""

from __future__ import annotations

import ctypes
import math
import sys
from pathlib import Path
from typing import Callable

from pottery_scale import classify_pottery_and_scale, extract_scale_from_image
from pottery_volume_cli import analyze
from pottery_volume_core import read_image


def pixel_distance(point_a: tuple[float, float], point_b: tuple[float, float]) -> float:
    """Return the distance between two image points in pixels."""
    distance = math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
    if not math.isfinite(distance):
        raise ValueError("2点間の距離を計算できません。")
    return distance


def build_tsv_row(info: dict[str, object], include_header: bool = False) -> str:
    """Format analysis result into a single tab-separated line for Excel."""
    res = info["result"]  # type: ignore[index]
    image_name = str(info["image_name"])
    length_unit = str(res["units"]["length"])
    volume_unit = str(res["units"]["volume"])
    is_mm = "capacity_ml" in res
    if is_mm and volume_unit in {"mm3", "mm³"}:
        volume_unit = "mL"

    headers = [
        "タイトル",
        "画像ファイル",
        f"器高({length_unit})",
        f"口径({length_unit})",
        f"最大径({length_unit})",
        f"内腔容量({volume_unit})",
        f"器壁体積({volume_unit})",
        f"全外形体積({volume_unit})",
        f"パップス検算({volume_unit})",
        "パップス差(%)",
    ]
    if is_mm:
        headers.append("mm/px")

    vessel_height = f"{res['vessel_height']:.2f}"
    mouth_dia = f"{res['mouth_diameter']:.2f}"
    max_dia = f"{res['maximum_diameter']:.2f}"

    if is_mm:
        cap = f"{res['capacity_ml']:.2f}"
        wall = f"{res['wall_volume_ml']:.2f}"
        total = f"{res['capacity_ml'] + res['wall_volume_ml']:.2f}"
        pappus = f"{res['pappus_wall_volume_ml']:.2f}"
        diff = f"{res['pappus_difference_percent']:.2f}"
        scale_val = (
            f"{res.get('scale_mm_per_px', 0.0):.4f}"
            if res.get("scale_mm_per_px")
            else ""
        )
        data = [
            str(info.get("title", "")),
            image_name,
            vessel_height,
            mouth_dia,
            max_dia,
            cap,
            wall,
            total,
            pappus,
            diff,
            scale_val,
        ]
    else:
        cap = f"{res['capacity']:.2f}"
        wall = f"{res['wall_volume']:.2f}"
        total = f"{res['capacity'] + res['wall_volume']:.2f}"
        pappus = f"{res['pappus_wall_volume']:.2f}"
        diff = f"{res['pappus_difference_percent']:.2f}"
        data = [
            str(info.get("title", "")),
            image_name,
            vessel_height,
            mouth_dia,
            max_dia,
            cap,
            wall,
            total,
            pappus,
            diff,
        ]

    lines: list[str] = []
    if include_header:
        lines.append("\t".join(headers))
    lines.append("\t".join(data))
    return "\n".join(lines)


def build_tsv_table(info: dict[str, object]) -> str:
    """Format analysis result into vertical tab-separated table rows for Excel."""
    res = info["result"]  # type: ignore[index]
    image_name = str(info["image_name"])
    length_unit = str(res["units"]["length"])
    volume_unit = str(res["units"]["volume"])
    is_mm = "capacity_ml" in res

    rows = [
        ("項目", "値", "単位"),
        ("タイトル", str(info.get("title", "")), ""),
        ("画像ファイル", image_name, ""),
        ("器高", f"{res['vessel_height']:.2f}", length_unit),
        ("口径", f"{res['mouth_diameter']:.2f}", length_unit),
        ("最大径", f"{res['maximum_diameter']:.2f}", length_unit),
    ]
    if is_mm:
        rows.extend(
            [
                ("内腔容量", f"{res['capacity_ml']:.2f}", "mL"),
                ("内腔容量(cm³)", f"{res['capacity_cm3']:.2f}", "cm³"),
                ("器壁体積", f"{res['wall_volume_ml']:.2f}", "mL"),
                (
                    "全外形体積",
                    f"{res['capacity_ml'] + res['wall_volume_ml']:.2f}",
                    "mL",
                ),
                ("パップス検算", f"{res['pappus_wall_volume_ml']:.2f}", "mL"),
                ("パップス差", f"{res['pappus_difference_percent']:.2f}", "%"),
            ]
        )
        if res.get("scale_mm_per_px"):
            rows.append(("スケール", f"{res['scale_mm_per_px']:.4f}", "mm/px"))
    else:
        rows.extend(
            [
                ("内腔容量", f"{res['capacity']:.2f}", volume_unit),
                ("器壁体積", f"{res['wall_volume']:.2f}", volume_unit),
                (
                    "全外形体積",
                    f"{res['capacity'] + res['wall_volume']:.2f}",
                    volume_unit,
                ),
                ("パップス検算", f"{res['pappus_wall_volume']:.2f}", volume_unit),
                ("パップス差", f"{res['pappus_difference_percent']:.2f}", "%"),
            ]
        )
    return "\n".join(f"{c1}\t{c2}\t{c3}".rstrip() for c1, c2, c3 in rows)


def _enable_windows_file_drop(
    root: object, on_drop: Callable[[list[str]], None]
) -> None:
    """Enable Explorer file drops on the Tk top-level window on Windows."""
    if sys.platform != "win32":
        return

    from ctypes import wintypes

    user32 = ctypes.windll.user32
    shell32 = ctypes.windll.shell32
    hwnd = int(root.winfo_id())  # type: ignore[attr-defined]
    wm_dropfiles = 0x0233
    gwlp_wndproc = -4
    lresult_type = getattr(wintypes, "LRESULT", ctypes.c_ssize_t)
    wnd_proc_type = ctypes.WINFUNCTYPE(
        lresult_type,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )
    call_window_proc = user32.CallWindowProcW
    call_window_proc.argtypes = [
        ctypes.c_void_p,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    ]
    call_window_proc.restype = lresult_type
    drag_query_file = shell32.DragQueryFileW
    drag_query_file.argtypes = [
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.LPWSTR,
        wintypes.UINT,
    ]
    drag_query_file.restype = wintypes.UINT

    old_proc = ctypes.c_void_p()

    @wnd_proc_type
    def window_proc(
        window: wintypes.HWND,
        message: wintypes.UINT,
        wparam: wintypes.WPARAM,
        lparam: wintypes.LPARAM,
    ) -> int:
        if message == wm_dropfiles:
            handle = wintypes.HANDLE(wparam)
            paths: list[str] = []
            count = drag_query_file(handle, 0xFFFFFFFF, None, 0)
            for index in range(count):
                length = drag_query_file(handle, index, None, 0)
                buffer = ctypes.create_unicode_buffer(length + 1)
                drag_query_file(handle, index, buffer, length + 1)
                paths.append(buffer.value)
            shell32.DragFinish(handle)
            on_drop(paths)
            return 0
        return call_window_proc(old_proc, window, message, wparam, lparam)

    user32.SetWindowLongPtrW.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_void_p,
    ]
    user32.SetWindowLongPtrW.restype = ctypes.c_void_p
    old_proc.value = user32.SetWindowLongPtrW(
        hwnd, gwlp_wndproc, ctypes.cast(window_proc, ctypes.c_void_p)
    )
    shell32.DragAcceptFiles(hwnd, True)
    # Keep the callback and original procedure alive for as long as Tk can receive messages.
    root._file_drop_callback = window_proc  # type: ignore[attr-defined]
    root._file_drop_original_proc = old_proc  # type: ignore[attr-defined]


def launch_gui(initial_image: str | Path | None = None) -> None:
    """Open a desktop interface for selecting an image and estimating pottery volume."""
    import contextlib
    import io
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    available_fonts = set(tkfont.families(root))
    preferred_fonts = (
        "BIZ UDPゴシック",
        "BIZ UDGothic",
        "Yu Gothic UI",
        "Meiryo UI",
        "UD デジタル 教科書体 NP-R",
        "UD デジタル 教科書体 N-R",
        "Hiragino Sans",
    )
    default_font = tkfont.nametofont("TkDefaultFont").cget("family")
    ui_font = next(
        (name for name in preferred_fonts if name in available_fonts), default_font
    )

    root.option_add("*Font", (ui_font, 10))
    style = ttk.Style(root)

    # Use Tk system colors so text follows Windows themes, including high contrast.
    BG_APP = root.cget("background")
    BG_CARD = BG_APP
    BG_SUBTLE = BG_APP
    BG_BANNER_INFO = BG_APP
    BORDER_COLOR = "#A0A0A0"

    def color_luminance(color: str) -> float | None:
        try:
            red, green, blue = (
                channel / 65535
                for channel in root.winfo_rgb(color)
            )
        except tk.TclError:
            return None

        def linearize(channel: float) -> float:
            return (
                channel / 12.92
                if channel <= 0.04045
                else ((channel + 0.055) / 1.055) ** 2.4
            )

        return (
            0.2126 * linearize(red)
            + 0.7152 * linearize(green)
            + 0.0722 * linearize(blue)
        )

    background_luminance = color_luminance(BG_APP)
    label_foreground = (
        style.lookup("TLabel", "foreground")
        or root.option_get("foreground", "")
        or ("SystemWindowText" if sys.platform == "win32" else "black")
    )
    foreground_luminance = color_luminance(label_foreground)

    def contrast_ratio(first: float | None, second: float | None) -> float:
        if first is None or second is None:
            return 0.0
        return (max(first, second) + 0.05) / (min(first, second) + 0.05)

    if background_luminance is None or foreground_luminance is None:
        SYSTEM_TEXT = label_foreground
    else:
        contrast = contrast_ratio(background_luminance, foreground_luminance)
        if contrast < 4.5:
            candidates = ("#000000", "#FFFFFF")
            SYSTEM_TEXT = max(
                candidates,
                key=lambda color: contrast_ratio(
                    color_luminance(color), background_luminance
                ),
            )
        else:
            SYSTEM_TEXT = label_foreground
    TEXT_PRIMARY = SYSTEM_TEXT
    TEXT_SECONDARY = SYSTEM_TEXT
    TEXT_MUTED = SYSTEM_TEXT
    ACCENT_PRIMARY = TEXT_PRIMARY

    root.title("土器体積・容量推定ツール")
    root.geometry("1120x740")
    root.minsize(920, 620)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(1, weight=1)

    style.configure(".", font=(ui_font, 10))
    style.configure("Muted.TLabel", foreground=TEXT_MUTED, font=(ui_font, 9))
    style.configure("SectionTitle.TLabel", font=(ui_font, 10, "bold"))
    style.configure("Subtle.TLabel", font=(ui_font, 9))
    style.configure("Subtle.TButton", font=(ui_font, 9))
    style.configure("Primary.TButton", padding=(16, 8), font=(ui_font, 10, "bold"))
    style.configure("Treeview", rowheight=26, font=(ui_font, 10))
    style.configure("Treeview.Heading", font=(ui_font, 10, "bold"))

    # State Variables
    image_var = tk.StringVar(value=str(initial_image or ""))
    measurement_title_var = tk.StringVar()
    scale_image_var = tk.StringVar()
    drop_status_var = tk.StringVar(
        value="土器実測図と目盛りの2枚をウィンドウへドラッグ＆ドロップすると、自動判別してスケールを設定します。"
    )
    scale_mode_var = tk.StringVar(value="px（スケール未指定）")
    direct_scale_var = tk.StringVar()
    bar_px_var = tk.StringVar()
    known_mm_var = tk.StringVar()
    points_var = tk.StringVar()
    vessel_height_var = tk.StringVar()
    axis_var = tk.StringVar()
    crop_var = tk.StringVar()
    liquid_var = tk.StringVar()
    kernel_var = tk.StringVar(value="3")
    min_area_var = tk.StringVar(value="5")
    smooth_var = tk.StringVar(value="5")
    profile_mode_var = tk.StringVar(value="auto")
    json_var = tk.StringVar()
    debug_var = tk.StringVar()
    save_debug_var = tk.BooleanVar(value=False)
    adaptive_var = tk.BooleanVar(value=False)
    advanced_open_var = tk.BooleanVar(value=False)

    # KPI & Metrics Display Variables
    kpi_capacity_var = tk.StringVar(value="—")
    kpi_capacity_unit_var = tk.StringVar(value="")
    kpi_wall_var = tk.StringVar(value="—")
    kpi_wall_unit_var = tk.StringVar(value="")
    metric_height_var = tk.StringVar(value="—")
    metric_mouth_var = tk.StringVar(value="—")
    metric_max_dia_var = tk.StringVar(value="—")
    metric_total_vol_var = tk.StringVar(value="—")
    metric_pappus_var = tk.StringVar(value="—")
    metric_scale_var = tk.StringVar(value="未指定 (px)")
    auto_scale_generation = 0
    drop_generation = 0
    title_is_automatic = True
    updating_automatic_title = False

    def make_card(parent: tk.Widget, **grid_kwargs: object) -> tk.Frame:
        card = tk.Frame(
            parent,
            background=BG_CARD,
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
            padx=14,
            pady=12,
        )
        card.grid(**grid_kwargs)
        return card

    # --- Top Header & Status Banner ---
    header_bar = ttk.Frame(root, style="App.TFrame", padding=(16, 12, 16, 4))
    header_bar.grid(row=0, column=0, sticky="ew")
    header_bar.columnconfigure(1, weight=1)

    title_box = ttk.Frame(header_bar, style="App.TFrame")
    title_box.grid(row=0, column=0, sticky="w")
    tk.Label(
        title_box,
        text="土器体積・容量推定",
        font=(ui_font, 15, "bold"),
        background=BG_APP,
        foreground=TEXT_PRIMARY,
    ).pack(side="left")

    status_banner = tk.Frame(
        header_bar,
        background=BG_APP,
        highlightbackground=BORDER_COLOR,
        highlightthickness=1,
        padx=10,
        pady=6,
    )
    status_banner.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    drop_status_label = tk.Label(
        status_banner,
        textvariable=drop_status_var,
        font=(ui_font, 10),
        background=BG_APP,
        foreground=TEXT_PRIMARY,
        anchor="w",
        justify="left",
    )
    drop_status_label.pack(side="left", fill="x", expand=True)

    def set_status(message: str, level: str = "info") -> None:
        drop_status_var.set(message.replace("\n", " "))

    def set_automatic_title(title: str) -> None:
        nonlocal updating_automatic_title, title_is_automatic
        updating_automatic_title = True
        measurement_title_var.set(title)
        updating_automatic_title = False
        title_is_automatic = True

    def on_title_changed(*_args: object) -> None:
        nonlocal title_is_automatic
        if not updating_automatic_title:
            title_is_automatic = False

    measurement_title_var.trace_add("write", on_title_changed)

    # --- Main Two-Column Workspace ---
    workspace = ttk.Frame(root, style="App.TFrame", padding=(16, 8, 16, 14))
    workspace.grid(row=1, column=0, sticky="nsew")
    workspace.columnconfigure(0, weight=11, uniform="pane")
    workspace.columnconfigure(1, weight=10, uniform="pane")
    workspace.rowconfigure(0, weight=1)

    # Left Column (Inputs & Controls)
    left_pane = ttk.Frame(workspace, style="App.TFrame")
    left_pane.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
    left_pane.columnconfigure(0, weight=1)
    left_pane.rowconfigure(3, weight=1)

    # Right Column (Results & Export)
    right_pane = ttk.Frame(workspace, style="App.TFrame")
    right_pane.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    right_pane.columnconfigure(0, weight=1)
    right_pane.rowconfigure(0, weight=1)

    # =========================================================================
    # STEP 1: Image Selection Card
    # =========================================================================
    file_card = make_card(left_pane, row=0, column=0, sticky="ew", pady=(0, 10))
    file_card.columnconfigure(1, weight=1)

    step1_header = ttk.Frame(file_card, style="Card.TFrame")
    step1_header.grid(row=0, column=0, columnspan=4, sticky="ew", pady=(0, 8))
    ttk.Label(
        step1_header,
        text="画像の選択（ドラッグ＆ドロップ対応）",
        style="SectionTitle.TLabel",
    ).pack(side="left")

    def browse_image() -> None:
        chosen = filedialog.askopenfilename(
            title="土器実測図を選択",
            filetypes=[
                ("画像ファイル", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if chosen:
            image_var.set(chosen)
            image_path = Path(chosen)
            if not debug_var.get().strip():
                debug_var.set(str(image_path.parent / "debug_out"))
            set_status(f"土器実測図を選択しました: {image_path.name}", "info")

    def preview_selected_image(target_var: tk.StringVar, image_kind: str) -> None:
        image_text = target_var.get().strip().strip('"')
        if not image_text:
            messagebox.showinfo(
                "画像未選択", f"先に{image_kind}を選択してください。", parent=root
            )
            return
        image_path = Path(image_text)
        if not image_path.is_file():
            messagebox.showerror("画像が見つかりません", image_text, parent=root)
            return

        try:
            import base64
            import cv2

            image = read_image(image_path)
            image_height, image_width = image.shape[:2]
            max_width = min(1100, max(320, root.winfo_screenwidth() - 80))
            max_height = min(760, max(240, root.winfo_screenheight() - 160))
            scale = min(1.0, max_width / image_width, max_height / image_height)
            if scale < 1.0:
                image = cv2.resize(
                    image,
                    (
                        max(1, round(image_width * scale)),
                        max(1, round(image_height * scale)),
                    ),
                    interpolation=cv2.INTER_AREA,
                )
            success, encoded = cv2.imencode(".png", image)
            if not success:
                raise ValueError("画像を表示用に変換できません。")
            photo = tk.PhotoImage(data=base64.b64encode(encoded).decode("ascii"))
        except Exception as exc:
            messagebox.showerror("画像を表示できません", str(exc), parent=root)
            return

        window = tk.Toplevel(root)
        window.title(f"{image_kind}の確認 - {image_path.name}")
        window.configure(background=BG_APP)
        window.transient(root)
        frame = ttk.Frame(window, padding=12, style="App.TFrame")
        frame.pack(fill="both", expand=True)
        image_label = tk.Label(
            frame,
            image=photo,
            background="#D0D0D0",
            highlightbackground=BORDER_COLOR,
            highlightthickness=1,
        )
        image_label.image = photo
        image_label.pack()
        ttk.Label(
            frame,
            text=f"{image_path.name}  ({image_width} × {image_height} px)",
            style="App.TLabel",
        ).pack(pady=(8, 4))
        ttk.Button(frame, text="閉じる", command=window.destroy).pack(pady=(4, 0))
        display_width = photo.width()
        display_height = photo.height()
        window.geometry(f"{display_width + 32}x{display_height + 92}")

    ttk.Label(file_card, text="土器実測図").grid(row=1, column=0, sticky="w", pady=4)
    ttk.Entry(file_card, textvariable=image_var).grid(
        row=1, column=1, sticky="ew", padx=(8, 6), pady=4
    )
    ttk.Button(file_card, text="参照…", width=7, command=browse_image).grid(
        row=1, column=2, padx=(0, 4), pady=4
    )
    ttk.Button(
        file_card,
        text="確認",
        width=6,
        style="Subtle.TButton",
        command=lambda: preview_selected_image(image_var, "土器画像"),
    ).grid(row=1, column=3, pady=4)

    def invalidate_auto_scale_request() -> None:
        nonlocal auto_scale_generation
        auto_scale_generation += 1

    def invalidate_drop_request() -> None:
        nonlocal drop_generation
        drop_generation += 1

    def reset_calibration_for_new_pair() -> None:
        invalidate_auto_scale_request()
        scale_mode_var.set("px（スケール未指定）")
        direct_scale_var.set("")
        bar_px_var.set("")
        known_mm_var.set("")
        points_var.set("")

    for calibration_var in (
        scale_image_var,
        scale_mode_var,
        direct_scale_var,
        bar_px_var,
        known_mm_var,
        points_var,
        vessel_height_var,
    ):
        calibration_var.trace_add(
            "write",
            lambda *_args: invalidate_auto_scale_request(),
        )
    for image_selection_var in (image_var, scale_image_var):
        image_selection_var.trace_add(
            "write",
            lambda *_args: invalidate_drop_request(),
        )

    def on_image_changed(*_args: object) -> None:
        image_text = image_var.get().strip().strip('"')
        if title_is_automatic and image_text:
            set_automatic_title(Path(image_text).stem)

    image_var.trace_add("write", on_image_changed)

    def auto_analyze_scale_image(scale_path: Path, prefix_msg: str = "") -> None:
        import threading

        request_generation = auto_scale_generation

        def worker() -> None:
            try:
                scale_img = read_image(scale_path)
                label, bar, mm_per_px = extract_scale_from_image(scale_img)

                def on_done() -> None:
                    if (
                        not root.winfo_exists()
                        or request_generation != auto_scale_generation
                    ):
                        return
                    if label and bar and mm_per_px:
                        scale_mode_var.set("スケール線の px と mm")
                        bar_px_var.set(f"{bar.pixels:.2f}")
                        known_mm_var.set(f"{label.length_mm:g}")
                        info = (
                            f"{prefix_msg}目盛り自動設定: {label.text} ({label.length_mm:g}mm) / "
                            f"{bar.pixels:.1f}px → {mm_per_px:.4f} mm/px"
                        )
                        set_status(info.strip(), "success")
                    elif bar:
                        scale_mode_var.set("スケール線の px と mm")
                        bar_px_var.set(f"{bar.pixels:.2f}")
                        known_mm_var.set("")
                        info = f"{prefix_msg}目盛り線（{bar.pixels:.1f}px）を検出しました。実寸 mm を入力してください。"
                        set_status(info.strip(), "info")
                    else:
                        info = f"{prefix_msg}目盛り画像を読み込みました。「画像上で測定…」等で設定できます。"
                        set_status(info.strip(), "info")

                root.after(0, on_done)
            except Exception as exc:
                error_text = str(exc)

                def on_err(error_text: str = error_text) -> None:
                    if (
                        not root.winfo_exists()
                        or request_generation != auto_scale_generation
                    ):
                        return
                    set_status(
                        f"{prefix_msg}目盛り画像の解析エラー: {error_text}", "warning"
                    )

                root.after(0, on_err)

        threading.Thread(target=worker, daemon=True).start()

    def browse_scale_image() -> None:
        chosen = filedialog.askopenfilename(
            title="目盛り画像を選択",
            filetypes=[
                ("画像ファイル", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                ("すべてのファイル", "*.*"),
            ],
        )
        if chosen:
            reset_calibration_for_new_pair()
            scale_image_var.set(chosen)
            scale_path = Path(chosen)
            set_status(
                f"目盛り画像を選択しました: {scale_path.name}（解析中…）", "info"
            )
            auto_analyze_scale_image(scale_path)

    ttk.Label(file_card, text="目盛り画像").grid(row=2, column=0, sticky="w", pady=4)
    ttk.Entry(file_card, textvariable=scale_image_var).grid(
        row=2, column=1, sticky="ew", padx=(8, 6), pady=4
    )
    ttk.Button(file_card, text="参照…", width=7, command=browse_scale_image).grid(
        row=2, column=2, padx=(0, 4), pady=4
    )
    ttk.Button(
        file_card,
        text="確認",
        width=6,
        style="Subtle.TButton",
        command=lambda: preview_selected_image(scale_image_var, "目盛り画像"),
    ).grid(row=2, column=3, pady=4)

    ttk.Label(
        file_card,
        text="※ 目盛り画像は任意です（実測図内に目盛りがある場合は未指定でOK）",
        style="Muted.TLabel",
    ).grid(row=3, column=0, columnspan=4, sticky="w", pady=(4, 0))

    def handle_dropped_files(paths: list[str]) -> None:
        nonlocal drop_generation
        drop_generation += 1
        request_generation = drop_generation
        valid_paths = [
            Path(p)
            for p in paths
            if Path(p).suffix.lower()
            in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
        ]
        if not valid_paths:
            return

        if len(valid_paths) == 1:
            p = valid_paths[0]
            image_var.set(str(p))
            if not debug_var.get().strip():
                debug_var.set(str(p.parent / "debug_out"))
            set_status(f"土器実測図を読み込みました: {p.name}", "info")
        else:
            import threading

            invalidate_auto_scale_request()
            calibration_generation = auto_scale_generation

            def classify_in_background() -> None:
                try:
                    result = classify_pottery_and_scale(valid_paths[0], valid_paths[1])

                    def on_done() -> None:
                        if (
                            not root.winfo_exists()
                            or request_generation != drop_generation
                        ):
                            return
                        pottery_p, scale_p = result
                        calibration_changed = (
                            calibration_generation != auto_scale_generation
                        )
                        image_var.set(str(pottery_p))
                        scale_image_var.set(str(scale_p))
                        if not debug_var.get().strip():
                            debug_var.set(str(pottery_p.parent / "debug_out"))
                        if calibration_changed:
                            set_status(
                                "画像を判別しました。新しい手動スケール設定を保持しています。",
                                "info",
                            )
                            return
                        reset_calibration_for_new_pair()
                        prefix = (
                            f"土器: {pottery_p.name} / 目盛り: {scale_p.name} を判別 — "
                        )
                        set_status(prefix + "目盛りのスケールを解析中…", "success")
                        auto_analyze_scale_image(scale_p, prefix_msg=prefix)

                    root.after(0, on_done)
                except Exception as exc:
                    error_text = str(exc)

                    def on_err(error_text: str = error_text) -> None:
                        if (
                            not root.winfo_exists()
                            or request_generation != drop_generation
                        ):
                            return
                        p = valid_paths[0]
                        image_var.set(str(p))
                        set_status(
                            f"画像の判別でエラー: {error_text}（{p.name} を土器画像に設定しました）",
                            "error",
                        )

                    root.after(0, on_err)

            threading.Thread(target=classify_in_background, daemon=True).start()

    root.update_idletasks()
    _enable_windows_file_drop(root, handle_dropped_files)

    # =========================================================================
    # STEP 2: Scale Settings Card
    # =========================================================================
    scale_card = make_card(left_pane, row=1, column=0, sticky="ew", pady=(0, 10))
    scale_card.columnconfigure(1, weight=1)

    step2_header = ttk.Frame(scale_card, style="Card.TFrame")
    step2_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    ttk.Label(
        step2_header, text="スケール（実寸換算）設定", style="SectionTitle.TLabel"
    ).pack(side="left")

    ttk.Label(scale_card, text="指定方法").grid(row=1, column=0, sticky="w", pady=4)
    scale_combo = ttk.Combobox(
        scale_card,
        textvariable=scale_mode_var,
        values=(
            "px（スケール未指定）",
            "mm/px を直接指定",
            "スケール線の px と mm",
            "2点座標と既知 mm",
            "器高から換算",
        ),
        state="readonly",
    )
    scale_combo.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=4)

    # Dynamic parameter row
    scale_entries: dict[str, ttk.Frame] = {}
    for key, label_text, variable, hint in (
        ("direct", "mm/px", direct_scale_var, "例: 0.5"),
        ("bar", "線長 (px)", bar_px_var, "px"),
        ("points", "2点座標", points_var, "x0,y0,x1,y1"),
        ("height", "器高 (mm)", vessel_height_var, "例: 120"),
    ):
        row_frame = ttk.Frame(scale_card, style="Card.TFrame")
        row_frame.columnconfigure(1, weight=1)
        ttk.Label(row_frame, text=label_text).grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(row_frame, textvariable=variable, width=16).grid(
            row=0, column=1, sticky="ew", padx=(8, 6), pady=4
        )
        ttk.Label(row_frame, text=hint, style="Muted.TLabel").grid(
            row=0, column=2, sticky="w", padx=(0, 6)
        )
        if key in ("bar", "points"):
            ttk.Label(row_frame, text="実寸 mm").grid(
                row=0, column=3, sticky="w", padx=(6, 4)
            )
            ttk.Entry(row_frame, textvariable=known_mm_var, width=10).grid(
                row=0, column=4, sticky="w", pady=4
            )
        scale_entries[key] = row_frame

    def update_scale_rows(*_args: object) -> None:
        for frame in scale_entries.values():
            if frame.winfo_manager() == "grid":
                frame.grid_remove()
        selected = scale_mode_var.get()
        key = {
            "mm/px を直接指定": "direct",
            "スケール線の px と mm": "bar",
            "2点座標と既知 mm": "points",
            "器高から換算": "height",
        }.get(selected)
        if key:
            scale_entries[key].grid(
                row=2, column=0, columnspan=2, sticky="ew", pady=(2, 0)
            )

    scale_mode_var.trace_add("write", update_scale_rows)
    update_scale_rows()

    def open_measurement_tool() -> None:
        import base64
        import tkinter as tk
        from tkinter import messagebox, ttk

        image_text = scale_image_var.get().strip().strip(
            '"'
        ) or image_var.get().strip().strip('"')
        is_scale_file = bool(scale_image_var.get().strip().strip('"'))
        if not image_text:
            messagebox.showerror(
                "画像が未指定です",
                "先に土器画像または目盛り画像を選択してください。",
                parent=root,
            )
            return
        image_path = Path(image_text)
        if not image_path.is_file():
            messagebox.showerror("画像が見つかりません", image_text, parent=root)
            return

        try:
            import cv2

            image = read_image(image_path)
            image_height, image_width = image.shape[:2]
        except (OSError, ValueError) as exc:
            messagebox.showerror("画像を開けません", str(exc), parent=root)
            return

        window = tk.Toplevel(root)
        target_kind = "目盛り画像" if is_scale_file else "土器画像"
        window.title(f"{target_kind}上でスケールを測定 ({image_path.name})")
        window.geometry("1020x760")
        window.minsize(680, 460)
        window.configure(background=BG_APP)
        window.transient(root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        zoom_pct_var = tk.StringVar(value="100%")
        status_var = tk.StringVar(value="1点目をクリックしてください。")
        distance_var = tk.StringVar(value="—")
        measured_mm_var = tk.StringVar()

        ttk.Label(
            window,
            text="画像上の2点をクリックして距離を測定します（ホイールで拡大縮小・右ドラッグで移動）。",
            style="App.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))

        canvas_frame = ttk.Frame(window, style="App.TFrame")
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=6)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(canvas_frame, background="#D0D0D0", highlightthickness=0)
        x_scroll = ttk.Scrollbar(
            canvas_frame, orient="horizontal", command=canvas.xview
        )
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        measurement_frame = make_card(
            window, row=1, column=1, sticky="ns", padx=(10, 12), pady=6
        )
        measurement_frame.columnconfigure(1, weight=1)

        ttk.Label(
            measurement_frame,
            textvariable=status_var,
            wraplength=220,
            foreground=ACCENT_PRIMARY,
            font=(ui_font, 10, "bold"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))
        ttk.Label(measurement_frame, text="測定距離:").grid(
            row=1, column=0, sticky="w", pady=4
        )
        ttk.Label(
            measurement_frame,
            textvariable=distance_var,
            font=(ui_font, 11, "bold"),
        ).grid(row=1, column=1, sticky="w", padx=6, pady=4)
        ttk.Label(measurement_frame, text="実寸 mm:").grid(
            row=2, column=0, sticky="w", pady=4
        )
        ttk.Entry(measurement_frame, textvariable=measured_mm_var, width=12).grid(
            row=2, column=1, sticky="ew", padx=6, pady=4
        )

        point_a: tuple[float, float] | None = None
        point_b: tuple[float, float] | None = None
        marker_ids: list[int] = []
        display_scale = 1.0
        zoom_scale: float | None = None
        min_zoom_scale = 0.05
        max_rendered_pixels = 16_000_000
        max_zoom_scale = math.sqrt(
            max_rendered_pixels / max(1, image_width * image_height)
        )
        min_zoom_scale = min(min_zoom_scale, max_zoom_scale)
        display_photo: tk.PhotoImage | None = None
        display_image_id = canvas.create_image(0, 0, anchor="nw")
        resize_job: str | None = None

        def display_point(x: float, y: float) -> tuple[float, float]:
            return x * display_scale, y * display_scale

        def image_point(x: float, y: float) -> tuple[float, float]:
            return x / display_scale, y / display_scale

        def refresh_display_image() -> None:
            nonlocal display_scale, display_photo, resize_job
            resize_job = None
            if not window.winfo_exists():
                return
            try:
                available_width = canvas.winfo_width()
                available_height = canvas.winfo_height()
            except tk.TclError:
                return
            if available_width <= 1 or available_height <= 1:
                return
            fit_scale = min(
                1.0,
                available_width / image_width,
                available_height / image_height,
            )
            new_scale = min(
                fit_scale if zoom_scale is None else zoom_scale,
                max_zoom_scale,
            )
            zoom_pct_var.set(f"{round(new_scale * 100)}%")
            if abs(new_scale - display_scale) < 1e-6 and display_photo is not None:
                return
            display_scale = new_scale
            display_width = max(1, round(image_width * display_scale))
            display_height = max(1, round(image_height * display_scale))
            if display_scale == 1.0:
                display_image = image
            else:
                interpolation = (
                    cv2.INTER_LINEAR if display_scale > 1.0 else cv2.INTER_AREA
                )
                display_image = cv2.resize(
                    image, (display_width, display_height), interpolation=interpolation
                )
            success, encoded = cv2.imencode(".png", display_image)
            if not success:
                raise ValueError("画像を表示用に変換できません。")
            display_photo = tk.PhotoImage(
                data=base64.b64encode(encoded).decode("ascii")
            )
            canvas.itemconfigure(display_image_id, image=display_photo)
            canvas.configure(scrollregion=(0, 0, display_width, display_height))
            canvas.image = display_photo
            redraw_markers()

        def set_zoom(scale: float | None) -> None:
            nonlocal zoom_scale
            zoom_scale = None if scale is None else min(scale, max_zoom_scale)
            if scale is None:
                canvas.xview_moveto(0)
                canvas.yview_moveto(0)
            refresh_display_image()

        def zoom_in() -> None:
            if display_scale < max_zoom_scale:
                set_zoom(min(display_scale * 1.25, max_zoom_scale))

        def zoom_out() -> None:
            if display_scale > min_zoom_scale:
                set_zoom(max(display_scale / 1.25, min_zoom_scale))

        def schedule_display_refresh(_event: object | None = None) -> None:
            nonlocal resize_job
            if resize_job is None and window.winfo_exists():
                try:
                    resize_job = window.after_idle(refresh_display_image)
                except tk.TclError:
                    pass

        def redraw_markers() -> None:
            for marker_id in marker_ids:
                canvas.delete(marker_id)
            marker_ids.clear()
            if point_a is not None:
                ax, ay = display_point(point_a[0], point_a[1])
                marker_ids.append(
                    canvas.create_oval(
                        ax - 5, ay - 5, ax + 5, ay + 5, outline="#EF4444", width=2
                    )
                )
            if point_b is not None and point_a is not None:
                ax, ay = display_point(point_a[0], point_a[1])
                bx, by = display_point(point_b[0], point_b[1])
                marker_ids.append(
                    canvas.create_oval(
                        bx - 5, by - 5, bx + 5, by + 5, outline="#EF4444", width=2
                    )
                )
                marker_ids.append(
                    canvas.create_line(ax, ay, bx, by, fill="#EF4444", width=2)
                )

        def clear_points() -> None:
            nonlocal point_a, point_b
            point_a = point_b = None
            redraw_markers()
            distance_var.set("—")
            status_var.set("1点目をクリックしてください。")

        def on_canvas_click(event: object) -> None:
            nonlocal point_a, point_b
            x, y = image_point(
                float(canvas.canvasx(event.x)),  # type: ignore[attr-defined]
                float(canvas.canvasy(event.y)),  # type: ignore[attr-defined]
            )
            if x < 0 or y < 0 or x >= image_width or y >= image_height:
                return
            if point_a is None or point_b is not None:
                point_a = (x, y)
                point_b = None
                redraw_markers()
                distance_var.set("—")
                status_var.set("2点目をクリックしてください。")
                return
            point_b = (x, y)
            redraw_markers()
            distance = pixel_distance(point_a, point_b)
            distance_var.set(f"{distance:.2f} px")
            status_var.set("測定完了。実寸mmを入力して反映してください。")

        def apply_measurement() -> None:
            if point_a is None or point_b is None:
                messagebox.showerror(
                    "測定点が不足しています",
                    "画像上で2点をクリックしてください。",
                    parent=window,
                )
                return
            measured_mm = measured_mm_var.get().strip()
            if not measured_mm:
                messagebox.showerror(
                    "実寸mmが未入力です",
                    "実寸mmを入力するとスケール設定へ反映できます。",
                    parent=window,
                )
                return
            try:
                mm = float(measured_mm)
                distance = pixel_distance(point_a, point_b)
                if not math.isfinite(mm) or mm <= 0 or distance <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror(
                    "実寸mmを確認してください",
                    "実寸mmは正の数値で入力してください。",
                    parent=window,
                )
                return
            points_var.set(
                f"{point_a[0]:.2f},{point_a[1]:.2f},{point_b[0]:.2f},{point_b[1]:.2f}"
            )
            known_mm_var.set(measured_mm)
            scale_mode_var.set("2点座標と既知 mm")
            set_status(
                f"2点測定（{distance:.1f} px = {measured_mm} mm）をスケールへ反映しました。",
                "success",
            )
            close_window()

        def close_window() -> None:
            nonlocal resize_job
            if resize_job is not None:
                try:
                    window.after_cancel(resize_job)
                except tk.TclError:
                    pass
                resize_job = None
            window.destroy()

        zoom_frame = ttk.Frame(measurement_frame, style="Card.TFrame")
        zoom_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(14, 6))
        zoom_header = ttk.Frame(zoom_frame, style="Card.TFrame")
        zoom_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 2))
        ttk.Label(zoom_header, text="表示倍率", style="Muted.TLabel").pack(side="left")
        ttk.Label(
            zoom_header,
            textvariable=zoom_pct_var,
            font=(ui_font, 9, "bold"),
            foreground=ACCENT_PRIMARY,
        ).pack(side="right")

        ttk.Button(
            zoom_frame,
            text="全体 (0)",
            style="Subtle.TButton",
            command=lambda: set_zoom(None),
        ).grid(row=1, column=0, sticky="ew", padx=(0, 2), pady=2)
        ttk.Button(
            zoom_frame,
            text="原寸 (1)",
            style="Subtle.TButton",
            command=lambda: set_zoom(1.0),
        ).grid(row=1, column=1, sticky="ew", padx=(2, 0), pady=2)
        ttk.Button(
            zoom_frame, text="拡大 (+)", style="Subtle.TButton", command=zoom_in
        ).grid(row=2, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(
            zoom_frame, text="縮小 (-)", style="Subtle.TButton", command=zoom_out
        ).grid(row=2, column=1, sticky="ew", padx=(2, 0))
        zoom_frame.columnconfigure(0, weight=1)
        zoom_frame.columnconfigure(1, weight=1)

        ttk.Button(measurement_frame, text="点をリセット", command=clear_points).grid(
            row=6, column=0, columnspan=2, sticky="ew", pady=(12, 4)
        )
        ttk.Button(
            measurement_frame,
            text="スケール設定へ反映",
            style="Primary.TButton",
            command=apply_measurement,
        ).grid(row=7, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(measurement_frame, text="閉じる (Esc)", command=close_window).grid(
            row=8, column=0, columnspan=2, sticky="ew", pady=4
        )

        def on_mousewheel(event: object) -> None:
            delta = getattr(event, "delta", 0)
            num = getattr(event, "num", 0)
            if delta > 0 or num == 4:
                zoom_in()
            elif delta < 0 or num == 5:
                zoom_out()

        def on_pan_start(event: object) -> None:
            canvas.scan_mark(event.x, event.y)

        def on_pan_move(event: object) -> None:
            canvas.scan_dragto(event.x, event.y, gain=1)

        canvas.bind("<Button-1>", on_canvas_click)
        canvas.bind("<MouseWheel>", on_mousewheel)
        canvas.bind("<Button-4>", on_mousewheel)
        canvas.bind("<Button-5>", on_mousewheel)
        canvas.bind("<ButtonPress-2>", on_pan_start)
        canvas.bind("<B2-Motion>", on_pan_move)
        canvas.bind("<ButtonPress-3>", on_pan_start)
        canvas.bind("<B3-Motion>", on_pan_move)
        canvas_frame.bind("<Configure>", schedule_display_refresh)

        window.bind("<plus>", lambda _e: zoom_in())
        window.bind("<KP_Add>", lambda _e: zoom_in())
        window.bind("<minus>", lambda _e: zoom_out())
        window.bind("<KP_Subtract>", lambda _e: zoom_out())
        window.bind("<Key-0>", lambda _e: set_zoom(None))
        window.bind("<Key-1>", lambda _e: set_zoom(1.0))
        window.bind("<Escape>", lambda _e: close_window())

        window.protocol("WM_DELETE_WINDOW", close_window)
        window.update_idletasks()
        refresh_display_image()

    def open_scale_reader() -> None:
        import base64
        import threading
        import tkinter as tk
        from tkinter import messagebox, ttk

        image_text = scale_image_var.get().strip().strip(
            '"'
        ) or image_var.get().strip().strip('"')
        is_scale_file = bool(scale_image_var.get().strip().strip('"'))
        if not image_text:
            messagebox.showerror(
                "画像が未指定です",
                "先に土器画像または目盛り画像を選択してください。",
                parent=root,
            )
            return
        image_path = Path(image_text)
        if not image_path.is_file():
            messagebox.showerror("画像が見つかりません", image_text, parent=root)
            return
        try:
            import cv2

            image = read_image(image_path)
            image_height, image_width = image.shape[:2]
        except (OSError, ValueError) as exc:
            messagebox.showerror("画像を開けません", str(exc), parent=root)
            return

        window = tk.Toplevel(root)
        target_kind = "目盛り画像" if is_scale_file else "土器画像"
        window.title(f"{target_kind}からスケールを読み取る ({image_path.name})")
        window.geometry("1120x760")
        window.minsize(780, 540)
        window.configure(background=BG_APP)
        window.transient(root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(
            window,
            text="OCRで長さと単位を読み取り、目盛り線候補を自動検出します（赤線の両端は画像クリックで手動調整可能）。",
            style="App.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4))

        canvas_frame = ttk.Frame(window, style="App.TFrame")
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=(12, 0), pady=6)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(canvas_frame, background="#D0D0D0", highlightthickness=0)
        x_scroll = ttk.Scrollbar(
            canvas_frame, orient="horizontal", command=canvas.xview
        )
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        panel = make_card(window, row=1, column=1, sticky="ns", padx=(10, 12), pady=6)
        panel.columnconfigure(0, weight=1)
        label_candidates: list[object] = []
        bar_candidates: list[object] = []
        overlay_ids: list[int] = []
        manual_points: list[tuple[float, float]] = []
        display_scale = 1.0
        zoom_scale: float | None = None
        min_zoom_scale = 0.05
        max_rendered_pixels = 16_000_000
        max_zoom_scale = math.sqrt(
            max_rendered_pixels / max(1, image_width * image_height)
        )
        min_zoom_scale = min(min_zoom_scale, max_zoom_scale)
        display_photo: tk.PhotoImage | None = None
        display_image_id = canvas.create_image(0, 0, anchor="nw")
        resize_job: str | None = None
        zoom_pct_var = tk.StringVar(value="100%")
        ocr_summary_var = tk.StringVar(value="OCR読み取り中…")
        label_choice_var = tk.StringVar()
        value_var = tk.StringVar()
        unit_var = tk.StringVar(value="cm")
        bar_choice_var = tk.StringVar()
        bar_length_var = tk.StringVar(value="—")
        scale_result_var = tk.StringVar(value="mm/px: —")
        points_status_var = tk.StringVar(value="自動検出の結果を確認してください。")

        def display_point(x: float, y: float) -> tuple[float, float]:
            return x * display_scale, y * display_scale

        def image_point(x: float, y: float) -> tuple[float, float]:
            return x / display_scale, y / display_scale

        def refresh_display_image() -> None:
            nonlocal display_scale, display_photo, resize_job
            resize_job = None
            if not window.winfo_exists():
                return
            try:
                available_width = canvas.winfo_width()
                available_height = canvas.winfo_height()
            except tk.TclError:
                return
            if available_width <= 1 or available_height <= 1:
                return
            fit_scale = min(
                1.0,
                available_width / image_width,
                available_height / image_height,
            )
            new_scale = min(
                fit_scale if zoom_scale is None else zoom_scale,
                max_zoom_scale,
            )
            zoom_pct_var.set(f"{round(new_scale * 100)}%")
            if abs(new_scale - display_scale) < 1e-6 and display_photo is not None:
                return
            display_scale = new_scale
            display_width = max(1, round(image_width * display_scale))
            display_height = max(1, round(image_height * display_scale))
            if display_scale == 1.0:
                display_image = image
            else:
                interpolation = (
                    cv2.INTER_LINEAR if display_scale > 1.0 else cv2.INTER_AREA
                )
                display_image = cv2.resize(
                    image, (display_width, display_height), interpolation=interpolation
                )
            success, encoded = cv2.imencode(".png", display_image)
            if not success:
                raise ValueError("画像を表示用に変換できません。")
            display_photo = tk.PhotoImage(
                data=base64.b64encode(encoded).decode("ascii")
            )
            canvas.itemconfigure(display_image_id, image=display_photo)
            canvas.configure(scrollregion=(0, 0, display_width, display_height))
            canvas.image = display_photo
            redraw_overlay()

        def set_zoom(scale: float | None) -> None:
            nonlocal zoom_scale
            zoom_scale = None if scale is None else min(scale, max_zoom_scale)
            if scale is None:
                canvas.xview_moveto(0)
                canvas.yview_moveto(0)
            refresh_display_image()

        def zoom_in() -> None:
            if display_scale < max_zoom_scale:
                set_zoom(min(display_scale * 1.25, max_zoom_scale))

        def zoom_out() -> None:
            if display_scale > min_zoom_scale:
                set_zoom(max(display_scale / 1.25, min_zoom_scale))

        def schedule_display_refresh(_event: object | None = None) -> None:
            nonlocal resize_job
            if resize_job is None and window.winfo_exists():
                try:
                    resize_job = window.after_idle(refresh_display_image)
                except tk.TclError:
                    pass

        ttk.Label(panel, text="OCRで読み取った長さ", style="SectionTitle.TLabel").grid(
            row=0, column=0, sticky="w", pady=(0, 2)
        )
        ocr_summary = ttk.Label(
            panel, textvariable=ocr_summary_var, wraplength=290, justify="left"
        )
        ocr_summary.grid(row=1, column=0, sticky="ew", pady=(0, 2))
        progressbar = ttk.Progressbar(panel, mode="indeterminate", length=240)
        progressbar.grid(row=2, column=0, sticky="ew", pady=(2, 6))
        progressbar.start(15)

        label_combo = ttk.Combobox(
            panel,
            textvariable=label_choice_var,
            state="readonly",
            width=34,
        )
        label_combo.grid(row=3, column=0, sticky="ew", pady=2)
        ttk.Label(panel, text="距離の数値と単位（必要なら修正）").grid(
            row=4, column=0, sticky="w", pady=(8, 2)
        )
        length_row = ttk.Frame(panel, style="Card.TFrame")
        length_row.grid(row=5, column=0, sticky="ew")
        length_row.columnconfigure(0, weight=1)
        ttk.Entry(length_row, textvariable=value_var, width=14).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Combobox(
            length_row,
            textvariable=unit_var,
            values=("mm", "cm", "m"),
            state="readonly",
            width=6,
        ).grid(row=0, column=1, sticky="e")
        ttk.Label(panel, text="目盛り線の候補").grid(
            row=6, column=0, sticky="w", pady=(10, 2)
        )
        bar_combo = ttk.Combobox(
            panel,
            textvariable=bar_choice_var,
            state="readonly",
            width=34,
        )
        bar_combo.grid(row=7, column=0, sticky="ew", pady=2)
        ttk.Label(panel, text="画像上の長さ").grid(
            row=8, column=0, sticky="w", pady=(8, 0)
        )
        ttk.Label(panel, textvariable=bar_length_var, font=(ui_font, 10, "bold")).grid(
            row=9, column=0, sticky="w"
        )
        ttk.Label(
            panel,
            textvariable=points_status_var,
            wraplength=290,
            justify="left",
            style="Muted.TLabel",
        ).grid(row=10, column=0, sticky="ew", pady=(6, 2))

        def reset_manual_points() -> None:
            manual_points.clear()
            update_bar_choices()
            points_status_var.set("自動検出の結果に戻しました。")

        ttk.Button(
            panel,
            text="自動検出線に戻す",
            style="Subtle.TButton",
            command=reset_manual_points,
        ).grid(row=11, column=0, sticky="ew", pady=(2, 6))

        ttk.Label(
            panel,
            textvariable=scale_result_var,
            font=(ui_font, 13, "bold"),
            foreground=ACCENT_PRIMARY,
        ).grid(row=12, column=0, sticky="w", pady=(4, 8))

        def current_label():
            index = label_combo.current()
            return (
                label_candidates[index] if 0 <= index < len(label_candidates) else None
            )

        def current_bar():
            if manual_points:
                if len(manual_points) == 2:
                    return manual_points[0], manual_points[1]
                return None
            index = bar_combo.current()
            if 0 <= index < len(bar_candidates):
                candidate = bar_candidates[index]
                return (candidate.x1, candidate.y1), (candidate.x2, candidate.y2)
            return None

        def redraw_overlay() -> None:
            for item_id in overlay_ids:
                canvas.delete(item_id)
            overlay_ids.clear()
            for index, candidate in enumerate(bar_candidates):
                is_candidate_selected = (
                    not manual_points and index == bar_combo.current()
                )
                color = "#EF4444" if is_candidate_selected else "#F59E0B"
                width = 3 if is_candidate_selected else 1
                x1, y1 = display_point(candidate.x1, candidate.y1)
                x2, y2 = display_point(candidate.x2, candidate.y2)
                overlay_ids.append(
                    canvas.create_line(x1, y1, x2, y2, fill=color, width=width)
                )
            label = current_label()
            if label is not None:
                x0, y0, x1, y1 = label.bounds
                x0, y0 = display_point(x0, y0)
                x1, y1 = display_point(x1, y1)
                overlay_ids.append(
                    canvas.create_rectangle(x0, y0, x1, y1, outline="#10B981", width=2)
                )
            if len(manual_points) == 1:
                mx, my = display_point(manual_points[0][0], manual_points[0][1])
                overlay_ids.append(
                    canvas.create_oval(
                        mx - 5, my - 5, mx + 5, my + 5, outline="#EF4444", width=2
                    )
                )
            selected = current_bar()
            if selected is not None:
                (x0, y0), (x1, y1) = selected
                x0, y0 = display_point(x0, y0)
                x1, y1 = display_point(x1, y1)
                for x, y in ((x0, y0), (x1, y1)):
                    overlay_ids.append(
                        canvas.create_oval(
                            x - 5, y - 5, x + 5, y + 5, outline="#EF4444", width=2
                        )
                    )
                overlay_ids.append(
                    canvas.create_line(x0, y0, x1, y1, fill="#EF4444", width=3)
                )

        def update_scale_result(*_args: object) -> None:
            selected = current_bar()
            if selected is None:
                bar_length_var.set("—")
                scale_result_var.set("mm/px: —")
                return
            (x0, y0), (x1, y1) = selected
            pixels = math.hypot(x1 - x0, y1 - y0)
            bar_length_var.set(f"{pixels:.2f} px")
            try:
                length = float(value_var.get().strip().replace(",", "."))
                factors = {"mm": 1.0, "cm": 10.0, "m": 1000.0}
                millimeters = length * factors[unit_var.get()]
                if not math.isfinite(millimeters) or millimeters <= 0 or pixels <= 0:
                    raise ValueError
            except (KeyError, ValueError):
                scale_result_var.set("mm/px: 数値と単位を確認")
                return
            scale_result_var.set(f"mm/px: {millimeters / pixels:.8g}")

        def update_bar_choices() -> None:
            nonlocal bar_candidates
            from pottery_scale import rank_scale_bars

            bar_candidates = rank_scale_bars(
                all_bar_candidates, current_label(), image.shape
            )
            choices = [
                f"{index + 1}: {bar.pixels:.1f} px  (y={((bar.y1 + bar.y2) / 2):.0f})"
                for index, bar in enumerate(bar_candidates)
            ]
            bar_combo.configure(values=choices)
            if choices:
                bar_combo.current(0)
                points_status_var.set(
                    "赤線の両端を確認してください。画像クリックで手動指定もできます。"
                )
            else:
                bar_combo.set("")
                points_status_var.set(
                    "目盛り線を自動検出できませんでした。画像上で両端をクリックしてください。"
                )
            redraw_overlay()
            update_scale_result()

        all_bar_candidates: list[object] = []

        def on_label_selected(_event: object | None = None) -> None:
            label = current_label()
            if label is not None:
                value_var.set(f"{label.value:g}")
                unit_var.set(label.unit)
            manual_points.clear()
            update_bar_choices()

        def on_bar_selected(_event: object | None = None) -> None:
            manual_points.clear()
            redraw_overlay()
            update_scale_result()

        def on_canvas_click(event: object) -> None:
            x, y = image_point(
                float(canvas.canvasx(event.x)),  # type: ignore[attr-defined]
                float(canvas.canvasy(event.y)),  # type: ignore[attr-defined]
            )
            if x < 0 or y < 0 or x >= image_width or y >= image_height:
                return
            if len(manual_points) == 2:
                manual_points.clear()
            manual_points.append((x, y))
            if len(manual_points) == 1:
                points_status_var.set(
                    "始点を設定しました。終点をクリックしてください。"
                )
            else:
                points_status_var.set(
                    "始点・終点を指定しました。結果を確認して反映してください。"
                )
            redraw_overlay()
            update_scale_result()

        def close_window() -> None:
            nonlocal resize_job
            if resize_job is not None:
                try:
                    window.after_cancel(resize_job)
                except tk.TclError:
                    pass
                resize_job = None
            window.destroy()

        def apply_scale() -> None:
            selected = current_bar()
            if selected is None or len(manual_points) == 1:
                messagebox.showerror(
                    "目盛り線を指定してください",
                    "候補を選ぶか、画像上で目盛り線の両端をクリックしてください。",
                    parent=window,
                )
                return
            (x0, y0), (x1, y1) = selected
            pixels = math.hypot(x1 - x0, y1 - y0)
            try:
                length = float(value_var.get().strip().replace(",", "."))
                factor = {"mm": 1.0, "cm": 10.0, "m": 1000.0}[unit_var.get()]
                millimeters = length * factor
                mm_per_px = millimeters / pixels
                if (
                    not math.isfinite(mm_per_px)
                    or mm_per_px <= 0
                    or not math.isfinite(pixels)
                    or pixels <= 0
                ):
                    raise ValueError
            except (KeyError, ValueError, ZeroDivisionError):
                messagebox.showerror(
                    "長さを確認してください",
                    "距離は正の数値で、単位は mm、cm、m のいずれかを指定してください。",
                    parent=window,
                )
                return
            direct_scale_var.set(f"{mm_per_px:.10g}")
            scale_mode_var.set("mm/px を直接指定")
            set_status(
                f"スケール（{mm_per_px:.4f} mm/px）を自動読み取りから反映しました。",
                "success",
            )
            close_window()

        label_combo.bind("<<ComboboxSelected>>", on_label_selected)
        bar_combo.bind("<<ComboboxSelected>>", on_bar_selected)
        value_var.trace_add("write", update_scale_result)
        unit_var.trace_add("write", update_scale_result)
        canvas.bind("<Button-1>", on_canvas_click)
        canvas_frame.bind("<Configure>", schedule_display_refresh)

        zoom_frame = ttk.Frame(panel, style="Card.TFrame")
        zoom_frame.grid(row=13, column=0, sticky="ew", pady=(8, 6))
        zoom_header = ttk.Frame(zoom_frame, style="Card.TFrame")
        zoom_header.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(zoom_header, text="表示倍率", style="Muted.TLabel").pack(side="left")
        ttk.Label(
            zoom_header,
            textvariable=zoom_pct_var,
            font=(ui_font, 9, "bold"),
            foreground=ACCENT_PRIMARY,
        ).pack(side="right")

        ttk.Button(
            zoom_frame,
            text="全体 (0)",
            style="Subtle.TButton",
            command=lambda: set_zoom(None),
        ).grid(row=1, column=0, sticky="ew", padx=(0, 2), pady=2)
        ttk.Button(
            zoom_frame,
            text="原寸 (1)",
            style="Subtle.TButton",
            command=lambda: set_zoom(1.0),
        ).grid(row=1, column=1, sticky="ew", padx=(2, 0), pady=2)
        ttk.Button(
            zoom_frame, text="拡大 (+)", style="Subtle.TButton", command=zoom_in
        ).grid(row=2, column=0, sticky="ew", padx=(0, 2))
        ttk.Button(
            zoom_frame, text="縮小 (-)", style="Subtle.TButton", command=zoom_out
        ).grid(row=2, column=1, sticky="ew", padx=(2, 0))
        zoom_frame.columnconfigure(0, weight=1)
        zoom_frame.columnconfigure(1, weight=1)

        ttk.Button(
            panel,
            text="mm/pxとして反映",
            style="Primary.TButton",
            command=apply_scale,
        ).grid(row=14, column=0, sticky="ew", pady=4)
        ttk.Button(panel, text="閉じる (Esc)", command=close_window).grid(
            row=15, column=0, sticky="ew", pady=2
        )

        def on_mousewheel(event: object) -> None:
            delta = getattr(event, "delta", 0)
            num = getattr(event, "num", 0)
            if delta > 0 or num == 4:
                zoom_in()
            elif delta < 0 or num == 5:
                zoom_out()

        def on_pan_start(event: object) -> None:
            canvas.scan_mark(event.x, event.y)

        def on_pan_move(event: object) -> None:
            canvas.scan_dragto(event.x, event.y, gain=1)

        canvas.bind("<MouseWheel>", on_mousewheel)
        canvas.bind("<Button-4>", on_mousewheel)
        canvas.bind("<Button-5>", on_mousewheel)
        canvas.bind("<ButtonPress-2>", on_pan_start)
        canvas.bind("<B2-Motion>", on_pan_move)
        canvas.bind("<ButtonPress-3>", on_pan_start)
        canvas.bind("<B3-Motion>", on_pan_move)

        window.bind("<plus>", lambda _e: zoom_in())
        window.bind("<KP_Add>", lambda _e: zoom_in())
        window.bind("<minus>", lambda _e: zoom_out())
        window.bind("<KP_Subtract>", lambda _e: zoom_out())
        window.bind("<Key-0>", lambda _e: set_zoom(None))
        window.bind("<Key-1>", lambda _e: set_zoom(1.0))
        window.bind("<Escape>", lambda _e: close_window())

        window.protocol("WM_DELETE_WINDOW", close_window)
        window.update_idletasks()
        refresh_display_image()

        def finish_detection(labels: list[object], bars: list[object]) -> None:
            if not window.winfo_exists():
                return
            progressbar.stop()
            progressbar.grid_remove()
            label_candidates[:] = labels
            all_bar_candidates[:] = bars
            if labels:
                label_combo.configure(
                    values=[
                        f"{item.text}  →  {item.length_mm:g} mm  ({item.confidence:.0%})"
                        for item in labels
                    ]
                )
                label_combo.current(0)
                ocr_summary_var.set(
                    "読み取った長さ: "
                    + " / ".join(
                        f"{item.text} ({item.confidence:.0%})" for item in labels
                    )
                )
                on_label_selected()
            else:
                label_combo.configure(values=())
                ocr_summary_var.set(
                    "単位付きの長さを読めませんでした。数値と単位を入力してください。"
                )
                update_bar_choices()

        def detect_in_background() -> None:
            try:
                from pottery_scale import (
                    detect_horizontal_scale_bars,
                    recognize_scale_text,
                )

                bars = detect_horizontal_scale_bars(image)
                labels = recognize_scale_text(image)
                window.after(0, lambda: finish_detection(labels, bars))
            except Exception as exc:
                error_text = str(exc)

                def finish_error(error_text: str = error_text) -> None:
                    if not window.winfo_exists():
                        return
                    progressbar.stop()
                    progressbar.grid_remove()
                    ocr_summary_var.set(
                        f"OCRを利用できませんでした: {error_text}\n数値と単位を入力して続けられます。"
                    )
                    from pottery_scale import detect_horizontal_scale_bars

                    update_bars = detect_horizontal_scale_bars(image)
                    finish_detection([], update_bars)

                try:
                    window.after(0, finish_error)
                except tk.TclError:
                    pass

        threading.Thread(target=detect_in_background, daemon=True).start()

    # Scale Tool Buttons Bar
    scale_tools_bar = ttk.Frame(scale_card, style="Card.TFrame")
    scale_tools_bar.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
    scale_tools_bar.columnconfigure(0, weight=1)
    scale_tools_bar.columnconfigure(1, weight=1)

    ttk.Button(
        scale_tools_bar,
        text="画像から自動読み取り…",
        style="Accent.TButton",
        command=open_scale_reader,
    ).grid(row=0, column=0, sticky="ew", padx=(0, 4))
    ttk.Button(
        scale_tools_bar,
        text="画像上で2点測定…",
        command=open_measurement_tool,
    ).grid(row=0, column=1, sticky="ew", padx=(4, 0))

    # =========================================================================
    # STEP 3: Collapsible Advanced Settings Card
    # =========================================================================
    adv_card = make_card(left_pane, row=2, column=0, sticky="ew", pady=(0, 10))
    adv_card.columnconfigure(0, weight=1)

    adv_header = ttk.Frame(adv_card, style="Card.TFrame")
    adv_header.grid(row=0, column=0, sticky="ew")
    adv_header.columnconfigure(1, weight=1)

    adv_toggle_btn = ttk.Button(
        adv_header,
        text="▶ 詳細オプション（自動検出の微調整・ファイル出力）",
        style="Subtle.TButton",
    )
    adv_toggle_btn.grid(row=0, column=0, columnspan=2, sticky="ew")

    adv_body = ttk.Frame(adv_card, style="Card.TFrame")
    adv_body.columnconfigure(1, weight=1)

    def toggle_advanced() -> None:
        is_open = not advanced_open_var.get()
        advanced_open_var.set(is_open)
        if is_open:
            adv_toggle_btn.configure(
                text="▼ 詳細オプション（自動検出の微調整・ファイル出力）"
            )
            adv_body.grid(row=1, column=0, sticky="ew", pady=(10, 0))
        else:
            adv_toggle_btn.configure(
                text="▶ 詳細オプション（自動検出の微調整・ファイル出力）"
            )
            adv_body.grid_remove()

    adv_toggle_btn.configure(command=toggle_advanced)

    def add_setting(
        row: int, title: str, variable: tk.StringVar, hint: str = ""
    ) -> None:
        ttk.Label(adv_body, text=title).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(adv_body, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=(8, 6), pady=3
        )
        if hint:
            ttk.Label(adv_body, text=hint, style="Muted.TLabel").grid(
                row=row, column=2, sticky="w", pady=3
            )

    add_setting(0, "回転軸 x (px)", axis_var, "空欄で自動")
    add_setting(1, "断面 crop", crop_var, "x0,y0,x1,y1")
    add_setting(2, "液面 y (px)", liquid_var, "空欄で口縁")

    morph_row = ttk.Frame(adv_body, style="Card.TFrame")
    morph_row.grid(row=3, column=0, columnspan=3, sticky="ew", pady=5)
    ttk.Label(morph_row, text="クロージング").pack(side="left")
    ttk.Entry(morph_row, textvariable=kernel_var, width=4).pack(
        side="left", padx=(4, 10)
    )
    ttk.Label(morph_row, text="最小成分").pack(side="left")
    ttk.Entry(morph_row, textvariable=min_area_var, width=4).pack(
        side="left", padx=(4, 10)
    )
    ttk.Label(morph_row, text="平滑化").pack(side="left")
    ttk.Entry(morph_row, textvariable=smooth_var, width=4).pack(
        side="left", padx=(4, 10)
    )
    ttk.Label(morph_row, text="輪郭").pack(side="left")
    ttk.Combobox(
        morph_row,
        textvariable=profile_mode_var,
        values=("auto", "filled", "lines"),
        state="readonly",
        width=7,
    ).pack(side="left", padx=(4, 0))

    ttk.Checkbutton(
        adv_body, text="適応的二値化を使う（影・ムラがある場合）", variable=adaptive_var
    ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 6))

    ttk.Separator(adv_body, orient="horizontal").grid(
        row=5, column=0, columnspan=3, sticky="ew", pady=4
    )

    ttk.Label(adv_body, text="JSON保存先").grid(row=6, column=0, sticky="w", pady=3)
    ttk.Entry(adv_body, textvariable=json_var).grid(
        row=6, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3
    )
    ttk.Checkbutton(adv_body, text="デバッグ画像出力", variable=save_debug_var).grid(
        row=7, column=0, sticky="w", pady=3
    )
    ttk.Entry(adv_body, textvariable=debug_var).grid(
        row=7, column=1, columnspan=2, sticky="ew", padx=(8, 0), pady=3
    )

    # =========================================================================
    # Primary Action Bar (Bottom of Left Pane)
    # =========================================================================
    action_bar = ttk.Frame(left_pane, style="App.TFrame")
    action_bar.grid(row=4, column=0, sticky="sew", pady=(4, 0))
    action_bar.columnconfigure(0, weight=1)

    # =========================================================================
    # RIGHT PANE: Results & Export Card
    # =========================================================================
    result_card = make_card(right_pane, row=0, column=0, sticky="nsew")
    result_card.columnconfigure(0, weight=1)
    result_card.rowconfigure(4, weight=1)

    res_header = ttk.Frame(result_card, style="Card.TFrame")
    res_header.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    ttk.Label(res_header, text="推定結果", style="SectionTitle.TLabel").pack(
        side="left"
    )

    # Measurement Title Field
    title_row = ttk.Frame(result_card, style="Card.TFrame")
    title_row.grid(row=1, column=0, sticky="ew", pady=(0, 10))
    title_row.columnconfigure(1, weight=1)
    ttk.Label(title_row, text="資料名 / タイトル").grid(row=0, column=0, sticky="w")
    ttk.Entry(title_row, textvariable=measurement_title_var).grid(
        row=0, column=1, sticky="ew", padx=(8, 0)
    )

    # Highlighted KPI Cards (Capacity & Wall Volume)
    kpi_grid = ttk.Frame(result_card, style="Card.TFrame")
    kpi_grid.grid(row=2, column=0, sticky="ew", pady=(0, 10))
    kpi_grid.columnconfigure(0, weight=1, uniform="kpi")
    kpi_grid.columnconfigure(1, weight=1, uniform="kpi")

    cap_box = tk.Frame(
        kpi_grid,
        background=BG_BANNER_INFO,
        highlightbackground=BORDER_COLOR,
        highlightthickness=1,
        padx=12,
        pady=10,
    )
    cap_box.grid(row=0, column=0, sticky="ew", padx=(0, 5))
    tk.Label(
        cap_box,
        text="内腔容量（内容量）",
        font=(ui_font, 9, "bold"),
        background=BG_BANNER_INFO,
        foreground=ACCENT_PRIMARY,
    ).pack(anchor="w")
    cap_val_row = tk.Frame(cap_box, background=BG_BANNER_INFO)
    cap_val_row.pack(anchor="w", pady=(2, 0))
    tk.Label(
        cap_val_row,
        textvariable=kpi_capacity_var,
        font=(ui_font, 14, "bold"),
        background=BG_BANNER_INFO,
        foreground=ACCENT_PRIMARY,
    ).pack(side="left")
    tk.Label(
        cap_val_row,
        textvariable=kpi_capacity_unit_var,
        font=(ui_font, 11, "bold"),
        background=BG_BANNER_INFO,
        foreground=ACCENT_PRIMARY,
    ).pack(side="left", padx=(4, 0), pady=(5, 0))

    wall_box = tk.Frame(
        kpi_grid,
        background=BG_SUBTLE,
        highlightbackground=BORDER_COLOR,
        highlightthickness=1,
        padx=12,
        pady=10,
    )
    wall_box.grid(row=0, column=1, sticky="ew", padx=(5, 0))
    tk.Label(
        wall_box,
        text="器壁体積（粘土体積）",
        font=(ui_font, 9, "bold"),
        background=BG_SUBTLE,
        foreground=TEXT_SECONDARY,
    ).pack(anchor="w")
    wall_val_row = tk.Frame(wall_box, background=BG_SUBTLE)
    wall_val_row.pack(anchor="w", pady=(2, 0))
    tk.Label(
        wall_val_row,
        textvariable=kpi_wall_var,
        font=(ui_font, 14, "bold"),
        background=BG_SUBTLE,
        foreground=TEXT_PRIMARY,
    ).pack(side="left")
    tk.Label(
        wall_val_row,
        textvariable=kpi_wall_unit_var,
        font=(ui_font, 11, "bold"),
        background=BG_SUBTLE,
        foreground=TEXT_SECONDARY,
    ).pack(side="left", padx=(4, 0), pady=(5, 0))

    # Structured Dimension & Verification Table
    metrics_box = tk.Frame(
        result_card,
        background=BG_SUBTLE,
        highlightbackground=BORDER_COLOR,
        highlightthickness=1,
        padx=10,
        pady=8,
    )
    metrics_box.grid(row=3, column=0, sticky="ew", pady=(0, 10))
    metrics_box.columnconfigure(1, weight=1)
    metrics_box.columnconfigure(3, weight=1)

    metric_items = [
        (0, 0, "器高:", metric_height_var),
        (0, 2, "全外形体積:", metric_total_vol_var),
        (1, 0, "口径:", metric_mouth_var),
        (1, 2, "パップス検算:", metric_pappus_var),
        (2, 0, "最大径:", metric_max_dia_var),
        (2, 2, "適用スケール:", metric_scale_var),
    ]
    for r_idx, c_idx, lbl_text, var in metric_items:
        ttk.Label(metrics_box, text=lbl_text, style="Subtle.TLabel").grid(
            row=r_idx,
            column=c_idx,
            sticky="w",
            padx=(4 if c_idx == 0 else 14, 4),
            pady=3,
        )
        tk.Label(
            metrics_box,
            textvariable=var,
            font=(ui_font, 10, "bold"),
            background=BG_SUBTLE,
            foreground=TEXT_PRIMARY,
            anchor="e",
        ).grid(row=r_idx, column=c_idx + 1, sticky="e", padx=(0, 4), pady=3)

    # Detailed Log / Warnings Box
    log_wrapper = ttk.Frame(result_card, style="Card.TFrame")
    log_wrapper.grid(row=4, column=0, sticky="nsew", pady=(0, 8))
    log_wrapper.columnconfigure(0, weight=1)
    log_wrapper.rowconfigure(1, weight=1)

    ttk.Label(log_wrapper, text="詳細ログ・注意メッセージ", style="Muted.TLabel").grid(
        row=0, column=0, sticky="w", pady=(0, 3)
    )

    result_box = tk.Text(
        log_wrapper,
        height=6,
        wrap="word",
        state="disabled",
        font=(ui_font, 9),
        background=BG_SUBTLE,
        foreground=TEXT_PRIMARY,
        relief="solid",
        bd=1,
        padx=10,
        pady=8,
        highlightthickness=0,
    )
    result_scroll = ttk.Scrollbar(
        log_wrapper, orient="vertical", command=result_box.yview
    )
    result_box.configure(yscrollcommand=result_scroll.set)
    result_box.grid(row=1, column=0, sticky="nsew")
    result_scroll.grid(row=1, column=1, sticky="ns")

    # History Management
    last_analysis_info: dict[str, object] | None = None
    history_records: dict[int, dict[str, str]] = {}
    next_history_id = 0
    history_window: tk.Toplevel | None = None
    history_tree: ttk.Treeview | None = None
    history_status_var = tk.StringVar(value="")
    selected_history_cell: tuple[str, str] | None = None
    selected_history_column: str | None = None
    include_header_var = tk.BooleanVar(value=False)
    history_columns = (
        "title",
        "image",
        "height",
        "mouth_diameter",
        "maximum_diameter",
        "length_unit",
        "capacity",
        "wall_volume",
        "total_volume",
        "pappus_volume",
        "difference",
        "volume_unit",
    )
    history_headings = {
        "title": "タイトル",
        "image": "画像ファイル",
        "height": "器高",
        "mouth_diameter": "口径",
        "maximum_diameter": "最大径",
        "length_unit": "長さ単位",
        "capacity": "内容量",
        "wall_volume": "器壁体積",
        "total_volume": "全体体積",
        "pappus_volume": "パップス法",
        "difference": "差 (%)",
        "volume_unit": "体積単位",
    }

    def update_history_button_label() -> None:
        count = len(history_records)
        history_button.configure(text=f"測定履歴 ({count})" if count else "測定履歴")

    def copy_to_clipboard(
        text: str,
        success_msg: str,
        trigger_btn: ttk.Button | None = None,
        original_label: str = "",
    ) -> None:
        if not text.strip():
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        set_status(success_msg, "success")
        if trigger_btn is not None and original_label:
            trigger_btn.configure(text="コピー済")
            root.after(
                1400,
                lambda: (
                    trigger_btn.configure(text=original_label)
                    if trigger_btn.winfo_exists()
                    else None
                ),
            )

    def history_display_values(
        result: dict[str, object], image_path: Path, title: str
    ) -> dict[str, str]:
        length_unit = str(result["units"]["length"])  # type: ignore[index]
        volume_unit = str(result["units"]["volume"])  # type: ignore[index]

        def clean_cell(value: object) -> str:
            return str(value).replace("\t", " ").replace("\r", " ").replace("\n", " ")

        is_mm = "capacity_ml" in result
        if is_mm:
            capacity = f"{result['capacity_ml']:.2f}"
            wall_volume = f"{result['wall_volume_ml']:.2f}"
            total_volume = f"{result['capacity_ml'] + result['wall_volume_ml']:.2f}"
            pappus_volume = f"{result['pappus_wall_volume_ml']:.2f}"
            volume_unit = "mL"
        else:
            capacity = f"{result['capacity']:.2f}"
            wall_volume = f"{result['wall_volume']:.2f}"
            total_volume = f"{result['capacity'] + result['wall_volume']:.2f}"
            pappus_volume = f"{result['pappus_wall_volume']:.2f}"
        return {
            "title": clean_cell(title),
            "image": clean_cell(image_path.name),
            "height": f"{result['vessel_height']:.2f}",
            "mouth_diameter": f"{result['mouth_diameter']:.2f}",
            "maximum_diameter": f"{result['maximum_diameter']:.2f}",
            "length_unit": length_unit,
            "capacity": capacity,
            "wall_volume": wall_volume,
            "total_volume": total_volume,
            "pappus_volume": pappus_volume,
            "difference": f"{result['pappus_difference_percent']:.2f}",
            "volume_unit": volume_unit,
        }

    def selected_history_rows() -> list[str]:
        if history_tree is None:
            return []
        visible_order = history_tree.get_children("")
        selected = set(history_tree.selection())
        return [iid for iid in visible_order if iid in selected]

    def copy_history_rows() -> None:
        if history_tree is None:
            return
        selected = selected_history_rows()
        if not selected:
            history_status_var.set("コピーする行を選択してください。")
            return
        rows = [
            "\t".join(history_records[int(iid)][column] for column in history_columns)
            for iid in selected
        ]
        if include_header_var.get():
            rows.insert(
                0, "\t".join(history_headings[column] for column in history_columns)
            )
            rows_count = len(rows) - 1
        else:
            rows_count = len(rows)
        copy_to_clipboard(
            "\n".join(rows), f"履歴から {rows_count} 行をコピーしました。"
        )
        history_status_var.set(f"{rows_count} 行をクリップボードにコピーしました。")

    def copy_history_cell() -> None:
        if history_tree is None or selected_history_cell is None:
            history_status_var.set("コピーするセルをクリックしてください。")
            return
        iid_str, column = selected_history_cell
        iid = int(iid_str)
        if iid not in history_records or column not in history_records[iid]:
            history_status_var.set("コピーするセルをクリックしてください。")
            return
        copy_to_clipboard(
            history_records[iid][column],
            f"「{history_headings[column]}」のセルをコピーしました。",
        )
        history_status_var.set(f"{history_headings[column]} のセルをコピーしました。")

    def copy_history_column() -> None:
        if history_tree is None or selected_history_column is None:
            history_status_var.set("列見出しかセルをクリックして列を選択してください。")
            return
        column = selected_history_column
        iids = history_tree.get_children("")
        values = [history_records[int(iid)][column] for iid in iids]
        if not values:
            history_status_var.set("コピーするデータがありません。")
            return
        if include_header_var.get():
            values.insert(0, history_headings[column])
            count = len(values) - 1
        else:
            count = len(values)
        copy_to_clipboard(
            "\n".join(values),
            f"「{history_headings[column]}」列 {count} 件をコピーしました。",
        )
        history_status_var.set(
            f"{history_headings[column]} 列 {count} 件をクリップボードにコピーしました。"
        )

    def delete_history_rows() -> None:
        if history_tree is None:
            return
        selected = selected_history_rows()
        if not selected:
            history_status_var.set("削除する行を選択してください。")
            return
        for iid in selected:
            history_tree.delete(iid)
            history_records.pop(int(iid), None)
        update_history_button_label()
        history_status_var.set(f"{len(selected)} 行を削除しました。")

    def show_history(raise_window: bool = True) -> None:
        nonlocal history_window, history_tree, selected_history_cell
        if history_window is not None and history_window.winfo_exists():
            if raise_window:
                history_window.deiconify()
                history_window.lift()
            return

        window = tk.Toplevel(root)
        history_window = window
        window.title("測定履歴一覧")
        window.geometry("1340x460")
        window.minsize(900, 320)
        window.configure(background=BG_APP)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(0, weight=1)

        table_frame = make_card(
            window, row=0, column=0, sticky="nsew", padx=12, pady=(12, 6)
        )
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)
        tree = ttk.Treeview(
            table_frame,
            columns=history_columns,
            show="headings",
            selectmode="extended",
        )
        tree_background = style.lookup("Treeview", "background") or BG_SUBTLE
        tree_foreground = style.lookup("Treeview", "foreground") or SYSTEM_TEXT
        tree.tag_configure(
            "oddrow", background=tree_background, foreground=tree_foreground
        )
        tree.tag_configure(
            "evenrow", background=tree_background, foreground=tree_foreground
        )
        history_tree = tree
        for column in history_columns:
            tree.heading(column, text=history_headings[column])
            tree.column(column, width=105, minwidth=75, stretch=True, anchor="w")
        tree.column("title", width=155, minwidth=100)
        tree.column("image", width=180, minwidth=110)
        tree.column("difference", width=80, minwidth=65, stretch=False)
        tree.column("length_unit", width=80, minwidth=70, stretch=False)
        tree.column("volume_unit", width=80, minwidth=70, stretch=False)
        for column in (
            "height",
            "mouth_diameter",
            "maximum_diameter",
            "capacity",
            "wall_volume",
            "total_volume",
            "pappus_volume",
            "difference",
        ):
            tree.column(column, anchor="e")
        y_scroll = ttk.Scrollbar(table_frame, orient="vertical", command=tree.yview)
        x_scroll = ttk.Scrollbar(table_frame, orient="horizontal", command=tree.xview)
        tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        tree.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        def mark_history_cell(event: tk.Event) -> None:
            nonlocal selected_history_cell, selected_history_column
            iid = tree.identify_row(event.y)
            column_id = tree.identify_column(event.x)
            try:
                column_index = int(column_id[1:]) - 1
            except (TypeError, ValueError):
                return
            if not 0 <= column_index < len(history_columns):
                return
            column = history_columns[column_index]
            selected_history_column = column
            if tree.identify_region(event.x, event.y) == "heading":
                history_status_var.set(f"選択列: {history_headings[column]}")
            elif iid:
                selected_history_cell = (iid, column)
                history_status_var.set(f"選択セル: {history_headings[column]}")

        tree.bind("<Button-1>", mark_history_cell, add="+")
        tree.bind("<Button-3>", mark_history_cell, add="+")
        tree.bind("<Control-c>", lambda _event: (copy_history_rows(), "break")[1])
        tree.bind("<Control-C>", lambda _event: (copy_history_rows(), "break")[1])
        tree.bind("<Control-Shift-C>", lambda _event: (copy_history_cell(), "break")[1])

        controls = ttk.Frame(window, padding=(12, 4, 12, 12), style="App.TFrame")
        controls.grid(row=1, column=0, sticky="ew")
        ttk.Button(
            controls,
            text="選択行をコピー (Ctrl+C)",
            style="Accent.TButton",
            command=copy_history_rows,
        ).pack(side="left", padx=(0, 6))
        ttk.Button(
            controls,
            text="選択セルをコピー (Ctrl+Shift+C)",
            command=copy_history_cell,
        ).pack(side="left", padx=6)
        ttk.Button(
            controls,
            text="選択列をコピー",
            command=copy_history_column,
        ).pack(side="left", padx=6)
        ttk.Checkbutton(
            controls, text="ヘッダーを含める", variable=include_header_var
        ).pack(side="left", padx=6)
        ttk.Button(controls, text="選択行を削除", command=delete_history_rows).pack(
            side="left", padx=6
        )
        ttk.Label(
            controls,
            textvariable=history_status_var,
            style="App.TLabel",
            foreground=ACCENT_PRIMARY,
        ).pack(side="left", padx=12)

        context_menu = tk.Menu(window, tearoff=False)
        context_menu.add_command(label="セルをコピー", command=copy_history_cell)
        context_menu.add_command(label="列をコピー", command=copy_history_column)
        context_menu.add_command(label="選択行をコピー", command=copy_history_rows)
        context_menu.add_separator()
        context_menu.add_command(label="選択行を削除", command=delete_history_rows)

        def post_context_menu(event: tk.Event) -> str:
            mark_history_cell(event)
            context_menu.tk_popup(event.x_root, event.y_root)
            return "break"

        tree.bind("<Button-3>", post_context_menu)
        for idx, (record_id, values) in enumerate(history_records.items()):
            tag = "evenrow" if idx % 2 == 0 else "oddrow"
            tree.insert(
                "",
                "end",
                iid=str(record_id),
                values=tuple(values[column] for column in history_columns),
                tags=(tag,),
            )
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        if raise_window:
            window.lift()

    def add_history_record(result: dict[str, object], image_path: Path) -> None:
        nonlocal next_history_id
        record_title = measurement_title_var.get().strip() or image_path.stem
        record = history_display_values(result, image_path, record_title)
        record_id = next_history_id
        next_history_id += 1
        history_records[record_id] = record
        update_history_button_label()
        iid = str(record_id)
        if (
            history_tree is not None
            and history_window is not None
            and history_window.winfo_exists()
        ):
            tag = "evenrow" if len(history_records) % 2 == 1 else "oddrow"
            history_tree.insert(
                "",
                "end",
                iid=iid,
                values=tuple(record[column] for column in history_columns),
                tags=(tag,),
            )
            history_tree.see(iid)

    def current_export_info() -> dict[str, object] | None:
        if last_analysis_info is None:
            return None
        info = dict(last_analysis_info)
        if not title_is_automatic:
            selected_image = image_var.get().strip().strip('"')
            result_image = str(info.get("image_path", ""))
            if selected_image and result_image:
                if Path(selected_image).resolve() == Path(result_image).resolve():
                    info["title"] = measurement_title_var.get()
        return info

    # Export / Copy Bar (Bottom of Right Pane)
    copy_section = ttk.Frame(result_card, style="Card.TFrame")
    copy_section.grid(row=5, column=0, sticky="ew")
    copy_section.columnconfigure((0, 1, 2, 3), weight=1)

    ttk.Label(
        copy_section,
        text="クリップボードへコピー（Excel貼り付け対応）",
        style="Muted.TLabel",
    ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, 4))

    def copy_result() -> None:
        info = current_export_info()
        if info is None:
            messagebox.showinfo("案内", "先に計算を実行してください。", parent=root)
            return
        res = info["result"]  # type: ignore[index]
        length_unit = res["units"]["length"]
        volume_unit = res["units"]["volume"]
        if "capacity_ml" in res:
            summary = (
                f"【{info['title']}】\n"
                f"器高: {res['vessel_height']:.2f} {length_unit} / "
                f"口径: {res['mouth_diameter']:.2f} {length_unit} / "
                f"最大径: {res['maximum_diameter']:.2f} {length_unit}\n"
                f"内腔容量: {res['capacity_ml']:.2f} mL / "
                f"器壁体積: {res['wall_volume_ml']:.2f} mL "
                f"(パップス差: {res['pappus_difference_percent']:.2f}%)"
            )
        else:
            summary = (
                f"【{info['title']}】\n"
                f"器高: {res['vessel_height']:.2f} {length_unit} / "
                f"口径: {res['mouth_diameter']:.2f} {length_unit} / "
                f"最大径: {res['maximum_diameter']:.2f} {length_unit}\n"
                f"内腔容量: {res['capacity']:.2f} {volume_unit} / "
                f"器壁体積: {res['wall_volume']:.2f} {volume_unit} "
                f"(パップス差: {res['pappus_difference_percent']:.2f}%)"
            )
        copy_to_clipboard(
            summary,
            "推定結果サマリーをコピーしました。",
            btn_copy_summary,
            "サマリー",
        )

    def copy_excel_row() -> None:
        info = current_export_info()
        if info is None:
            messagebox.showinfo("案内", "先に計算を実行してください。", parent=root)
            return
        tsv = build_tsv_row(info, include_header=False)
        copy_to_clipboard(
            tsv,
            "Excel用横1行データ（TSV）をコピーしました。Excelで Ctrl+V できます。",
            btn_copy_row,
            "Excel横1行",
        )

    def copy_excel_header_row() -> None:
        info = current_export_info()
        if info is None:
            messagebox.showinfo("案内", "先に計算を実行してください。", parent=root)
            return
        tsv = build_tsv_row(info, include_header=True)
        copy_to_clipboard(
            tsv,
            "Excel用ヘッダー付き横1行データをコピーしました。",
            btn_copy_header_row,
            "ヘッダー付1行",
        )

    def copy_excel_table() -> None:
        info = current_export_info()
        if info is None:
            messagebox.showinfo("案内", "先に計算を実行してください。", parent=root)
            return
        tsv = build_tsv_table(info)
        copy_to_clipboard(
            tsv,
            "Excel用縦の表データ（項目・値・単位）をコピーしました。",
            btn_copy_table,
            "Excel縦の表",
        )

    btn_copy_summary = ttk.Button(
        copy_section, text="サマリー", style="Subtle.TButton", command=copy_result
    )
    btn_copy_summary.grid(row=1, column=0, sticky="ew", padx=(0, 3))

    btn_copy_row = ttk.Button(
        copy_section,
        text="Excel横1行",
        style="Accent.TButton",
        command=copy_excel_row,
    )
    btn_copy_row.grid(row=1, column=1, sticky="ew", padx=3)

    btn_copy_header_row = ttk.Button(
        copy_section,
        text="ヘッダー付1行",
        style="Subtle.TButton",
        command=copy_excel_header_row,
    )
    btn_copy_header_row.grid(row=1, column=2, sticky="ew", padx=3)

    btn_copy_table = ttk.Button(
        copy_section,
        text="Excel縦の表",
        style="Subtle.TButton",
        command=copy_excel_table,
    )
    btn_copy_table.grid(row=1, column=3, sticky="ew", padx=(3, 0))

    def show_log_text(value: str) -> None:
        result_box.configure(state="normal")
        result_box.delete("1.0", "end")
        result_box.insert("1.0", value)
        result_box.configure(state="disabled")

    show_log_text("画像を選択して「体積・容量を計算する」を押すと結果が表示されます。")

    def calculate() -> None:
        nonlocal last_analysis_info
        image_text = image_var.get().strip().strip('"')
        if not image_text:
            messagebox.showerror(
                "画像が未指定です",
                "土器画像を選ぶか、画像のパスを入力してください。",
                parent=root,
            )
            return
        image_path = Path(image_text)
        if not image_path.is_file():
            messagebox.showerror("画像が見つかりません", image_text, parent=root)
            return

        json_path = json_var.get().strip()
        command_args = [str(image_path)]
        mode = scale_mode_var.get()
        try:
            if mode == "mm/px を直接指定":
                command_args += ["--scale-mm-per-px", direct_scale_var.get().strip()]
            elif mode == "スケール線の px と mm":
                command_args += [
                    "--scale-bar-px",
                    bar_px_var.get().strip(),
                    "--scale-bar-mm",
                    known_mm_var.get().strip(),
                ]
            elif mode == "2点座標と既知 mm":
                command_args += [
                    "--scale-points",
                    points_var.get().strip(),
                    "--scale-bar-mm",
                    known_mm_var.get().strip(),
                ]
            elif mode == "器高から換算":
                command_args += ["--vessel-height-mm", vessel_height_var.get().strip()]
            if axis_var.get().strip():
                command_args += ["--axis-x", axis_var.get().strip()]
            if crop_var.get().strip():
                command_args += ["--crop", crop_var.get().strip()]
            if liquid_var.get().strip():
                command_args += ["--liquid-level-y", liquid_var.get().strip()]
            command_args += [
                "--closing-kernel",
                kernel_var.get().strip(),
                "--min-component-area",
                min_area_var.get().strip(),
                "--smooth-window",
                smooth_var.get().strip(),
                "--profile-mode",
                profile_mode_var.get(),
            ]
            if json_path:
                command_args += ["--json-out", json_path]
            if adaptive_var.get():
                command_args.append("--adaptive-threshold")
            if save_debug_var.get():
                debug_path = debug_var.get().strip() or str(
                    image_path.parent / "debug_out"
                )
                debug_var.set(debug_path)
                command_args += ["--debug-dir", debug_path]
        except Exception as exc:
            messagebox.showerror("設定を確認してください", str(exc), parent=root)
            return

        stdout_buffer, stderr_buffer = io.StringIO(), io.StringIO()
        calculate_button.configure(state="disabled")
        root.configure(cursor="watch")
        root.update_idletasks()
        try:
            with contextlib.redirect_stdout(stdout_buffer), contextlib.redirect_stderr(
                stderr_buffer
            ):
                _, result, _, _ = analyze(command_args)

            current_title = measurement_title_var.get().strip()
            if not current_title or title_is_automatic:
                resolved_title = image_path.stem
                set_automatic_title(resolved_title)
            else:
                resolved_title = current_title

            last_analysis_info = {
                "result": result,
                "image_name": image_path.name,
                "image_path": str(image_path),
                "title": resolved_title,
            }
            add_history_record(result, image_path)

            length_unit = result["units"]["length"]
            volume_unit = result["units"]["volume"]
            is_mm = "capacity_ml" in result

            metric_height_var.set(f"{result['vessel_height']:.2f} {length_unit}")
            metric_mouth_var.set(f"{result['mouth_diameter']:.2f} {length_unit}")
            metric_max_dia_var.set(f"{result['maximum_diameter']:.2f} {length_unit}")

            if is_mm:
                kpi_capacity_var.set(f"{result['capacity_ml']:.2f}")
                kpi_capacity_unit_var.set("mL")
                kpi_wall_var.set(f"{result['wall_volume_ml']:.2f}")
                kpi_wall_unit_var.set("mL")
                total_vol = result["capacity_ml"] + result["wall_volume_ml"]
                metric_total_vol_var.set(f"{total_vol:.2f} mL")
                metric_pappus_var.set(
                    f"{result['pappus_wall_volume_ml']:.2f} mL ({result['pappus_difference_percent']:.2f}%)"
                )
                scale_val = result.get("scale_mm_per_px")
                metric_scale_var.set(
                    f"{scale_val:.4f} mm/px" if scale_val else "mm指定"
                )
            else:
                kpi_capacity_var.set(f"{result['capacity']:.2f}")
                kpi_capacity_unit_var.set(volume_unit)
                kpi_wall_var.set(f"{result['wall_volume']:.2f}")
                kpi_wall_unit_var.set(volume_unit)
                total_vol = result["capacity"] + result["wall_volume"]
                metric_total_vol_var.set(f"{total_vol:.2f} {volume_unit}")
                metric_pappus_var.set(
                    f"{result['pappus_wall_volume']:.2f} {volume_unit} ({result['pappus_difference_percent']:.2f}%)"
                )
                metric_scale_var.set("未指定 (px)")

            log_lines = [f"対象ファイル: {image_path.name}"]
            if is_mm:
                log_lines.append(f"内腔容量 (cm³): {result['capacity_cm3']:.2f} cm³")
            if save_debug_var.get():
                log_lines.append(f"デバッグ画像出力先: {debug_var.get().strip()}")
            if json_path:
                log_lines.append(f"JSON出力先: {json_path}")

            if result.get("warnings"):
                log_lines += ["", "【注意・警告】"]
                log_lines.extend(f"・{warning}" for warning in result["warnings"])
            else:
                log_lines.append("輪郭・回転軸の検出は正常に完了しました。")

            show_log_text("\n".join(log_lines))

            if is_mm:
                completion_text = (
                    f"計算完了（{resolved_title}）: 容量 {result['capacity_ml']:.2f} mL / "
                    f"器壁体積 {result['wall_volume_ml']:.2f} mL"
                )
            else:
                completion_text = (
                    f"計算完了（{resolved_title}）: 容量 {result['capacity']:.2f} {volume_unit} / "
                    f"器壁体積 {result['wall_volume']:.2f} {volume_unit}"
                )
            set_status(completion_text, "success")
        except (Exception, SystemExit) as exc:
            show_log_text(f"エラー: {exc}\n\n{stderr_buffer.getvalue()}")
            set_status(f"計算エラー: {exc}", "error")
            messagebox.showerror("エラー", str(exc), parent=root)
        finally:
            root.configure(cursor="")
            calculate_button.configure(state="normal")

    calculate_button = ttk.Button(
        action_bar,
        text="体積・容量を計算する (Enter)",
        style="Primary.TButton",
        command=calculate,
    )
    calculate_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

    history_button = ttk.Button(
        action_bar,
        text="測定履歴",
        command=show_history,
    )
    history_button.grid(row=0, column=1, sticky="ns")

    root.bind("<Return>", lambda _event: calculate())
    root.mainloop()
