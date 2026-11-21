from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

PAYLOAD_BASE_URL = "https://file.ayane0857.net/app/doki/windows/latest"
PAYLOAD_ZIP_NAME = "PotteryVolume-GUI-Windows.zip"
PAYLOAD_VERSION_NAME = "BOOTSTRAP_VERSION"


def _resource_path(name: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / name


def payload_version() -> str:
    path = _resource_path(PAYLOAD_VERSION_NAME)
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return "dev"


def cache_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "PotteryVolume"
    return Path.home() / ".cache" / "PotteryVolume"


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


def prepare_payload() -> Path:
    version = payload_version()
    root = cache_root()
    payload_dir = root / "payload" / version
    marker = payload_dir / ".ready"

    if marker.is_file():
        executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
        if executable.is_file():
            return executable

    root.mkdir(parents=True, exist_ok=True)
    archive = root / f"{PAYLOAD_ZIP_NAME}.part"
    checksum = root / "PotteryVolume-GUI-Windows.zip.sha256.part"
    staging = root / "payload" / f".{version}.part"

    download(PAYLOAD_BASE_URL + "/" + PAYLOAD_ZIP_NAME, archive)
    download(PAYLOAD_BASE_URL + "/" + PAYLOAD_ZIP_NAME + ".sha256", checksum)

    expected = checksum.read_text(encoding="ascii").strip().split()[0].lower()
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
    (payload_dir / ".ready").write_text(version, encoding="ascii")
    archive.unlink(missing_ok=True)
    checksum.unlink(missing_ok=True)

    executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    if not executable.is_file():
        raise RuntimeError("ダウンロードされたアプリにEXEが見つかりませんでした。")
    return executable


def main() -> int:
    try:
        executable = prepare_payload()
        subprocess.Popen([str(executable), *sys.argv[1:]], cwd=str(executable.parent))
        return 0
    except (OSError, RuntimeError, urllib.error.URLError, zipfile.BadZipFile) as error:
        show_error(
            "PotteryVolumeの実行に必要なファイルをダウンロードできませんでした。\n\n"
            f"{error}\n\nインターネット接続を確認してください。"
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
