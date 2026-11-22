"""Measure Windows staging paths from a GUI ZIP or an onedir build."""

from __future__ import annotations

import argparse
import os
from pathlib import Path, PureWindowsPath
from zipfile import ZipFile

STAGING_DIRECTORY = ".PotteryVolume-staging"
MAX_PATH = 260  # Includes the terminating NUL.


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("payload", type=Path, help="GUI ZIP or PotteryVolume_gui directory")
    local_app_data = os.environ.get("LOCALAPPDATA", r"C:\Users\Example\AppData\Local")
    parser.add_argument(
        "--app-dir",
        type=PureWindowsPath,
        default=PureWindowsPath(local_app_data) / "Programs" / "PotteryVolume",
        help="Windows installation directory ({app}); defaults to %(default)s",
    )
    args = parser.parse_args()
    if not args.app_dir.is_absolute():
        parser.error("--app-dir must be an absolute Windows path")

    source = args.payload
    if source.is_dir():
        paths = [
            PureWindowsPath("PotteryVolume_gui", *path.relative_to(source).parts)
            for path in source.rglob("*")
        ]
    else:
        with ZipFile(source) as archive:
            paths = [PureWindowsPath(entry.filename) for entry in archive.infolist()]
    if not paths:
        parser.error("payload has no entries")

    def length(path: PureWindowsPath) -> int:
        return len(str(path).encode("utf-16-le")) // 2

    longest = max(paths, key=length)
    prefix = args.app_dir / STAGING_DIRECTORY
    staged = prefix / longest
    staged_length = length(staged)
    over_limit = sum(length(prefix / path) >= MAX_PATH for path in paths)
    print(f"Longest payload path ({length(longest)} UTF-16 units): {longest}")
    print(f"Longest staging path ({staged_length} UTF-16 units): {staged}")
    print(f"MAX_PATH: {MAX_PATH - 1} units before NUL; entries exceeding it: {over_limit}")
    return int(over_limit > 0)


if __name__ == "__main__":
    raise SystemExit(main())
