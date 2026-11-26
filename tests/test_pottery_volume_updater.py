"""Network metadata and installer download tests for the GUI updater."""

from __future__ import annotations

import hashlib
import io
import urllib.error
from pathlib import Path

import pytest

import pottery_volume_updater as updater


class FakeResponse(io.BytesIO):
    def __init__(self, body: bytes) -> None:
        super().__init__(body)
        self.headers = {"Content-Length": str(len(body))}


@pytest.mark.parametrize("value", ["", " " * 2, "x" * 40, "0" * 39, "0" * 41])
def test_release_version_rejects_empty_and_invalid_values(value: str) -> None:
    with pytest.raises(updater.UpdateError, match="最新版情報"):
        updater.parse_release_version(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("A" * 40, "a" * 40), ("b" * 40, "b" * 40), (b"C" * 40 + b"\r\n", "c" * 40)],
)
def test_release_version_normalizes_hex_case(value, expected: str) -> None:
    assert updater.parse_release_version(value) == expected


def test_latest_release_uses_short_network_timeout(monkeypatch) -> None:
    requested: dict[str, object] = {}

    def fake_urlopen(request, timeout: float):
        requested.update(
            url=request.full_url,
            accept=request.get_header("Accept"),
            timeout=timeout,
        )
        return FakeResponse(b"A" * 40)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    assert updater.resolve_latest_release() == "a" * 40
    assert requested == {
        "url": updater.GITHUB_LATEST_COMMIT_API_URL,
        "accept": "application/vnd.github.sha",
        "timeout": updater.REQUEST_TIMEOUT_SECONDS,
    }
    assert updater.REQUEST_TIMEOUT_SECONDS <= 10


@pytest.mark.parametrize(
    "metadata", [b"not-a-sha", b"a" * 39, b"a" * 41, b"\xff"]
)
def test_latest_release_rejects_invalid_sha(monkeypatch, metadata: bytes) -> None:
    monkeypatch.setattr(
        updater.urllib.request, "urlopen", lambda *_args, **_kwargs: FakeResponse(metadata)
    )

    with pytest.raises(updater.UpdateError, match="最新版情報"):
        updater.resolve_latest_release()


def test_update_comparison_skips_current_and_dev_builds() -> None:
    commit = "a" * 40

    assert not updater.update_available(commit, commit.upper())
    assert not updater.update_available("dev", "b" * 40)
    assert not updater.update_available("invalid", "b" * 40)
    assert updater.update_available(commit, "b" * 40)


@pytest.mark.parametrize(
    "metadata",
    ["", "  ", "not-a-hash", "g" * 64, "a" * 63, "a" * 65],
)
def test_checksum_metadata_rejects_invalid_first_field(metadata: str) -> None:
    with pytest.raises(updater.UpdateError, match="SHA-256"):
        updater.parse_sha256_metadata(metadata)


def test_checksum_metadata_uses_first_field_and_normalizes_case() -> None:
    assert updater.parse_sha256_metadata("A" * 64 + "  PotteryVolume-Setup.exe\n") == "a" * 64


def test_non_https_urls_are_rejected() -> None:
    for url in ("http://example.com/update", "file:///tmp/setup.exe", "https:///missing-host"):
        with pytest.raises(updater.UpdateError, match="HTTPS"):
            updater.validate_https_url(url)


def test_http_latest_commit_url_is_rejected_before_network_access(monkeypatch) -> None:
    monkeypatch.setattr(
        updater, "GITHUB_LATEST_COMMIT_API_URL", "http://example.com/latest"
    )
    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: pytest.fail("HTTP URLs must be rejected before access"),
    )

    with pytest.raises(updater.UpdateError, match="HTTPS"):
        updater.resolve_latest_release()


def test_redirect_to_http_is_rejected(monkeypatch) -> None:
    class RedirectedResponse(FakeResponse):
        def geturl(self) -> str:
            return "http://example.com/latest"

    monkeypatch.setattr(
        updater.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: RedirectedResponse(b"a" * 40),
    )

    with pytest.raises(updater.UpdateError, match="HTTPS"):
        updater.resolve_latest_release()


def test_setup_download_streams_verifies_and_replaces_destination(
    monkeypatch, tmp_path: Path
) -> None:
    version = "d" * 40
    payload = b"verified setup"
    expected = hashlib.sha256(payload).hexdigest()
    destination = tmp_path / "download" / "PotteryVolume-Setup.exe"
    destination.parent.mkdir()
    destination.write_bytes(b"old setup")
    requested: list[str] = []

    def fake_urlopen(url: str, timeout: float):
        requested.append(url)
        if url.endswith(".sha256"):
            return FakeResponse(f"{expected}  PotteryVolume-Setup.exe\n".encode("ascii"))
        return FakeResponse(payload)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    progress: list[tuple[int, int | None]] = []

    result = updater.download_setup(
        version, destination, progress=lambda received, total: progress.append((received, total)) or True
    )

    assert result == destination
    assert destination.read_bytes() == payload
    assert requested == [
        f"{updater.PAYLOAD_BASE_URL}/PotteryVolume-Setup.exe.sha256",
        f"{updater.PAYLOAD_BASE_URL}/PotteryVolume-Setup.exe",
    ]
    assert progress[-1] == (len(payload), len(payload))
    assert not destination.with_name(destination.name + ".part").exists()


def test_hash_mismatch_does_not_publish_setup_or_leave_partial_file(
    monkeypatch, tmp_path: Path
) -> None:
    version = "e" * 40
    payload = b"tampered setup"
    destination = tmp_path / "PotteryVolume-Setup.exe"
    destination.write_bytes(b"existing verified setup")

    def fake_urlopen(url: str, timeout: float):
        if url.endswith(".sha256"):
            return FakeResponse(("0" * 64 + "  file\n").encode("ascii"))
        return FakeResponse(payload)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(updater.UpdateError, match="一致しません"):
        updater.download_setup(version, destination)

    assert destination.read_bytes() == b"existing verified setup"
    assert not destination.with_name(destination.name + ".part").exists()


def test_cancelled_setup_download_removes_partial_file(monkeypatch, tmp_path: Path) -> None:
    version = "f" * 40
    payload = b"setup bytes"
    expected = hashlib.sha256(payload).hexdigest()

    def fake_urlopen(url: str, timeout: float):
        if url.endswith(".sha256"):
            return FakeResponse((expected + "  setup.exe\n").encode("ascii"))
        return FakeResponse(payload)

    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    destination = tmp_path / "setup.exe"

    with pytest.raises(updater.DownloadCancelled):
        updater.download_setup(version, destination, progress=lambda _received, _total: False)

    assert not destination.exists()
    assert not destination.with_name(destination.name + ".part").exists()


def test_network_failure_is_propagated_for_worker_to_log(monkeypatch) -> None:
    def offline(*_args, **_kwargs):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(updater.urllib.request, "urlopen", offline)

    with pytest.raises(urllib.error.URLError):
        updater.resolve_latest_release()
