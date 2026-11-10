"""Double-click launcher for the pottery volume settings window."""

import contextlib
import io
import sys

from pottery_volume import launch_gui, main


if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--batch" in arguments:
        arguments.remove("--batch")
        # The packaged app is windowed, so keep CLI text output off the absent console.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            raise SystemExit(main(arguments))
    launch_gui(arguments[0] if arguments else None)
