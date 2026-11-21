from __future__ import annotations

import hashlib
import zipfile

import pytest

import pottery_volume_bootstrap


def test_sha256(tmp_path):
    payload = tmp_path / "payload.bin"
    payload.write_bytes(b"pottery")

    assert pottery_volume_bootstrap.sha256(payload) == hashlib.sha256(b"pottery").hexdigest()


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
