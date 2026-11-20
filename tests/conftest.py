import gc

import pytest


@pytest.fixture(scope="session", autouse=True)
def _qt_session_cleanup() -> object:
    yield

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        return

    app = QApplication.instance()
    if app is not None:
        app.closeAllWindows()
        app.processEvents()
        gc.collect()
        app.processEvents()
        app.quit()
