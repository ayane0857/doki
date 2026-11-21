from __future__ import annotations

import hashlib
import os
import urllib.error
import zipfile
from contextlib import nullcontext
from io import BytesIO

import pytest

import pottery_volume_bootstrap
from pottery_volume_cli import build_parser


def test_resolve_payload_version_reads_latest_pointer(monkeypatch):
    version = "e" * 40
    requested = {}

    def fake_urlopen(url, timeout):
        requested.update(url=url, timeout=timeout)
        return BytesIO(f"{version}\n".encode("ascii"))

    monkeypatch.setattr(pottery_volume_bootstrap.urllib.request, "urlopen", fake_urlopen)

    assert pottery_volume_bootstrap.resolve_payload_version("latest") == version
    assert requested == {
        "url": pottery_volume_bootstrap.PAYLOAD_BASE_URL + "/latest/release.txt",
        "timeout": 60,
    }


def test_resolve_payload_version_rejects_invalid_latest_pointer(monkeypatch):
    monkeypatch.setattr(
        pottery_volume_bootstrap.urllib.request,
        "urlopen",
        lambda url, timeout: BytesIO(b"not-a-commit"),
    )

    with pytest.raises(RuntimeError, match="バージョンが不正"):
        pottery_volume_bootstrap.resolve_payload_version("latest")


def test_sha256(tmp_path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"pottery")

    assert pottery_volume_bootstrap.sha256(payload) == hashlib.sha256(b"pottery").hexdigest()


@pytest.mark.parametrize(
    "metadata",
    [
        "",
        "   ",
        "not-a-checksum",
        "g" * 64,
        "0" * 63,
    ],
)
def test_parse_sha256_metadata_rejects_invalid_metadata(metadata):
    with pytest.raises(RuntimeError, match="SHA-256"):
        pottery_volume_bootstrap.parse_sha256_metadata(metadata)


def test_parse_sha256_metadata_accepts_valid_metadata():
    checksum = "A" * 64

    assert pottery_volume_bootstrap.parse_sha256_metadata(f"{checksum}  archive.zip\n") == "a" * 64


def test_safe_extract_rejects_parent_traversal(tmp_path):
    archive_path = tmp_path / "invalid.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("../outside.txt", "invalid")

    with pytest.raises(RuntimeError, match="不正なパス"):
        pottery_volume_bootstrap.safe_extract(archive_path, tmp_path / "output")


def test_prepare_payload_uses_latest_cached_release(monkeypatch, tmp_path):
    version = "0123456789abcdef0123456789abcdef01234567"
    monkeypatch.setattr(pottery_volume_bootstrap, "resolve_payload_version", lambda value: version)
    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path)

    payload_dir = tmp_path / "payload" / version
    executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("ready", encoding="utf-8")
    (payload_dir / ".ready").write_text(version, encoding="ascii")

    assert pottery_volume_bootstrap.prepare_payload() == executable


def test_recorded_release_requires_ready_marker_and_executable(tmp_path):
    version = "0123456789abcdef0123456789abcdef01234567"
    root = tmp_path
    payload_dir = root / "payload" / version
    executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("ready", encoding="utf-8")
    (root / pottery_volume_bootstrap.LAST_RELEASE_NAME).write_text(version, encoding="ascii")

    assert pottery_volume_bootstrap.recorded_release(root) is None

    (payload_dir / ".ready").write_text(version, encoding="ascii")
    assert pottery_volume_bootstrap.recorded_release(root) == executable


def test_normalize_forwarded_arguments_preserves_caller_paths(tmp_path):
    arguments = [
        "input.png",
        "--debug-dir",
        "debug",
        "--json-out=results/result.json",
    ]

    normalized = pottery_volume_bootstrap.normalize_forwarded_arguments(arguments, tmp_path)

    assert normalized == [
        str(tmp_path / "input.png"),
        "--debug-dir",
        str(tmp_path / "debug"),
        "--json-out=" + str(tmp_path / "results" / "result.json"),
    ]


def test_normalize_forwarded_crop_and_parser_contract(tmp_path):
    arguments = ["--crop", "10,20,100,200", "input.png"]
    normalized = pottery_volume_bootstrap.normalize_forwarded_arguments(arguments, tmp_path)

    args = build_parser().parse_args(normalized)
    assert args.crop == (10, 20, 100, 200)
    assert args.input == tmp_path / "input.png"


def test_main_launches_child_with_forwarded_arguments(monkeypatch, tmp_path):
    executable = tmp_path / "payload" / ("0" * 40) / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("ready", encoding="utf-8")

    monkeypatch.setattr(pottery_volume_bootstrap, "prepare_payload_with_loading_window", lambda: executable)
    monkeypatch.setattr(pottery_volume_bootstrap, "normalize_forwarded_arguments", lambda arguments, cwd: arguments)

    launched = {}

    def fake_popen(command, cwd):
        launched["command"] = command
        launched["cwd"] = cwd

    monkeypatch.setattr(pottery_volume_bootstrap.subprocess, "Popen", fake_popen)

    assert pottery_volume_bootstrap.main() == 0
    assert launched["command"][0] == str(executable)


def test_write_release_record_is_atomic(tmp_path):
    root = tmp_path
    record = root / pottery_volume_bootstrap.LAST_RELEASE_NAME
    record.write_text("old", encoding="ascii")

    pottery_volume_bootstrap.write_release_record(
        root,
        "0123456789abcdef0123456789abcdef01234567",
    )

    assert record.read_text(encoding="ascii") == "0123456789abcdef0123456789abcdef01234567"
    assert not (root / (pottery_volume_bootstrap.LAST_RELEASE_NAME + ".tmp")).exists()


def test_cache_root_uses_launcher_directory_when_frozen(monkeypatch, tmp_path):
    executable = tmp_path / "chosen" / "PotteryVolume.exe"
    executable.parent.mkdir()
    monkeypatch.setattr(pottery_volume_bootstrap.sys, "frozen", True, raising=False)
    monkeypatch.setattr(pottery_volume_bootstrap.sys, "executable", str(executable))

    assert pottery_volume_bootstrap.cache_root() == executable.parent


def test_invalid_cached_payload_is_not_recorded(monkeypatch, tmp_path):
    version = "0123456789abcdef0123456789abcdef01234567"
    record = tmp_path / pottery_volume_bootstrap.LAST_RELEASE_NAME
    record.write_text("previous", encoding="ascii")

    payload_dir = tmp_path / "payload" / version
    payload_dir.mkdir(parents=True)
    (payload_dir / ".ready").write_text("wrong-version", encoding="ascii")
    executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("ready", encoding="utf-8")

    monkeypatch.setattr(pottery_volume_bootstrap, "resolve_payload_version", lambda value: version)
    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        pottery_volume_bootstrap,
        "download",
        lambda url, destination: (_ for _ in ()).throw(RuntimeError("download failed")),
    )

    with pytest.raises(RuntimeError, match="download failed"):
        pottery_volume_bootstrap.prepare_payload()

    assert record.read_text(encoding="ascii") == "previous"


def test_prepare_payload_downloads_verifies_extracts_and_records(monkeypatch, tmp_path):
    version = "a" * 40
    archive_bytes = BytesIO()
    with zipfile.ZipFile(archive_bytes, "w") as archive:
        archive.writestr("PotteryVolume_gui/PotteryVolume_gui.exe", "application")
    payload_zip = archive_bytes.getvalue()
    expected_hash = hashlib.sha256(payload_zip).hexdigest()

    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(pottery_volume_bootstrap, "resolve_payload_version", lambda value: version)

    def fake_download(url, destination):
        if url.endswith(".sha256"):
            destination.write_text(f"{expected_hash}  archive.zip\n", encoding="ascii")
        else:
            destination.write_bytes(payload_zip)

    monkeypatch.setattr(pottery_volume_bootstrap, "download", fake_download)

    executable = pottery_volume_bootstrap.prepare_payload()

    assert executable == tmp_path / "payload" / version / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    assert executable.read_text(encoding="utf-8") == "application"
    assert (executable.parents[1] / ".ready").read_text(encoding="ascii") == version
    assert (tmp_path / pottery_volume_bootstrap.LAST_RELEASE_NAME).read_text(encoding="ascii") == version
    assert not list(tmp_path.glob("*.part"))


def test_prepare_payload_falls_back_to_recorded_release_offline(monkeypatch, tmp_path):
    version = "b" * 40
    payload_dir = tmp_path / "payload" / version
    executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("ready", encoding="utf-8")
    (payload_dir / ".ready").write_text(version, encoding="ascii")
    (tmp_path / pottery_volume_bootstrap.LAST_RELEASE_NAME).write_text(version, encoding="ascii")

    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        pottery_volume_bootstrap,
        "resolve_payload_version",
        lambda value: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )

    assert pottery_volume_bootstrap.prepare_payload() == executable


def test_prepare_payload_reports_offline_without_valid_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        pottery_volume_bootstrap,
        "resolve_payload_version",
        lambda value: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )

    with pytest.raises(urllib.error.URLError):
        pottery_volume_bootstrap.prepare_payload()


def test_cleanup_keeps_two_recent_current_and_running_payloads(monkeypatch, tmp_path):
    versions = [str(value) * 40 for value in range(5)]
    for index, version in enumerate(versions):
        payload_dir = tmp_path / "payload" / version
        executable = payload_dir / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
        executable.parent.mkdir(parents=True)
        executable.write_text("ready", encoding="utf-8")
        marker = payload_dir / ".ready"
        marker.write_text(version, encoding="ascii")
        os.utime(marker, (index + 1, index + 1))

    monkeypatch.setattr(
        pottery_volume_bootstrap,
        "_running_payload_versions",
        lambda root: {versions[1]},
    )

    pottery_volume_bootstrap.cleanup_old_payloads(tmp_path, versions[0], keep_count=2)

    assert {path.name for path in (tmp_path / "payload").iterdir()} == {
        versions[0],
        versions[1],
        versions[3],
        versions[4],
    }


def test_parse_launcher_arguments_reserves_prepare_only_without_colliding(monkeypatch, tmp_path):
    parse = pottery_volume_bootstrap.parse_launcher_arguments
    assert parse(["--prepare-only"]) == (True, [])
    assert parse(["--prepare-only", "input.png"]) == (False, ["--prepare-only", "input.png"])
    assert parse(["--", "--prepare-only"]) == (False, ["--prepare-only"])


def test_prepare_only_does_not_launch_application(monkeypatch):
    monkeypatch.setattr(pottery_volume_bootstrap.sys, "argv", ["PotteryVolume.exe", "--prepare-only"])
    monkeypatch.setattr(pottery_volume_bootstrap, "prepare_payload_with_loading_window", lambda: None)
    monkeypatch.setattr(
        pottery_volume_bootstrap.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("prepare-only must not launch the GUI"),
    )

    assert pottery_volume_bootstrap.main() == 0


def test_cached_latest_skips_loading_window_on_windows(monkeypatch, tmp_path):
    version = "c" * 40
    executable = tmp_path / "payload" / version / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("ready", encoding="utf-8")
    (executable.parents[1] / ".ready").write_text(version, encoding="ascii")
    monkeypatch.setattr(pottery_volume_bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(pottery_volume_bootstrap, "resolve_payload_version", lambda value: version)
    monkeypatch.setattr(pottery_volume_bootstrap, "preparation_lock", lambda root: nullcontext())

    assert pottery_volume_bootstrap.prepare_payload_with_loading_window() == executable


def test_main_normalizes_relative_arguments_on_windows(monkeypatch, tmp_path):
    executable = tmp_path / "payload" / ("d" * 40) / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(pottery_volume_bootstrap.sys, "platform", "win32")
    monkeypatch.setattr(pottery_volume_bootstrap.sys, "argv", ["PotteryVolume.exe", "input.png", "--debug-dir", "out"])
    monkeypatch.setattr(pottery_volume_bootstrap, "prepare_payload_with_loading_window", lambda: executable)
    launched = {}
    monkeypatch.setattr(
        pottery_volume_bootstrap.subprocess,
        "Popen",
        lambda command, cwd: launched.update(command=command, cwd=cwd),
    )

    assert pottery_volume_bootstrap.main() == 0
    assert launched["command"][1:] == [str(tmp_path / "input.png"), "--debug-dir", str(tmp_path / "out")]
    assert launched["cwd"] == str(executable.parent)
