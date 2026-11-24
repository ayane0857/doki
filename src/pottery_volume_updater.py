"""GUI updater network and file-verification logic, independent of Qt."""

from __future__ import annotations

import hashlib
import os
import re
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

GITHUB_REPOSITORY = "ayane0857/doki"
GITHUB_RELEASES_BASE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases/download"
PAYLOAD_BASE_URL = f"{GITHUB_RELEASES_BASE_URL}/latest"
REQUEST_TIMEOUT_SECONDS = 8
DOWNLOAD_CHUNK_SIZE = 1024 * 256
_RELEASE_PATTERN = re.compile(r"[0-9a-fA-F]{40}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-fA-F]{64}\Z")


class UpdateError(RuntimeError):
    """Raised when release metadata or a downloaded installer is invalid."""


class DownloadCancelled(UpdateError):
    """Raised when the user cancels an installer download."""


ProgressCallback = Callable[[int, int | None], bool]


def validate_https_url(url: str) -> str:
    """Return a URL only when it uses HTTPS and has a host name."""
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https" or not parsed.netloc:
        raise UpdateError("HTTPS 以外の更新URLは利用できません。")
    return url


def _open_https_url(url: str, timeout: float) -> Any:
    """Open a URL and reject redirects whose final URL is not HTTPS."""
    response = urllib.request.urlopen(url, timeout=timeout)
    try:
        get_url = getattr(response, "geturl", None)
        if callable(get_url):
            final_url = get_url()
            if not isinstance(final_url, str):
                raise UpdateError("更新サーバーの応答URLが不正です。")
            validate_https_url(final_url)
    except Exception:
        response.close()
        raise
    return response


def parse_release_version(content: str | bytes) -> str:
    """Parse and normalize a 40-character hexadecimal release commit."""
    try:
        value = content.decode("ascii") if isinstance(content, bytes) else content
    except UnicodeDecodeError as exc:
        raise UpdateError("最新版情報の形式が不正です。") from exc
    value = value.strip()
    if not _RELEASE_PATTERN.fullmatch(value):
        raise UpdateError("最新版情報の形式が不正です。")
    return value.lower()


def resolve_latest_release(timeout: float = REQUEST_TIMEOUT_SECONDS) -> str:
    """Fetch release.txt from the rolling GitHub latest release."""
    url = validate_https_url(f"{PAYLOAD_BASE_URL}/PotteryVolume-release.txt")
    with _open_https_url(url, timeout) as response:
        return parse_release_version(response.read(256))


def update_available(build_commit: str, latest_commit: str) -> bool:
    """Return whether a packaged build should offer the specified release."""
    if build_commit.lower() == "dev" or not _RELEASE_PATTERN.fullmatch(build_commit):
        return False
    latest = parse_release_version(latest_commit)
    return build_commit.lower() != latest


def sha256(path: Path) -> str:
    """Return the lowercase SHA-256 digest for a file."""
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(DOWNLOAD_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_sha256_metadata(metadata: str | bytes) -> str:
    """Read the first SHA-256 field from a standard .sha256 file."""
    try:
        value = metadata.decode("ascii") if isinstance(metadata, bytes) else metadata
    except UnicodeDecodeError as exc:
        raise UpdateError("Setup.exe の SHA-256 情報が不正です。") from exc
    fields = value.strip().split()
    if not fields or not _SHA256_PATTERN.fullmatch(fields[0]):
        raise UpdateError("Setup.exe の SHA-256 情報が不正です。")
    return fields[0].lower()


def fetch_setup_sha256(commit: str, timeout: float = REQUEST_TIMEOUT_SECONDS) -> str:
    """Fetch Setup.exe checksum metadata from the rolling GitHub release."""
    parse_release_version(commit)
    url = validate_https_url(
        f"{PAYLOAD_BASE_URL}/PotteryVolume-Setup.exe.sha256"
    )
    with _open_https_url(url, timeout) as response:
        metadata = response.read(4096)
    return parse_sha256_metadata(metadata)


def download_setup(
    commit: str,
    destination: Path,
    *,
    progress: ProgressCallback | None = None,
    timeout: float = REQUEST_TIMEOUT_SECONDS,
) -> Path:
    """Download a Setup.exe, verify its checksum, then atomically publish it."""
    parse_release_version(commit)
    expected_hash = fetch_setup_sha256(commit, timeout)
    url = validate_https_url(
        f"{PAYLOAD_BASE_URL}/PotteryVolume-Setup.exe"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    temporary.unlink(missing_ok=True)
    digest = hashlib.sha256()
    received = 0
    try:
        with _open_https_url(url, timeout) as response:
            raw_length = getattr(response, "headers", {}).get("Content-Length")
            total = int(raw_length) if raw_length and raw_length.isdigit() else None
            if progress is not None and not progress(0, total):
                raise DownloadCancelled("更新プログラムのダウンロードを中止しました。")
            with temporary.open("wb") as file:
                while chunk := response.read(DOWNLOAD_CHUNK_SIZE):
                    file.write(chunk)
                    digest.update(chunk)
                    received += len(chunk)
                    if progress is not None and not progress(received, total):
                        raise DownloadCancelled(
                            "更新プログラムのダウンロードを中止しました。"
                        )
        if digest.hexdigest() != expected_hash:
            raise UpdateError("Setup.exe の SHA-256 が一致しません。")
        os.replace(temporary, destination)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
