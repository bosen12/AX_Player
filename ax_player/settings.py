"""Persisted UI state: what the app should look like when you reopen it.

Deliberately separate from resume.py, which stores per-video playback
progress. This is window-and-sidebar state -- the folder you had open, the
size you left the window, how you had the list sorted.

Backed by QSettings in INI format rather than the registry so everything
this app writes stays under app_data_dir() with the thumbnail cache and
resume database, and so QByteArray geometry blobs work without hand-rolling
an encoding for them.
"""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QSettings

from ax_player.paths import app_data_dir

SORT_NAME = "name"
SORT_DATE = "date"
SORT_SIZE = "size"
SORT_MODES = (SORT_NAME, SORT_DATE, SORT_SIZE)

_store: QSettings | None = None


def _s() -> QSettings:
    global _store
    if _store is None:
        _store = QSettings(str(app_data_dir() / "settings.ini"), QSettings.Format.IniFormat)
    return _store


def geometry() -> QByteArray:
    value = _s().value("window/geometry")
    return value if isinstance(value, QByteArray) else QByteArray()


def set_geometry(value: QByteArray) -> None:
    _s().setValue("window/geometry", value)


def last_folder() -> str:
    return str(_s().value("library/last_folder", "") or "")


def set_last_folder(path: str) -> None:
    _s().setValue("library/last_folder", path)


def recursive() -> bool:
    return _s().value("library/recursive", False, type=bool)


def set_recursive(on: bool) -> None:
    _s().setValue("library/recursive", bool(on))


def sort_mode() -> str:
    mode = str(_s().value("library/sort", SORT_NAME) or SORT_NAME)
    return mode if mode in SORT_MODES else SORT_NAME


def set_sort_mode(mode: str) -> None:
    _s().setValue("library/sort", mode if mode in SORT_MODES else SORT_NAME)


def unwatched_only() -> bool:
    return _s().value("library/unwatched_only", False, type=bool)


def set_unwatched_only(on: bool) -> None:
    _s().setValue("library/unwatched_only", bool(on))


def flush() -> None:
    _s().sync()
