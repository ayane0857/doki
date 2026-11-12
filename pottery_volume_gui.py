"""Tkinter GUI for pottery volume estimation."""

from __future__ import annotations

import ctypes
import math
import sys
from pathlib import Path
from typing import Callable

from pottery_volume_cli import analyze
from pottery_volume_core import read_image


def pixel_distance(
    point_a: tuple[float, float], point_b: tuple[float, float]
) -> float:
    """Return the distance between two image points in pixels."""
    distance = math.hypot(point_b[0] - point_a[0], point_b[1] - point_a[1])
    if not math.isfinite(distance):
        raise ValueError("2点間の距離を計算できません。")
    return distance


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
    """Open a small desktop form for selecting an image and analysis settings."""
    import contextlib
    import io
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    available_fonts = set(tkfont.families(root))
    education_fonts = (
        "UD デジタル 教科書体 NP-R",
        "UD デジタル 教科書体 N-R",
        "BIZ UDPゴシック",
        "BIZ UDGothic",
    )
    default_font = tkfont.nametofont("TkDefaultFont").cget("family")
    ui_font = next(
        (name for name in education_fonts if name in available_fonts), default_font
    )
    root.option_add("*Font", (ui_font, 11))
    style = ttk.Style(root)
    style.configure(".", font=(ui_font, 11))
    style.configure("TLabel", font=(ui_font, 11))
    style.configure("TButton", font=(ui_font, 11))
    style.configure("TEntry", font=(ui_font, 11))
    style.configure("TCombobox", font=(ui_font, 11))
    style.configure("TLabelframe.Label", font=(ui_font, 11, "bold"))
    root.title("土器体積推定")
    root.geometry("780x770")
    root.minsize(720, 680)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(0, weight=1)

    image_var = tk.StringVar(value=str(initial_image or ""))
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
    save_debug_var = tk.BooleanVar(value=True)
    adaptive_var = tk.BooleanVar(value=False)

    outer = ttk.Frame(root, padding=12)
    outer.grid(row=0, column=0, sticky="nsew")
    outer.columnconfigure(1, weight=1)
    outer.rowconfigure(12, weight=1)

    ttk.Label(outer, text="入力画像（ここへドロップ可）").grid(
        row=0, column=0, sticky="w", pady=4
    )
    ttk.Entry(outer, textvariable=image_var).grid(row=0, column=1, sticky="ew", padx=6)

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

    ttk.Button(outer, text="画像を選択…", command=browse_image).grid(
        row=0, column=2, padx=4
    )

    def handle_dropped_files(paths: list[str]) -> None:
        image_path = next(
            (
                Path(path)
                for path in paths
                if Path(path).suffix.lower()
                in {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}
            ),
            None,
        )
        if image_path is None:
            return
        image_var.set(str(image_path))
        if not debug_var.get().strip():
            debug_var.set(str(image_path.parent / "debug_out"))

    root.update_idletasks()
    _enable_windows_file_drop(root, handle_dropped_files)

    scale_frame = ttk.LabelFrame(outer, text="スケール")
    scale_frame.grid(row=1, column=0, columnspan=3, sticky="ew", pady=8)
    scale_frame.columnconfigure(1, weight=1)
    ttk.Label(scale_frame, text="指定方法").grid(
        row=0, column=0, sticky="w", padx=8, pady=4
    )
    scale_combo = ttk.Combobox(
        scale_frame,
        textvariable=scale_mode_var,
        values=(
            "px（スケール未指定）",
            "mm/px を直接指定",
            "スケール線の px と mm",
            "2点座標と既知 mm",
            "器高から換算",
        ),
        state="readonly",
        width=25,
    )
    scale_combo.grid(row=0, column=1, sticky="w", padx=6, pady=4)

    scale_entries: dict[str, ttk.Frame] = {}
    for key, label_text, variable, hint in (
        ("direct", "mm/px", direct_scale_var, "例: 0.5"),
        ("bar", "スケール線 (px, mm)", bar_px_var, "px"),
        ("points", "2点 x0,y0,x1,y1 と既知 mm", points_var, "例: 40,20,140,20"),
        ("height", "器高 (mm)", vessel_height_var, "例: 120"),
    ):
        row_frame = ttk.Frame(scale_frame)
        row_frame.columnconfigure(1, weight=1)
        ttk.Label(row_frame, text=label_text).grid(
            row=0, column=0, sticky="w", padx=(8, 6), pady=4
        )
        ttk.Entry(row_frame, textvariable=variable, width=20).grid(
            row=0, column=1, sticky="w", pady=4
        )
        ttk.Label(row_frame, text=hint).grid(row=0, column=2, sticky="w", padx=6)
        if key == "bar":
            ttk.Label(row_frame, text="実寸 mm").grid(
                row=0, column=3, sticky="w", padx=(10, 4)
            )
            ttk.Entry(row_frame, textvariable=known_mm_var, width=12).grid(
                row=0, column=4, sticky="w", padx=4
            )
        elif key == "points":
            ttk.Label(row_frame, text="実寸 mm").grid(
                row=0, column=3, sticky="w", padx=(10, 4)
            )
            ttk.Entry(row_frame, textvariable=known_mm_var, width=12).grid(
                row=0, column=4, sticky="w", padx=4
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
            scale_entries[key].grid(row=1, column=0, columnspan=2, sticky="ew")

    scale_mode_var.trace_add("write", update_scale_rows)
    update_scale_rows()

    def open_measurement_tool() -> None:
        import base64
        import tkinter as tk
        from tkinter import messagebox, ttk

        image_text = image_var.get().strip().strip('"')
        if not image_text:
            messagebox.showerror(
                "画像が未指定です",
                "先に画像を選択してください。",
                parent=root,
            )
            return
        image_path = Path(image_text)
        if not image_path.is_file():
            messagebox.showerror("画像が見つかりません", image_text, parent=root)
            return

        try:
            import cv2
            import numpy as np

            image = cv2.imdecode(
                np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_COLOR
            )
            if image is None:
                raise ValueError("画像を読み込めません。")
            success, encoded = cv2.imencode(".png", image)
            if not success:
                raise ValueError("画像を表示用に変換できません。")
            image_data = base64.b64encode(encoded).decode("ascii")
            image_height, image_width = image.shape[:2]
        except (OSError, ValueError) as exc:
            messagebox.showerror("画像を開けません", str(exc), parent=root)
            return

        window = tk.Toplevel(root)
        window.title("画像上でスケールを測定")
        window.geometry("1000x760")
        window.minsize(620, 420)
        window.transient(root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)

        ttk.Label(
            window,
            text="画像上の2点をクリックしてください。クリック位置は元画像のpxです。",
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=8)

        canvas_frame = ttk.Frame(window)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 0), pady=4)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(canvas_frame, background="#303030", highlightthickness=0)
        x_scroll = ttk.Scrollbar(
            canvas_frame, orient="horizontal", command=canvas.xview
        )
        y_scroll = ttk.Scrollbar(canvas_frame, orient="vertical", command=canvas.yview)
        canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        photo = tk.PhotoImage(data=image_data)
        canvas.create_image(0, 0, image=photo, anchor="nw")
        canvas.configure(scrollregion=(0, 0, image_width, image_height))
        canvas.image = photo

        measurement_frame = ttk.Frame(window, padding=(10, 4))
        measurement_frame.grid(row=1, column=1, sticky="ns")
        measurement_frame.columnconfigure(1, weight=1)
        point_a: tuple[float, float] | None = None
        point_b: tuple[float, float] | None = None
        marker_ids: list[int] = []
        status_var = tk.StringVar(value="1点目をクリックしてください。")
        distance_var = tk.StringVar(value="—")
        measured_mm_var = tk.StringVar()

        ttk.Label(
            measurement_frame, textvariable=status_var, wraplength=220
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 12))
        ttk.Label(measurement_frame, text="画像上の距離").grid(
            row=1, column=0, sticky="w", pady=3
        )
        ttk.Label(measurement_frame, textvariable=distance_var).grid(
            row=1, column=1, sticky="e", pady=3
        )
        ttk.Label(measurement_frame, text="実寸 mm（任意）").grid(
            row=2, column=0, sticky="w", pady=3
        )
        ttk.Entry(measurement_frame, textvariable=measured_mm_var, width=12).grid(
            row=2, column=1, sticky="e", pady=3
        )

        def clear_points() -> None:
            nonlocal point_a, point_b
            point_a = point_b = None
            for marker_id in marker_ids:
                canvas.delete(marker_id)
            marker_ids.clear()
            distance_var.set("—")
            status_var.set("1点目をクリックしてください。")

        def on_canvas_click(event: object) -> None:
            nonlocal point_a, point_b
            x = float(canvas.canvasx(event.x))  # type: ignore[attr-defined]
            y = float(canvas.canvasy(event.y))  # type: ignore[attr-defined]
            if point_a is None or point_b is not None:
                clear_points()
                point_a = (x, y)
                marker_ids.append(
                    canvas.create_oval(x - 5, y - 5, x + 5, y + 5, outline="#ff3030", width=2)
                )
                status_var.set("2点目をクリックしてください。")
                return
            point_b = (x, y)
            marker_ids.append(
                canvas.create_oval(x - 5, y - 5, x + 5, y + 5, outline="#ff3030", width=2)
            )
            marker_ids.append(
                canvas.create_line(
                    point_a[0], point_a[1], point_b[0], point_b[1], fill="#ff3030", width=2
                )
            )
            distance = pixel_distance(point_a, point_b)
            distance_var.set(f"{distance:.2f} px")
            status_var.set("測定完了。必要なら実寸mmを入力して適用してください。")

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
            window.destroy()

        ttk.Button(measurement_frame, text="点をリセット", command=clear_points).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(14, 4)
        )
        ttk.Button(
            measurement_frame, text="スケール設定へ反映", command=apply_measurement
        ).grid(row=4, column=0, columnspan=2, sticky="ew", pady=4)
        ttk.Button(measurement_frame, text="閉じる", command=window.destroy).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=4
        )
        canvas.bind("<Button-1>", on_canvas_click)

    ttk.Button(
        scale_frame, text="画像上で測定…", command=open_measurement_tool
    ).grid(row=0, column=2, padx=6, pady=4)

    def open_scale_reader() -> None:
        import base64
        import threading
        import tkinter as tk
        from tkinter import messagebox, ttk

        image_text = image_var.get().strip().strip('"')
        if not image_text:
            messagebox.showerror(
                "画像が未指定です", "先に画像を選択してください。", parent=root
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
        window.title("画像からスケールを読み取る")
        window.geometry("1120x760")
        window.minsize(760, 520)
        window.transient(root)
        window.columnconfigure(0, weight=1)
        window.rowconfigure(1, weight=1)
        ttk.Label(
            window,
            text="OCRで長さと単位を読み、候補の目盛り線を選びます。赤線の両端は画像上でクリックして調整できます。",
            wraplength=1080,
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=10, pady=8)

        canvas_frame = ttk.Frame(window)
        canvas_frame.grid(row=1, column=0, sticky="nsew", padx=(10, 0), pady=4)
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)
        canvas = tk.Canvas(canvas_frame, background="#303030", highlightthickness=0)
        x_scroll = ttk.Scrollbar(
            canvas_frame, orient="horizontal", command=canvas.xview
        )
        y_scroll = ttk.Scrollbar(
            canvas_frame, orient="vertical", command=canvas.yview
        )
        canvas.configure(xscrollcommand=x_scroll.set, yscrollcommand=y_scroll.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll.grid(row=1, column=0, sticky="ew")

        panel = ttk.Frame(window, padding=(12, 4))
        panel.grid(row=1, column=1, sticky="ns")
        panel.columnconfigure(0, weight=1)
        label_candidates: list[object] = []
        bar_candidates: list[object] = []
        overlay_ids: list[int] = []
        manual_points: list[tuple[float, float]] = []
        display_scale = 1.0
        zoom_scale: float | None = None
        min_zoom_scale = 0.05
        max_rendered_pixels = 16_000_000
        display_photo: tk.PhotoImage | None = None
        display_image_id = canvas.create_image(0, 0, anchor="nw")
        resize_job: str | None = None
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
            available_width = canvas.winfo_width()
            available_height = canvas.winfo_height()
            if available_width <= 1 or available_height <= 1:
                return
            fit_scale = min(
                1.0,
                available_width / image_width,
                available_height / image_height,
            )
            new_scale = fit_scale if zoom_scale is None else zoom_scale
            if abs(new_scale - display_scale) < 1e-6 and display_photo is not None:
                return
            display_scale = new_scale
            display_width = max(1, round(image_width * display_scale))
            display_height = max(1, round(image_height * display_scale))
            if display_scale == 1.0:
                display_image = image
            else:
                display_image = cv2.resize(
                    image, (display_width, display_height), interpolation=cv2.INTER_AREA
                )
            success, encoded = cv2.imencode(".png", display_image)
            if not success:
                raise ValueError("画像を表示用に変換できません。")
            display_photo = tk.PhotoImage(
                data=base64.b64encode(encoded).decode("ascii")
            )
            canvas.itemconfigure(display_image_id, image=display_photo)
            canvas.configure(scrollregion=(0, 0, display_width, display_height))
            redraw_overlay()

        def set_zoom(scale: float | None) -> None:
            nonlocal zoom_scale
            zoom_scale = scale
            refresh_display_image()

        def zoom_in() -> None:
            max_zoom_scale = math.sqrt(
                max_rendered_pixels / (image_width * image_height)
            )
            if display_scale < max_zoom_scale:
                set_zoom(min(display_scale * 1.25, max_zoom_scale))

        def zoom_out() -> None:
            if display_scale >= min_zoom_scale:
                set_zoom(max(display_scale / 1.25, min_zoom_scale))

        def schedule_display_refresh(_event: object | None = None) -> None:
            nonlocal resize_job
            if resize_job is None:
                resize_job = window.after_idle(refresh_display_image)

        ttk.Label(panel, text="OCRで読み取った長さ").grid(
            row=0, column=0, sticky="w", pady=(4, 2)
        )
        ocr_summary = ttk.Label(
            panel, textvariable=ocr_summary_var, wraplength=300, justify="left"
        )
        ocr_summary.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        label_combo = ttk.Combobox(
            panel,
            textvariable=label_choice_var,
            state="readonly",
            width=35,
        )
        label_combo.grid(row=2, column=0, sticky="ew", pady=2)
        ttk.Label(panel, text="距離の数値と単位（必要なら修正）").grid(
            row=3, column=0, sticky="w", pady=(10, 2)
        )
        length_row = ttk.Frame(panel)
        length_row.grid(row=4, column=0, sticky="ew")
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
            row=5, column=0, sticky="w", pady=(12, 2)
        )
        bar_combo = ttk.Combobox(
            panel,
            textvariable=bar_choice_var,
            state="readonly",
            width=35,
        )
        bar_combo.grid(row=6, column=0, sticky="ew", pady=2)
        ttk.Label(panel, text="画像上の長さ").grid(
            row=7, column=0, sticky="w", pady=(10, 0)
        )
        ttk.Label(panel, textvariable=bar_length_var).grid(
            row=8, column=0, sticky="w"
        )
        ttk.Label(
            panel,
            textvariable=points_status_var,
            wraplength=300,
            justify="left",
        ).grid(row=9, column=0, sticky="ew", pady=(8, 2))
        ttk.Label(
            panel,
            textvariable=scale_result_var,
            font=(ui_font, 13, "bold"),
        ).grid(row=10, column=0, sticky="w", pady=(8, 12))

        def current_label():
            index = label_combo.current()
            return label_candidates[index] if 0 <= index < len(label_candidates) else None

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
                color = "#e0a020" if index != bar_combo.current() else "#ff3030"
                width = 1 if index != bar_combo.current() else 3
                x1, y1 = display_point(candidate.x1, candidate.y1)
                x2, y2 = display_point(candidate.x2, candidate.y2)
                overlay_ids.append(
                    canvas.create_line(
                        x1,
                        y1,
                        x2,
                        y2,
                        fill=color,
                        width=width,
                    )
                )
            label = current_label()
            if label is not None:
                x0, y0, x1, y1 = label.bounds
                x0, y0 = display_point(x0, y0)
                x1, y1 = display_point(x1, y1)
                overlay_ids.append(
                    canvas.create_rectangle(
                        x0, y0, x1, y1, outline="#20c080", width=2
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
                            x - 5, y - 5, x + 5, y + 5, outline="#ff3030", width=2
                        )
                    )
                overlay_ids.append(
                    canvas.create_line(x0, y0, x1, y1, fill="#ff3030", width=3)
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
                scale_result_var.set("mm/px: 数値と単位を確認してください")
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
                    "赤線の両端を確認してください。線をクリックすると両端を手動指定できます。"
                )
            else:
                bar_combo.set("")
                points_status_var.set(
                    "目盛り線を自動検出できませんでした。画像上で線の両端を順にクリックしてください。"
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
                points_status_var.set("始点を設定しました。終点をクリックしてください。")
            else:
                points_status_var.set(
                    "画像上で始点・終点を指定しました。結果を確認して反映してください。"
                )
            redraw_overlay()
            update_scale_result()

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
            window.destroy()

        label_combo.bind("<<ComboboxSelected>>", on_label_selected)
        bar_combo.bind("<<ComboboxSelected>>", on_bar_selected)
        value_var.trace_add("write", update_scale_result)
        unit_var.trace_add("write", update_scale_result)
        canvas.bind("<Button-1>", on_canvas_click)
        canvas_frame.bind("<Configure>", schedule_display_refresh)
        ttk.Button(panel, text="mm/pxとして反映", command=apply_scale).grid(
            row=11, column=0, sticky="ew", pady=3
        )
        ttk.Button(panel, text="閉じる", command=window.destroy).grid(
            row=12, column=0, sticky="ew", pady=3
        )
        zoom_frame = ttk.Frame(panel)
        zoom_frame.grid(row=13, column=0, sticky="ew", pady=(10, 3))
        ttk.Label(zoom_frame, text="画像表示").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Button(
            zoom_frame, text="全体表示", command=lambda: set_zoom(None)
        ).grid(row=1, column=0, sticky="ew", padx=(0, 2), pady=2)
        ttk.Button(
            zoom_frame, text="原寸", command=lambda: set_zoom(1.0)
        ).grid(row=1, column=1, sticky="ew", padx=(2, 0), pady=2)
        ttk.Button(zoom_frame, text="拡大", command=zoom_in).grid(
            row=2, column=0, sticky="ew", padx=(0, 2)
        )
        ttk.Button(zoom_frame, text="縮小", command=zoom_out).grid(
            row=2, column=1, sticky="ew", padx=(2, 0)
        )
        zoom_frame.columnconfigure(0, weight=1)
        zoom_frame.columnconfigure(1, weight=1)
        window.update_idletasks()
        refresh_display_image()

        def finish_detection(labels: list[object], bars: list[object]) -> None:
            if not window.winfo_exists():
                return
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
                    + " / ".join(f"{item.text} ({item.confidence:.0%})" for item in labels)
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

    ttk.Button(
        scale_frame,
        text="画像から自動設定…",
        command=open_scale_reader,
    ).grid(row=1, column=2, padx=6, pady=4, sticky="ns")

    detection = ttk.LabelFrame(outer, text="自動検出の調整（必要な場合のみ）")
    detection.grid(row=2, column=0, columnspan=3, sticky="ew", pady=4)
    detection.columnconfigure(1, weight=1)

    def add_setting(
        row: int, title: str, variable: tk.StringVar, hint: str = ""
    ) -> None:
        ttk.Label(detection, text=title).grid(
            row=row, column=0, sticky="w", padx=8, pady=3
        )
        ttk.Entry(detection, textvariable=variable, width=30).grid(
            row=row, column=1, sticky="w", padx=6, pady=3
        )
        if hint:
            ttk.Label(detection, text=hint).grid(
                row=row, column=2, sticky="w", padx=6, pady=3
            )

    add_setting(0, "回転軸 x (px)", axis_var, "空欄なら自動検出")
    add_setting(1, "断面 crop x0,y0,x1,y1", crop_var, "空欄なら画像全体")
    add_setting(2, "液面 y (px)", liquid_var, "空欄なら口縁")

    options = ttk.Frame(detection)
    options.grid(row=3, column=0, columnspan=3, sticky="ew", padx=8, pady=5)
    ttk.Label(options, text="クロージング").pack(side="left")
    ttk.Entry(options, textvariable=kernel_var, width=5).pack(side="left", padx=(4, 14))
    ttk.Label(options, text="最小成分").pack(side="left")
    ttk.Entry(options, textvariable=min_area_var, width=5).pack(
        side="left", padx=(4, 14)
    )
    ttk.Label(options, text="平滑化窓").pack(side="left")
    ttk.Entry(options, textvariable=smooth_var, width=5).pack(side="left", padx=(4, 14))
    ttk.Label(options, text="輪郭モード").pack(side="left")
    ttk.Combobox(
        options,
        textvariable=profile_mode_var,
        values=("auto", "filled", "lines"),
        state="readonly",
        width=9,
    ).pack(side="left", padx=4)
    ttk.Checkbutton(detection, text="適応的二値化を使う", variable=adaptive_var).grid(
        row=4, column=0, columnspan=2, sticky="w", padx=8, pady=4
    )

    output = ttk.LabelFrame(outer, text="出力")
    output.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
    output.columnconfigure(1, weight=1)
    ttk.Label(output, text="JSON（任意）").grid(
        row=0, column=0, sticky="w", padx=8, pady=4
    )
    ttk.Entry(output, textvariable=json_var).grid(row=0, column=1, sticky="ew", padx=6)
    ttk.Checkbutton(output, text="デバッグ画像も保存", variable=save_debug_var).grid(
        row=1, column=0, sticky="w", padx=8, pady=4
    )
    ttk.Entry(output, textvariable=debug_var).grid(row=1, column=1, sticky="ew", padx=6)

    result_box = tk.Text(outer, height=10, wrap="word", state="disabled")
    result_box.grid(row=12, column=0, columnspan=3, sticky="nsew", pady=(8, 4))

    def show_text(value: str) -> None:
        result_box.configure(state="normal")
        result_box.delete("1.0", "end")
        result_box.insert("1.0", value)
        result_box.configure(state="disabled")

    def calculate() -> None:
        image_text = image_var.get().strip().strip('"')
        if not image_text:
            messagebox.showerror(
                "画像が未指定です",
                "画像を選ぶか、画像のパスを入力してください。",
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
            length_unit = result["units"]["length"]
            volume_unit = result["units"]["volume"]
            lines = [
                "推定結果",
                f"器高: {result['vessel_height']:.2f} {length_unit}",
                f"口径: {result['mouth_diameter']:.2f} {length_unit}",
                f"最大径: {result['maximum_diameter']:.2f} {length_unit}",
                f"容量: {result['capacity']:.2f} {volume_unit}",
                f"器壁体積: {result['wall_volume']:.2f} {volume_unit}",
                f"パップス検算との差: {result['pappus_difference_percent']:.2f}%",
            ]
            if "capacity_ml" in result:
                lines += [
                    f"容量: {result['capacity_ml']:.2f} mL",
                    f"器壁体積: {result['wall_volume_ml']:.2f} mL",
                ]
            if json_path:
                lines += ["", f"JSON: {json_path}"]
            if save_debug_var.get():
                lines.append(f"デバッグ画像: {debug_var.get().strip()}")
            if result.get("warnings"):
                lines += ["", "警告:"]
                lines.extend(f"・{warning}" for warning in result["warnings"])
            show_text("\n".join(lines))
        except (Exception, SystemExit) as exc:
            show_text(f"エラー: {exc}\n\n{stderr_buffer.getvalue()}")
            messagebox.showerror("エラー", str(exc), parent=root)
        finally:
            root.configure(cursor="")
            calculate_button.configure(state="normal")

    buttons = ttk.Frame(outer)
    buttons.grid(row=13, column=0, columnspan=3, sticky="e", pady=6)
    calculate_button = ttk.Button(buttons, text="計算する", command=calculate)
    calculate_button.pack(side="left", padx=4)
    ttk.Button(buttons, text="閉じる", command=root.destroy).pack(side="left", padx=4)

    root.bind("<Return>", lambda _event: calculate())
    root.mainloop()
