"""Regression cover for the library/playlist routing fixed in v1.1.5-v1.1.7."""
import types
from pathlib import Path

from ax_player import resume, settings
from ax_player.app import (
    AXPlayerWindow,
    _emit_safely,
    _ScanJob,
    _sort_playlist,
)


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


class _OpenWindow:
    """Enough of AXPlayerWindow for open_folder()."""

    def __init__(self, recursive=False):
        self._folder = None
        self._recursive = recursive
        self._requested_thumbs = {"stale"}
        self._sort_mode = "name"
        self._scan_signals = object()
        self.jobs = []
        self._scan_pool = types.SimpleNamespace(start=self.jobs.append)


def test_open_folder_normalises_a_relative_path(tmp_path, monkeypatch):
    """mpv resolves relative playlist entries against the *playlist file's*
    directory, and load_playlist writes that file into %TEMP% -- so a relative
    folder produces a sidebar full of rows every one of which fails to open
    ("Failed to open <temp-dir>/vids/clip.mkv", measured). settings.last_folder
    keeps the relative path too, so the next launch breaks again from a
    different cwd."""
    (tmp_path / "vids").mkdir()
    monkeypatch.chdir(tmp_path)
    w = _OpenWindow()

    AXPlayerWindow.open_folder(w, Path("vids"))

    assert w._folder.is_absolute(), "a relative folder reached the scan and the player"
    assert w._folder == (tmp_path / "vids").resolve()
    assert w.jobs and w.jobs[0]._folder == w._folder, "the scan got a different path"


def test_open_folder_agrees_with_the_case_play_resolves_to(tmp_path, monkeypatch):
    """play() resolves before testing membership, and resolve() canonicalises
    case on Windows. A folder opened under different case therefore matched
    nothing in its own playlist: every click rescanned, and with 含子資料夾 on
    the library re-rooted onto the subdirectory -- the bug v1.1.6 closed,
    reached through a third door."""
    (tmp_path / "RealCase").mkdir()
    monkeypatch.chdir(tmp_path)
    w = _OpenWindow()

    AXPlayerWindow.open_folder(w, Path("realcase"))

    assert w._folder == (tmp_path / "realcase").resolve()


# -- ordering ---------------------------------------------------------------
def test_episode_10_sorts_after_episode_2():
    """Lexicographic order is wrong for every folder this app is pointed at:
    'ep10' < 'ep2' as text, so the second episode of a series listed tenth."""
    names = ["ep10.mkv", "ep2.mkv", "ep1.mkv", "ep20.mkv", "ep3.mkv"]
    ordered = _sort_playlist([Path(n) for n in names], settings.SORT_NAME)

    assert [p.name for p in ordered] == ["ep1.mkv", "ep2.mkv", "ep3.mkv", "ep10.mkv", "ep20.mkv"]


def test_numbering_inside_a_chinese_title_sorts_numerically_too():
    names = ["第10話.mkv", "第2話.mkv", "第1話.mkv"]
    ordered = _sort_playlist([Path(n) for n in names], settings.SORT_NAME)

    assert [p.name for p in ordered] == ["第1話.mkv", "第2話.mkv", "第10話.mkv"]


def test_leading_zeros_do_not_split_a_run_of_episodes():
    """'ep02' and 'ep2' are the same number; what must not happen is the
    zero-padded ones sorting as a separate block."""
    names = ["ep03.mkv", "ep1.mkv", "ep2.mkv", "ep10.mkv"]
    ordered = _sort_playlist([Path(n) for n in names], settings.SORT_NAME)

    assert [p.name for p in ordered] == ["ep1.mkv", "ep2.mkv", "ep03.mkv", "ep10.mkv"]


def test_size_sorting_still_reads_largest_first(tmp_path):
    for name, size in (("small.mkv", 10), ("big.mkv", 3000), ("mid.mkv", 500)):
        (tmp_path / name).write_bytes(b"x" * size)
    files = [tmp_path / n for n in ("small.mkv", "big.mkv", "mid.mkv")]

    ordered = _sort_playlist(files, settings.SORT_SIZE)

    assert [p.name for p in ordered] == ["big.mkv", "mid.mkv", "small.mkv"]


# -- scanning ---------------------------------------------------------------
def _scan(folder, recursive=False):
    job = _ScanJob(folder, recursive, None, object(), settings.SORT_NAME, True)
    return sorted(p.name for p in job._scan())


def test_the_scan_finds_videos_and_ignores_everything_else(tmp_path):
    for name in ("a.mkv", "b.MP4", "c.m2ts", "notes.txt", "cover.jpg"):
        (tmp_path / name).write_bytes(b"")
    (tmp_path / "subdir.mkv").mkdir()  # a directory that looks like a video

    assert _scan(tmp_path) == ["a.mkv", "b.MP4", "c.m2ts"]


def test_a_recursive_scan_reaches_subfolders(tmp_path):
    (tmp_path / "S1").mkdir()
    (tmp_path / "top.mkv").write_bytes(b"")
    (tmp_path / "S1" / "deep.mkv").write_bytes(b"")

    assert _scan(tmp_path) == ["top.mkv"]
    assert _scan(tmp_path, recursive=True) == ["deep.mkv", "top.mkv"]


def test_a_missing_folder_does_not_take_the_scan_thread_down(tmp_path):
    job = _ScanJob(tmp_path / "gone", False, None, _Signals(), settings.SORT_NAME, True)
    job.run()

    assert job._signals.emitted == [(str(tmp_path / "gone"), [], "", True)]


class _Signals:
    def __init__(self):
        self.emitted = []
        self.done = self

    def emit(self, *args):
        self.emitted.append(args)


# -- where a folder starts playing -----------------------------------------
def test_a_folder_starts_at_the_first_episode_not_yet_watched(tmp_path):
    """Index 0 meant reopening a series always restarted episode 1, however
    far in the user actually was."""
    playlist = [tmp_path / f"ep{i}.mkv" for i in range(4)]
    for video in playlist[:2]:
        resume.set_watched(str(video), True)
    w = types.SimpleNamespace(_playlist=playlist)

    assert AXPlayerWindow._first_unwatched_index(w) == 2


def test_a_part_watched_episode_is_where_it_resumes(tmp_path):
    playlist = [tmp_path / f"ep{i}.mkv" for i in range(3)]
    resume.set_watched(str(playlist[0]), True)
    resume.save_progress(str(playlist[1]), 300.0, 1400.0)  # half way in
    w = types.SimpleNamespace(_playlist=playlist)

    assert AXPlayerWindow._first_unwatched_index(w) == 1


def test_a_fully_watched_folder_goes_back_to_the_top(tmp_path):
    playlist = [tmp_path / f"ep{i}.mkv" for i in range(3)]
    for video in playlist:
        resume.set_watched(str(video), True)
    w = types.SimpleNamespace(_playlist=playlist)

    assert AXPlayerWindow._first_unwatched_index(w) == 0
