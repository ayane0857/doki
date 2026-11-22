"""Generate the version and commit metadata embedded in the GUI executable."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def resolve_commit() -> str:
    commit = os.environ.get("GITHUB_SHA", "")
    if not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        try:
            commit = subprocess.check_output(
                ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        except (OSError, subprocess.CalledProcessError):
            commit = ""
    return commit.lower() if re.fullmatch(r"[0-9a-fA-F]{40}", commit) else "dev"


def main() -> None:
    with (ROOT / "pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    tag = os.environ.get("GITHUB_REF_NAME", "")
    if os.environ.get("GITHUB_REF_TYPE") == "tag" and tag != f"v{version}":
        raise SystemExit(f"Release tag {tag!r} does not match pyproject.toml version {version!r}.")

    info = {"version": version, "commit": resolve_commit()}
    (ROOT / "build" / "BUILD_INFO.json").write_text(
        json.dumps(info, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"BUILD_INFO.json: version={version}, commit={info['commit']}")


if __name__ == "__main__":
    main()
