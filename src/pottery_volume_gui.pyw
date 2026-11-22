"""Double-click launcher for the pottery volume settings window."""

import sys

if __name__ == "__main__":
    arguments = sys.argv[1:]
    if "--batch" in arguments:
        import contextlib
        import io

        from pottery_volume_cli import main

        arguments.remove("--batch")
        # The packaged app is windowed, so keep CLI text output off the absent console.
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            raise SystemExit(main(arguments))

    from pottery_volume_gui import launch_gui

    sys.exit(launch_gui(arguments[0] if arguments else None))
