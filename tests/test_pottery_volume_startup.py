import os
import subprocess
import sys
from pathlib import Path
from textwrap import dedent

import pytest


@pytest.mark.parametrize(
    "module, forbidden",
    [
        (
            "pottery_volume_gui",
            (
                "numpy", "cv2", "scipy", "skimage", "shapely", "matplotlib",
                "pottery_volume_core", "pottery_volume_cli", "pottery_volume_gui_helpers",
            ),
        ),
        ("pottery_volume_core", ("scipy", "shapely", "skimage")),
    ],
)
def test_startup_imports(module: str, forbidden: tuple[str, ...]) -> None:
    _run_python(f"""
        import sys
        import {module}

        loaded = {{name for name in sys.modules if name.partition('.')[0] in {forbidden!r}}}
        assert not loaded, sorted(loaded)
    """)


def test_lazy_gui_reexports() -> None:
    _run_python("""
        from pottery_volume_gui import GUIArgumentParser
        import pottery_volume_gui as gui
        import pottery_volume_gui_helpers as helpers

        assert GUIArgumentParser is helpers.GUIArgumentParser
        for name in ('Info', 'Result', 'build_tsv_row', 'build_tsv_table'):
            assert getattr(gui, name) is getattr(helpers, name)
        assert not hasattr(gui, 'missing_export')
    """)


def _run_python(code: str) -> None:
    src = Path(__file__).resolve().parents[1] / "src"
    result = subprocess.run(
        [sys.executable, "-c", dedent(code)],
        env={**os.environ, "PYTHONPATH": str(src)},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
