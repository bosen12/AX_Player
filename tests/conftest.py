import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the session.

    QImage and QPixmap both need it, and Qt allows exactly one per process.
    """
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture(autouse=True)
def isolated_appdata(tmp_path, monkeypatch, qapp):
    """No test may write to the real %LOCALAPPDATA%\\AXPlayer.

    Every path this app writes -- the thumbnail and contact-sheet caches,
    resume.json, settings.ini, debug.log -- resolves through app_data_dir(),
    which reads LOCALAPPDATA on each call. Without this, running the suite
    prunes and rewrites the caches of whoever is running it: verifying today's
    cache changes by hand polluted the live cache twice, 80 dead entries that
    had to be found and deleted afterwards. Fluid Motion's conftest exists for
    the same reason, after the same thing happened there.

    The module-level caches that would otherwise outlive the monkeypatch are
    reset here too.
    """
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))

    from ax_player import debug_log, resume, settings

    monkeypatch.setattr(debug_log, "_log_path", None)
    monkeypatch.setattr(settings, "_store", None)
    monkeypatch.setattr(resume, "_cache", None)
    yield
