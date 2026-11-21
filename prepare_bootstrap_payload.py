from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

SOURCE = Path("dist") / "PotteryVolume_gui"
ARCHIVE = Path("PotteryVolume-GUI-Windows.zip")
CHECKSUM = Path("PotteryVolume-GUI-Windows.zip.sha256")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    if not SOURCE.is_dir():
        raise SystemExit(f"Missing payload directory: {SOURCE}")

    if ARCHIVE.exists():
        ARCHIVE.unlink()
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in SOURCE.rglob("*"):
            if path.is_file():
                archive.write(path, path.relative_to(SOURCE.parent).as_posix())

    CHECKSUM.write_text(
        f"{sha256(ARCHIVE)}  {ARCHIVE.name}\n",
        encoding="ascii",
    )
    print(f"Created {ARCHIVE}")
    print(f"Created {CHECKSUM}")


if __name__ == "__main__":
    main()
