import json
import runpy
import shutil
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    ("ref_type", "ref_name"),
    [("branch", "master"), ("tag", "v1.2.3"), ("tag", "v1.2.4")],
)
def test_build_info_release_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ref_type: str, ref_name: str
) -> None:
    source = Path(__file__).resolve().parents[1] / "build" / "scripts" / "write_build_info.py"
    script = tmp_path / "build" / "scripts" / source.name
    script.parent.mkdir(parents=True)
    shutil.copyfile(source, script)
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    monkeypatch.setenv("GITHUB_REF_TYPE", ref_type)
    monkeypatch.setenv("GITHUB_REF_NAME", ref_name)
    monkeypatch.setenv("GITHUB_SHA", "a" * 40)
    build_info = tmp_path / "build" / "BUILD_INFO.json"

    if ref_name == "v1.2.4":
        with pytest.raises(SystemExit, match=r"Release tag 'v1\.2\.4' does not match"):
            runpy.run_path(str(script), run_name="__main__")
        assert not build_info.exists()
    else:
        runpy.run_path(str(script), run_name="__main__")
        assert json.loads(build_info.read_text(encoding="utf-8"))["version"] == "1.2.3"
