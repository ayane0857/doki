"""Tkinter GUI for pottery volume estimation."""

from __future__ import annotations

import ctypes
import math
import sys
from pathlib import Path
from typing import Callable

from pottery_volume_cli import analyze


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
