"""Everything the app remembers between launches.

A statement-deletion sweep could empty almost every function in settings.py
with the suite green: only set_sort_mode had cover. That is a lot of
user-visible state -- the library that reopens on launch, the window size, the
three toggles -- riding on nothing.

The round trip is asserted through a *fresh* QSettings rather than the cached
one, because the in-memory object answers correctly even when nothing reached
the file.
"""
from PySide6.QtCore import QByteArray, QSettings

from ax_player import settings
from ax_player.paths import app_data_dir


def _reread() -> QSettings:
    """What the next launch sees: a new QSettings over the same file."""
    settings.flush()
    return QSettings(str(app_data_dir() / "settings.ini"), QSettings.Format.IniFormat)


def test_the_library_folder_survives_a_restart(tmp_path):
    """main() reopens settings.last_folder() so a normal launch lands on the
    file list rather than an empty sidebar. Nothing tested that it is written
    at all."""
    settings.set_last_folder(str(tmp_path / "Anime"))

    assert settings.last_folder() == str(tmp_path / "Anime")
    assert _reread().value("library/last_folder") == str(tmp_path / "Anime")


def test_an_empty_library_reads_back_as_a_string_not_none():
    """last_folder() feeds Path(last).is_dir() straight away, so None here is a
    TypeError on the very first launch."""
    assert settings.last_folder() == ""


def test_the_three_toggles_round_trip(monkeypatch):
    """recursive / unwatched_only / always_on_top are all read back at startup
    and pushed into the sidebar by restore_state. Stored as real bools, not as
    the strings an INI file would otherwise hand back."""
    for setter, getter, key in (
        (settings.set_recursive, settings.recursive, "library/recursive"),
        (settings.set_unwatched_only, settings.unwatched_only, "library/unwatched_only"),
        (settings.set_always_on_top, settings.always_on_top, "window/always_on_top"),
    ):
        assert getter() is False, f"{key} did not default to off"
        setter(True)
        assert getter() is True, f"{key} did not come back on"
        assert _reread().value(key, False, type=bool) is True, f"{key} never reached the file"
        setter(False)
        assert getter() is False, f"{key} could not be turned off again"


def test_the_window_geometry_round_trips_as_a_blob():
    """saveGeometry() hands over a QByteArray and restoreGeometry() will only
    take one back. An INI file is text, so this is the one value whose type
    surviving the trip is not obvious."""
    blob = QByteArray(b"\x01\xd9\xd0\xcb\x00\x03\x00\x00")
    settings.set_geometry(blob)

    restored = settings.geometry()
    assert isinstance(restored, QByteArray), f"came back as {type(restored).__name__}"
    assert restored == blob

    settings._store = None  # what the next launch does
    assert settings.geometry() == blob, "the geometry never reached the file"


def test_a_missing_geometry_is_an_empty_blob_not_none():
    """First run. restoreGeometry(None) raises; restoreGeometry(empty) is the
    documented no-op the window relies on."""
    value = settings.geometry()
    assert isinstance(value, QByteArray) and value.isEmpty()
