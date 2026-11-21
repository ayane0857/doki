from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "build" / "dist" / "PotteryVolume_gui"
ARCHIVE = ROOT / "build" / "PotteryVolume-GUI-Windows.zip"
CHECKSUM = ROOT / "build" / "PotteryVolume-GUI-Windows.zip.sha256"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not SOURCE.is_dir():
        raise SystemExit(f"Missing payload directory: {SOURCE}")

    temporary_archive = ARCHIVE.with_suffix(ARCHIVE.suffix + ".tmp")
    temporary_checksum = CHECKSUM.with_suffix(CHECKSUM.suffix + ".tmp")
    temporary_archive.unlink(missing_ok=True)
    temporary_checksum.unlink(missing_ok=True)

    with zipfile.ZipFile(temporary_archive, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in SOURCE.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(SOURCE.parent).as_posix())

    checksum = sha256(temporary_archive)
    temporary_checksum.write_text(
        f"{checksum}  {ARCHIVE.name}\n",
        encoding="ascii",
    )
    temporary_archive.replace(ARCHIVE)
    temporary_checksum.replace(CHECKSUM)
    print(f"Created {ARCHIVE}")
    print(f"Created {CHECKSUM}")


if __name__ == "__main__":
    main()
