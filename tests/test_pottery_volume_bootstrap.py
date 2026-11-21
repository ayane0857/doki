from __future__ import annotations

import hashlib
import zipfile

import pytest

import pottery_volume_bootstrap
from pottery_volume_cli import build_parser


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

    with pytest.raises(RuntimeError, match="invalid path"):
        pottery_volume_bootstrap.safe_extract(archive_path, tmp_path / "output")


def test_prepare_payload_resolves_bundled_version(monkeypatch, tmp_path):
    version = "0123456789abcdef0123456789abcdef01234567"
    monkeypatch.setattr(pottery_volume_bootstrap, "payload_version", lambda: version)
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


def test_main_launches_when_release_record_write_fails(monkeypatch, tmp_path):
    executable = tmp_path / "payload" / ("0" * 40) / "PotteryVolume_gui" / "PotteryVolume_gui.exe"
    executable.parent.mkdir(parents=True)
    executable.write_text("ready", encoding="utf-8")

    monkeypatch.setattr(pottery_volume_bootstrap, "prepare_payload", lambda: executable)
    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path / "missing" / "child")
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


def test_cache_root_uses_saved_install_location(monkeypatch, tmp_path):
    base_root = tmp_path / "base"
    base_root.mkdir()
    install_root = tmp_path / "chosen"
    (base_root / pottery_volume_bootstrap.INSTALL_LOCATION_NAME).write_text(
        str(install_root),
        encoding="utf-8",
    )
    monkeypatch.setattr(pottery_volume_bootstrap, "default_cache_root", lambda: base_root)

    assert pottery_volume_bootstrap.cache_root() == install_root


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

    monkeypatch.setattr(pottery_volume_bootstrap, "payload_version", lambda: version)
    monkeypatch.setattr(pottery_volume_bootstrap, "cache_root", lambda: tmp_path)
    monkeypatch.setattr(
        pottery_volume_bootstrap,
        "download",
        lambda url, destination: (_ for _ in ()).throw(RuntimeError("download failed")),
    )

    with pytest.raises(RuntimeError, match="download failed"):
        pottery_volume_bootstrap.prepare_payload()

    assert record.read_text(encoding="ascii") == "previous"
