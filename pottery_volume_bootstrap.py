from __future__ import annotations

import ctypes
import hashlib
import os
import queue
import shutil
import subprocess
import sys
import threading
import urllib.error
import urllib.request
import zipfile
from contextlib import contextmanager
from pathlib import Path

PAYLOAD_BASE_URL = "https://file.ayane0857.net/app/doki/windows"
PAYLOAD_ZIP_NAME = "PotteryVolume-GUI-Windows.zip"
PAYLOAD_VERSION_NAME = "BOOTSTRAP_VERSION"
LAST_RELEASE_NAME = ".last-successful-release"
PAYLOAD_KEEP_COUNT = 2


def _resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def payload_version() -> str:
    path = _resource_path(PAYLOAD_VERSION_NAME)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return "dev"


def cache_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return default_cache_root()


def default_cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "PotteryVolume"
    return Path.home() / ".cache" / "PotteryVolume"


@contextmanager
def preparation_lock(root: Path):
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".prepare.lock"
    if sys.platform == "win32":
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel32.WaitForSingleObject.restype = ctypes.c_uint32
        kernel32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel32.ReleaseMutex.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int
        normalized_root = os.path.normcase(str(root.resolve()))
        mutex_name = "Local\\PotteryVolumePayload-" + hashlib.sha256(normalized_root.encode()).hexdigest()
        handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not handle:
            raise OSError(ctypes.get_last_error(), "共有キャッシュのロックを作成できませんでした。")
        try:
            wait_result = kernel32.WaitForSingleObject(handle, 0xFFFFFFFF)
            if wait_result not in (0, 0x80):
                raise OSError(ctypes.get_last_error(), "共有キャッシュのロックを取得できませんでした。")
            yield
        finally:
            kernel32.ReleaseMutex(handle)
            kernel32.CloseHandle(handle)
    else:
        import fcntl

        with lock_path.open("a+", encoding="ascii") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def resolve_payload_version(version: str = "latest") -> str:
    selected = version
    if selected in {"dev", "latest"}:
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
                raise RuntimeError("ZIPに不正なパスが含まれています。")
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
    if len(version) != 40 or any(character not in "0123456789abcdef" for character in version):
        raise RuntimeError("記録するペイロードのバージョンが不正です。")
    root.mkdir(parents=True, exist_ok=True)
    temporary = root / (LAST_RELEASE_NAME + ".tmp")
    try:
        temporary.write_text(version, encoding="ascii")
        temporary.replace(root / LAST_RELEASE_NAME)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def _payload_version_names(root: Path) -> set[str]:
    try:
        return {path.name for path in (root / "payload").iterdir()}
    except OSError:
        return set()


def _running_payload_versions(root: Path) -> set[str]:
    if sys.platform != "win32":
        return set()

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        dword = ctypes.c_uint32
        bytes_returned = dword()
        psapi.EnumProcesses.argtypes = [ctypes.POINTER(dword), dword, ctypes.POINTER(dword)]
        psapi.EnumProcesses.restype = ctypes.c_int
        capacity = 4096
        while True:
            process_ids = (dword * capacity)()
            if not psapi.EnumProcesses(
                process_ids,
                ctypes.sizeof(process_ids),
                ctypes.byref(bytes_returned),
            ):
                return _payload_version_names(root)
            if bytes_returned.value < ctypes.sizeof(process_ids):
                break
            capacity *= 2
            if capacity > 65536:
                raise OSError("実行中プロセスを一覧できませんでした。")

        kernel32.OpenProcess.argtypes = [dword, ctypes.c_int, dword]
        kernel32.OpenProcess.restype = ctypes.c_void_p
        kernel32.QueryFullProcessImageNameW.argtypes = [
            ctypes.c_void_p,
            dword,
            ctypes.POINTER(ctypes.c_wchar),
            ctypes.POINTER(dword),
        ]
        kernel32.QueryFullProcessImageNameW.restype = ctypes.c_int
        kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
        kernel32.CloseHandle.restype = ctypes.c_int

        protected: set[str] = set()
        payload_root = os.path.normcase(str((root / "payload").resolve()))
        count = min(bytes_returned.value // ctypes.sizeof(dword), len(process_ids))
        for process_id in process_ids[:count]:
            process = kernel32.OpenProcess(0x1000, False, process_id)
            if not process:
                continue
            try:
                image_buffer = ctypes.create_unicode_buffer(32768)
                image_length = dword(len(image_buffer))
                if not kernel32.QueryFullProcessImageNameW(
                    process,
                    0,
                    image_buffer,
                    ctypes.byref(image_length),
                ):
                    continue
                image_path = os.path.normcase(os.path.abspath(image_buffer.value))
                if not image_path.startswith(payload_root + os.sep):
                    continue
                executable = Path(image_buffer.value)
                if executable.name.casefold() == "potteryvolume_gui.exe":
                    version = executable.parent.parent.name.lower()
                    if len(version) == 40 and all(char in "0123456789abcdef" for char in version):
                        protected.add(version)
            finally:
                kernel32.CloseHandle(process)
        return protected
    except (AttributeError, OSError, TypeError, ValueError):
        # If process enumeration is unavailable, leave old payloads in place.
        return _payload_version_names(root)


def cleanup_old_payloads(root: Path, current_version: str, keep_count: int = PAYLOAD_KEEP_COUNT) -> None:
    payload_root = root / "payload"
    if not payload_root.is_dir():
        return

    versions = [
        path
        for path in payload_root.iterdir()
        if path.is_dir()
        and len(path.name) == 40
        and all(character in "0123456789abcdef" for character in path.name)
    ]
    def version_timestamp(path: Path) -> int:
        marker = path / ".ready"
        try:
            return marker.stat().st_mtime_ns
        except OSError:
            return path.stat().st_mtime_ns

    try:
        versions.sort(key=version_timestamp, reverse=True)
    except OSError:
        return
    keep = {path.name for path in versions[:max(keep_count, 0)]}
    keep.add(current_version)
    keep.update(_running_payload_versions(root))
    for path in versions:
        if path.name not in keep:
            try:
                shutil.rmtree(path)
            except OSError:
                # The next launch can retry cleanup after the files are no longer in use.
                continue


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
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"PotteryVolume-Bootstrap/{payload_version()}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        with destination.open("wb") as output:
            shutil.copyfileobj(response, output, length=1024 * 1024)


def show_error(message: str) -> None:
    if sys.platform == "win32":
        ctypes.windll.user32.MessageBoxW(0, message, "PotteryVolume", 0x10)
    else:
        print(message, file=sys.stderr)


def _resolve_payload_target(root: Path) -> tuple[str, Path | None]:
    try:
        selected_version = resolve_payload_version("latest")
    except (OSError, TimeoutError, urllib.error.URLError, UnicodeDecodeError, RuntimeError):
        fallback = recorded_release(root)
        if fallback is None:
            raise
        return fallback.parent.parent.name, fallback
    return selected_version, valid_payload_directory(root, selected_version)


def _record_and_cleanup(root: Path, version: str) -> Path:
    executable = valid_payload_directory(root, version)
    if executable is None:
        raise RuntimeError("ダウンロードされたペイロードの検証に失敗しました。")
    write_release_record(root, version)
    try:
        cleanup_old_payloads(root, version)
    except OSError:
        pass
    return executable


def prepare_payload(selected_version: str | None = None) -> Path:
    root = cache_root()
    with preparation_lock(root):
        if selected_version is None:
            selected_version, cached_executable = _resolve_payload_target(root)
        else:
            selected_version = resolve_payload_version(selected_version)
            cached_executable = valid_payload_directory(root, selected_version)

        if cached_executable is not None:
            return _record_and_cleanup(root, selected_version)

        payload_dir = root / "payload" / selected_version
        archive = root / f"{PAYLOAD_ZIP_NAME}.{selected_version}.part"
        checksum = root / f"{PAYLOAD_ZIP_NAME}.{selected_version}.sha256.part"
        staging = root / "payload" / f".{selected_version}.part"
        release_base = PAYLOAD_BASE_URL + "/releases/" + selected_version

        try:
            download(release_base + "/" + PAYLOAD_ZIP_NAME, archive)
            download(release_base + "/" + PAYLOAD_ZIP_NAME + ".sha256", checksum)
            try:
                checksum_metadata = checksum.read_text(encoding="ascii")
            except UnicodeDecodeError as error:
                raise RuntimeError("ダウンロードファイルのSHA-256メタデータが不正です。") from error
            expected = parse_sha256_metadata(checksum_metadata)
            if sha256(archive) != expected:
                raise RuntimeError("ダウンロードファイルのSHA-256検証に失敗しました。")

            if staging.exists():
                shutil.rmtree(staging)
            staging.mkdir(parents=True)
            safe_extract(archive, staging)
            staged_executable = staging / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
            if not staged_executable.is_file():
                raise RuntimeError("ダウンロードされたアプリにEXEが見つかりませんでした。")

            if payload_dir.exists():
                if selected_version in _running_payload_versions(root):
                    raise RuntimeError("同じ版のPotteryVolumeが起動中のため、更新ファイルを入れ替えられません。")
                shutil.rmtree(payload_dir)
            staging.rename(payload_dir)
            (payload_dir / ".ready").write_text(selected_version, encoding="ascii")
            return _record_and_cleanup(root, selected_version)
        finally:
            archive.unlink(missing_ok=True)
            checksum.unlink(missing_ok=True)
            if staging.exists():
                shutil.rmtree(staging, ignore_errors=True)


def prepare_payload_with_loading_window() -> Path:
    if sys.platform != "win32":
        return prepare_payload()

    root = cache_root()
    with preparation_lock(root):
        selected_version, cached_executable = _resolve_payload_target(root)
        if cached_executable is not None:
            return _record_and_cleanup(root, selected_version)

    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError:
        return prepare_payload(selected_version)

    try:
        root_window = tk.Tk()
        root_window.title("PotteryVolume")
        root_window.resizable(False, False)
        root_window.geometry("360x110")
        root_window.attributes("-topmost", True)

        frame = ttk.Frame(root_window, padding=20)
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
        return prepare_payload(selected_version)

    outcome: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def prepare() -> None:
        try:
            outcome.put((True, prepare_payload(selected_version)))
        except (OSError, RuntimeError, urllib.error.URLError, UnicodeDecodeError, zipfile.BadZipFile) as error:
            outcome.put((False, error))

    worker = threading.Thread(target=prepare, daemon=True)
    worker.start()
    result: object = None
    try:
        while worker.is_alive():
            root_window.update()
            worker.join(timeout=0.05)
        if not outcome.empty():
            succeeded, result = outcome.get()
            if not succeeded:
                if isinstance(result, Exception):
                    raise result
                raise RuntimeError("アプリケーションの準備中にエラーが発生しました。")
    finally:
        root_window.destroy()

    if not isinstance(result, Path):
        raise RuntimeError("ダウンロードされたアプリの準備に失敗しました。")
    return result


def parse_launcher_arguments(arguments: list[str]) -> tuple[bool, list[str]]:
    if arguments == ["--prepare-only"]:
        return True, []
    if arguments and arguments[0] == "--":
        return False, arguments[1:]
    return False, arguments


def main() -> int:
    try:
        prepare_only, forwarded_arguments = parse_launcher_arguments(sys.argv[1:])
        if prepare_only:
            prepare_payload_with_loading_window()
            return 0

        caller_cwd = Path.cwd()
        executable = prepare_payload_with_loading_window()
        normalized = normalize_forwarded_arguments(forwarded_arguments, caller_cwd)
        subprocess.Popen([str(executable), *normalized], cwd=str(executable.parent))
        return 0
    except (
        OSError,
        RuntimeError,
        TimeoutError,
        UnicodeDecodeError,
        urllib.error.URLError,
        zipfile.BadZipFile,
    ) as error:
        show_error(
            "PotteryVolumeの実行に必要なファイルを準備できませんでした。\n\n"
            f"{error}\n\nネットワーク接続を確認して、もう一度お試しください。"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
