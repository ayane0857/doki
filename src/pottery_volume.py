"""Launch the pottery volume GUI, or analyze an image when given arguments."""

import sys

if __name__ == "__main__":
    if len(sys.argv) == 1:
        from doki.gui.app import launch_gui

        raise SystemExit(launch_gui())
    from doki.cli import main

    raise SystemExit(main())
