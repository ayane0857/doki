from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import threading
import queue
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

PAYLOAD_BASE_URL = "https://file.ayane0857.net/app/doki/windows"
PAYLOAD_ZIP_NAME = "PotteryVolume-GUI-Windows.zip"
PAYLOAD_VERSION_NAME = "BOOTSTRAP_VERSION"
LAST_RELEASE_NAME = ".last-successful-release"
INSTALL_LOCATION_NAME = "install-location.txt"


def _resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def payload_version() -> str:
    path = _resource_path(PAYLOAD_VERSION_NAME)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return "dev"


def cache_root() -> Path:
    base_root = default_cache_root()
    install_location = base_root / INSTALL_LOCATION_NAME
    try:
        configured = install_location.read_text(encoding="utf-8").strip()
        if configured:
            return Path(configured).expanduser()
    except (OSError, UnicodeDecodeError):
        pass
    return base_root


def default_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "PotteryVolume"
    return Path.home() / ".cache" / "PotteryVolume"


def ensure_install_location() -> Path:
    base_root = default_cache_root()
    base_root.mkdir(parents=True, exist_ok=True)
    install_location = base_root / INSTALL_LOCATION_NAME

    try:
        configured = install_location.read_text(encoding="utf-8").strip()
        if configured:
            return Path(configured).expanduser()
    except (OSError, UnicodeDecodeError):
        pass

    if sys.platform != "win32":
        return base_root

    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(
            parent=root,
            initialdir=str(base_root),
            title="PotteryVolume のインストール先を選択",
        )
        root.destroy()
    except (ImportError, tk.TclError):
        return base_root

    install_root = Path(selected).expanduser() if selected else base_root
    install_root.mkdir(parents=True, exist_ok=True)
    try:
        install_location.write_text(str(install_root), encoding="utf-8")
    except OSError:
        pass
    return install_root


@contextmanager
def preparation_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".prepare.lock"
    if sys.platform == "win32":
        mutex_name = "Local\\PotteryVolumePayload-" + hashlib.sha256(str(root).lower().encode()).hexdigest()
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            raise OSError("共有キャッシュのロックを作成できませんでした。")
        try:
            wait_result = ctypes.windll.kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            if wait_result not in (0, 0x80):
                raise OSError("共有キャッシュのロックを取得できませんでした。")
            yield
        finally:
            ctypes.windll.kernel32.ReleaseMutex(handle)
            ctypes.windll.kernel32.CloseHandle(handle)
    else:
        import fcntl

        with lock_path.open("a+", encoding="ascii") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def resolve_payload_version(version: str) -> str:
    selected = version
    if selected == "dev":
        with urllib.request.urlopen(PAYLOAD_BASE_URL + "/latest/release.txt", timeout=60) as response:
            selected = response.read().decode("ascii").strip()
    if len(selected) != 40 or any(character not in "0123456789abcdefABCDEF" for character in selected):
        raise RuntimeError("公開されたペイロードのバージョンが不正です。")
    return selected.lower()


def safe_extract(zip_path: Path, destination: Path) -> None:
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if destination_resolved not in target.parents:
                raise RuntimeError("ZIP contains an invalid path.")
        archive.extractall(destination)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256_metadata(metadata: str) -> str:
    fields = metadata.strip().split()
    if not fields:
        raise RuntimeError("ダウンロードファイルのSHA-256メタデータが空です。")

    expected = fields[0].lower()
    if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
        raise RuntimeError("ダウンロードファイルのSHA-256メタデータが不正です。")
    return expected


def valid_payload_directory(root: Path, version: str) -> Path | None:
    if len(version) != 40 or any(character not in "0123456789abcdef" for character in version):
        return None
    payload_dir = root / "payload" / version
    marker = payload_dir / ".ready"
    executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    if marker.is_file() and executable.is_file():
        try:
            if marker.read_text(encoding="ascii").strip() == version:
                return executable
        except (OSError, UnicodeDecodeError):
            return None
    return None


def recorded_release(root: Path) -> Path | None:
    try:
        version = (root / LAST_RELEASE_NAME).read_text(encoding="ascii").strip().lower()
    except (OSError, UnicodeDecodeError):
        return None
    return valid_payload_directory(root, version)


def write_release_record(root: Path, version: str) -> None:
    try:
        root.mkdir(parents=True, exist_ok=True)
        temporary = root / (LAST_RELEASE_NAME + ".tmp")
        temporary.write_text(version, encoding="ascii")
        temporary.replace(root / LAST_RELEASE_NAME)
    except OSError:
        pass


def normalize_forwarded_arguments(arguments: list[str], caller_cwd: Path) -> list[str]:
    path_options = {"--debug-dir", "--json-out"}
    value_options = {
        "--scale-mm-per-px", "--scale-bar-px", "--scale-bar-mm",
        "--scale-points", "--vessel-height-mm", "--axis-x", "--crop",
        "--liquid-level-y", "--closing-kernel", "--profile-mode",
        "--min-component-area", "--smooth-window",
    }
    value_options.update(path_options)

    normalized = []
    index = 0
    positional_pending = True
    while index < len(arguments):
        argument = arguments[index]
        if argument in path_options and index + 1 < len(arguments):
            normalized.extend([argument, str((caller_cwd / arguments[index + 1]).resolve())])
            index += 2
        elif argument.startswith("--debug-dir=") or argument.startswith("--json-out="):
            option, value = argument.split("=", 1)
            normalized.append(f"{option}={str((caller_cwd / value).resolve())}")
            index += 1
        elif argument in value_options:
            normalized.append(argument)
            index += 1
            if index < len(arguments):
                normalized.append(arguments[index])
                index += 1
        elif argument.startswith("-"):
            normalized.append(argument)
            index += 1
        elif positional_pending:
            normalized.append(str((caller_cwd / argument).resolve()))
            positional_pending = False
            index += 1
        else:
            normalized.append(argument)
            index += 1
    return normalized


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "PotteryVolume-Bootstrap"})
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)


def show_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, message, "PotteryVolume", 0x10)
    else:
        print(message, file=sys.stderr)


def prepare_payload_with_loading_window() -> Path:
    if sys.platform != "win32":
        return prepare_payload()

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return prepare_payload()

    try:
        root = tk.Tk()
        root.title("PotteryVolume")
        root.resizable(False, False)
        root.geometry("360x110")
        root.attributes("-topmost", True)

        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="アプリケーションを準備しています...",
            anchor="center",
        ).pack(fill="x", pady=(0, 12))
        progress = ttk.Progressbar(frame, mode="indeterminate", length=300)
        progress.pack()
        progress.start(10)
    except tk.TclError:
        return prepare_payload()

    outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def prepare() -> None:
        try:
            outcome.put((True, prepare_payload()))
        except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as error:
            outcome.put((False, error))

    worker = threading.Thread(target=prepare, daemon=True)
    worker.start()

    result = None
    while worker.is_alive():
        root.update()
        worker.join(timeout=0.05)

    if not outcome.empty():
        succeeded, result = outcome.get()
        if not succeeded:
            root.destroy()
            if isinstance(result, Exception):
                raise result
            raise RuntimeError("アプリケーションの準備中にエラーが発生しました。")

    root.destroy()
    if not isinstance(result, Path):
        raise RuntimeError("ダウンロードされたアプリの準備に失敗しました。")
    return result


def prepare_payload() -> Path:
    version = payload_version()
    root = cache_root()
    with preparation_lock(root):
        try:
            selected_version = resolve_payload_version(version)
        except (OSError, TimeoutError, urllib.error.URLError, UnicodeDecodeError, RuntimeError) as lookup_error:
            if version == "dev":
                fallback = recorded_release(root)
                if fallback is not None:
                    return fallback
            raise lookup_error
        payload_dir = root / "payload" / selected_version
        cached_executable = valid_payload_directory(root, selected_version)
        if cached_executable is not None:
            write_release_record(root, selected_version)
            return cached_executable

        release_base = PAYLOAD_BASE_URL + "/releases/" + selected_version
        archive = root / f"{PAYLOAD_ZIP_NAME}.{selected_version}.part"
        checksum = root / f"{PAYLOAD_ZIP_NAME}.{selected_version}.sha256.part"
        staging = root / "payload" / f".{selected_version}.part"

        download(release_base + "/" + PAYLOAD_ZIP_NAME, archive)
        download(release_base + "/" + PAYLOAD_ZIP_NAME + ".sha256", checksum)

        try:
            checksum_metadata = checksum.read_text(encoding="ascii")
        except UnicodeDecodeError as error:
            raise RuntimeError("ダウンロードファイルのSHA-256メタデータが不正です。") from error
        expected = parse_sha256_metadata(checksum_metadata)
        actual = sha256(archive)
        if actual != expected:
            raise RuntimeError("ダウンロードファイルのSHA-256検証に失敗しました。")

        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        safe_extract(archive, staging)

        if payload_dir.exists():
            shutil.rmtree(payload_dir)
        staging.rename(payload_dir)
        archive.unlink(missing_ok=True)
        checksum.unlink(missing_ok=True)

        executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
        if not executable.is_file():
            raise RuntimeError("ダウンロードされたアプリにEXEが見つかりませんでした。")
        (payload_dir / ".ready").write_text(selected_version, encoding="ascii")
        usable_executable = valid_payload_directory(root, selected_version)
        if usable_executable is None:
            raise RuntimeError("ダウンロードされたペイロードの検証に失敗しました。")
        write_release_record(root, selected_version)
        return usable_executable


def main() -> int:
    try:
        if sys.platform == "win32":
            ensure_install_location()
        executable = prepare_payload_with_loading_window()
        caller_cwd = Path.cwd()
        normalized = normalize_forwarded_arguments(sys.argv[1:], caller_cwd)
        subprocess.Popen([str(executable), *normalized], cwd=str(executable.parent))
        return 0
    except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as error:
        show_error(
            "PotteryVolumeの実行に必要なファイルをダウンロードできませんでした。\n\n"
            f"{error}\n\nインターネット接続を確認してください。"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
