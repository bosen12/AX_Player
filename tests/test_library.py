"""Regression cover for the library/playlist routing fixed in v1.1.5-v1.1.7."""
import types
from pathlib import Path

from ax_player.app import AXPlayerWindow, _emit_safely


class _Window:
    """Enough of AXPlayerWindow for the unbound methods under test."""

    def __init__(self, folder, playlist, recursive=False, mpv_holds=()):
        self._folder = folder
        self._playlist = playlist
        self._recursive = recursive
        self._requested_sheets = set()
        self._holds = set(mpv_holds)
        self.opened = None
        self.selected = None
        self.player = types.SimpleNamespace(
            play_path=lambda v: v in self._holds, setFocus=lambda *a: None
        )

    def open_folder(self, folder, select=None, **kw):
        self.opened = folder
        self.selected = select


ROOT = Path(r"C:\V")
SUB = ROOT / "Sub"
LISTED = [ROOT / "a.mp4", SUB / "b.mp4"]


def test_playing_a_listed_file_does_not_reopen_the_folder():
    """With 含子資料夾 on, a subfolder file is in the library but is not a
    child of it. Testing the parent instead of membership re-rooted the whole
    library onto that subdirectory for every click."""
    w = _Window(ROOT, LISTED, recursive=True, mpv_holds=LISTED)
    AXPlayerWindow.play(w, SUB / "b.mp4")
    assert w.opened is None


def test_a_stale_mpv_playlist_reloads_at_the_library_root():
    w = _Window(ROOT, LISTED, recursive=True)  # mpv holds nothing
    AXPlayerWindow.play(w, SUB / "b.mp4")
    assert w.opened == ROOT
    assert w.selected == SUB / "b.mp4"


def test_an_unscanned_file_under_a_recursive_root_keeps_the_library():
    """Dropped in or passed on the command line before a rescan. The miss
    branch used to reopen video.parent, which is the same re-rooting bug
    through a different door."""
    w = _Window(ROOT, LISTED, recursive=True)
    AXPlayerWindow.play(w, SUB / "new.mp4")
    assert w.opened == ROOT


def test_a_flat_library_still_opens_the_files_own_folder():
    """Not recursive: rescanning the root would not list a file in a
    subdirectory either, so select would miss again and land on index 0 --
    playing the wrong video."""
    w = _Window(ROOT, LISTED, recursive=False)
    AXPlayerWindow.play(w, SUB / "new.mp4")
    assert w.opened == SUB


def test_a_file_outside_the_library_opens_its_own_folder():
    w = _Window(ROOT, LISTED, recursive=True)
    AXPlayerWindow.play(w, Path(r"C:\Other\c.mp4"))
    assert w.opened == Path(r"C:\Other")


def test_no_library_open_yet():
    w = _Window(None, [], recursive=False)
    AXPlayerWindow.play(w, ROOT / "a.mp4")
    assert w.opened == ROOT


def test_a_finished_sheet_can_be_requested_again():
    """_requested_sheets means "a job is running", not "this was tried".
    Leaving entries in made a sheet unrecoverable once the LRU removed its
    file: the cache lookup misses and the in-flight check then returns early,
    so the popup sits on 正在產生預覽… forever."""
    w = _Window(ROOT, LISTED)
    w._requested_sheets.add("C:\\V\\a.mp4")
    AXPlayerWindow._sheet_finished(w, "C:\\V\\a.mp4")
    assert w._requested_sheets == set()


def test_emit_safely_swallows_only_a_dead_receiver():
    """A job finishing after the window closed must not raise out of run()."""
    calls = []

    class Dead:
        def emit(self, *a):
            raise RuntimeError("Signal source has been deleted")

    class Live:
        def emit(self, *a):
            calls.append(a)

    class Broken:
        def emit(self, *a):
            raise ValueError("a real bug")

    _emit_safely(Dead(), "x", "y")  # must not raise
    _emit_safely(Live(), "x", "y")
    assert calls == [("x", "y")]
    try:
        _emit_safely(Broken(), "x")
    except ValueError:
        pass
    else:
        raise AssertionError("a genuine error was swallowed")
