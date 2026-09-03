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


# -- fullscreen gives back the state it took --------------------------------
def _fullscreen_stub(maximized):
    calls = []
    window = types.SimpleNamespace(
        _fullscreen=False,
        isMaximized=lambda: maximized,
        showFullScreen=lambda: calls.append("full"),
        showMaximized=lambda: calls.append("max"),
        showNormal=lambda: calls.append("normal"),
        titlebar=types.SimpleNamespace(setVisible=lambda _v: None),
        sidebar=types.SimpleNamespace(setVisible=lambda _v: None),
    )
    window.isFullScreen = lambda: window._fullscreen
    return window, calls


def test_leaving_fullscreen_gives_a_maximized_window_back_maximized():
    """showNormal() clears WindowMaximized as well as WindowFullScreen, so
    maximize -> uosc fullscreen -> fullscreen again handed back the restored
    1320x780 window instead of the maximized one."""
    window, calls = _fullscreen_stub(maximized=True)

    AXPlayerWindow._on_mpv_fullscreen(window, True)
    window._fullscreen = True
    AXPlayerWindow._on_mpv_fullscreen(window, False)

    assert calls == ["full", "max"]


def test_a_windowed_player_still_comes_back_windowed():
    window, calls = _fullscreen_stub(maximized=False)

    AXPlayerWindow._on_mpv_fullscreen(window, True)
    window._fullscreen = True
    AXPlayerWindow._on_mpv_fullscreen(window, False)

    assert calls == ["full", "normal"]


# -- a URL is not part of the folder playlist ------------------------------
def _detached_player(loaded):
    """Enough of PlayerWidget for the unbound methods under test.

    play_url/play_path/remove_paths are pure playlist bookkeeping; building the
    real widget would start libmpv and open a window.
    """
    sent = []
    return types.SimpleNamespace(
        _loaded=list(loaded),
        _sent=sent,
        _mpv=types.SimpleNamespace(command=lambda *a: sent.append(a)),
        _mpv_cmd=lambda *a: sent.append(a),
    )


def test_playing_a_url_stops_the_first_row_replaying_it(tmp_path):
    """loadfile "replace" leaves mpv with a one-entry playlist.

    play_path addresses mpv by *index* into _loaded, so with the folder still
    listed there, clicking row 0 computed index 0 -- which the one-entry
    playlist accepts -- and restarted the URL instead of playing the file. It
    returned True as well, so open_folder()'s self-heal never ran. Rows 1+
    raised IndexError and did self-heal, which is why only the first row
    looked stuck.
    """
    from ax_player.player_widget import PlayerWidget

    playlist = [tmp_path / f"ep{i}.mkv" for i in range(3)]
    widget = _detached_player(playlist)

    PlayerWidget.play_url(widget, "https://example.com/live.m3u8")

    assert PlayerWidget.play_path(widget, playlist[0]) is False, (
        "row 0 still resolved against the folder mpv no longer holds"
    )
    assert not any(a[0] == "playlist-play-index" for a in widget._sent), (
        "an index was sent for a playlist that is now just the URL"
    )


def test_removing_the_first_row_after_a_url_does_not_drop_the_stream(tmp_path):
    """Same stale list, second consumer: 移除選取 on row 0 would have issued
    playlist-remove 0, which is the URL that is playing."""
    from ax_player.player_widget import PlayerWidget

    playlist = [tmp_path / f"ep{i}.mkv" for i in range(3)]
    widget = _detached_player(playlist)

    PlayerWidget.play_url(widget, "https://example.com/live.m3u8")
    PlayerWidget.remove_paths(widget, {playlist[0]})

    assert not any(a[0] == "playlist-remove" for a in widget._sent), (
        "removed an entry by an index that no longer means what it did"
    )


# -- what mpv is actually told on a double click ---------------------------
def test_double_clicking_the_video_sends_the_key_mpv_binds_fullscreen_to():
    """Asked of a live mpv rather than assumed:

        MBTN_LEFT      -> ignore
        MBTN_LEFT_DBL  -> cycle fullscreen

    Relaying a second MBTN_LEFT -- which is what this did -- lands on the
    binding whose whole job is to do nothing, so double-clicking the video
    never toggled fullscreen.
    """
    from PySide6.QtCore import Qt

    from ax_player.player_widget import _MOUSE_BUTTONS, _MOUSE_BUTTONS_DBL

    assert _MOUSE_BUTTONS_DBL[Qt.MouseButton.LeftButton] == "MBTN_LEFT_DBL"
    assert _MOUSE_BUTTONS[Qt.MouseButton.LeftButton] == "MBTN_LEFT"


def test_side_buttons_keep_the_plain_name_because_mpv_rejects_theirs():
    """Measured against a live mpv: MBTN_MID_DBL and MBTN_RIGHT_DBL are
    accepted, MBTN_BACK_DBL and MBTN_FORWARD_DBL are refused with "is not a
    valid input name". Sending those would write an error line into debug.log
    on every side-button double click, and debug.log noise is a problem this
    project has already had to dig out of once."""
    from PySide6.QtCore import Qt

    from ax_player.player_widget import _MOUSE_BUTTONS_DBL

    assert set(_MOUSE_BUTTONS_DBL) == {
        Qt.MouseButton.LeftButton,
        Qt.MouseButton.MiddleButton,
        Qt.MouseButton.RightButton,
    }
    assert Qt.MouseButton.BackButton not in _MOUSE_BUTTONS_DBL


# -- 含子資料夾 has to actually do something -------------------------------
def _toggle_window(recursive=False, folder=Path(r"C:\V"), current=None):
    calls = []
    return types.SimpleNamespace(
        _recursive=recursive, _folder=folder, _current=current, _calls=calls,
        open_folder=lambda f, **kw: calls.append((str(f), kw)),
    ), calls


def test_ticking_include_subfolders_re_lists_the_folder(monkeypatch):
    """It set the flag and stopped, so the list did not change until the next
    F5 or reopen and the checkbox looked broken.

    Sidebar.restore_state blocks its signals "to avoid immediately triggering
    a rescan of a folder that isn't open yet" -- which is only worth doing if
    a real toggle rescans. The code disagreed with its own note.
    """
    monkeypatch.setattr(settings, "set_recursive", lambda _on: None)
    w, calls = _toggle_window(recursive=False)

    AXPlayerWindow.set_recursive(w, True)

    assert w._recursive is True
    assert calls, "the folder was never re-listed"
    assert calls[0][0] == r"C:\V"


def test_toggling_while_playing_does_not_restart_the_video(monkeypatch):
    """Same rule set_sort_mode follows: mpv's only way to take a new playlist
    is loadlist replace, which restarts playback from the top. Re-listing the
    sidebar is not worth interrupting the video for."""
    monkeypatch.setattr(settings, "set_recursive", lambda _on: None)
    w, calls = _toggle_window(recursive=False, current=Path(r"C:\V\ep3.mkv"))

    AXPlayerWindow.set_recursive(w, True)

    assert calls[0][1]["reload_player"] is False


def test_setting_it_to_what_it_already_is_does_nothing(monkeypatch):
    monkeypatch.setattr(settings, "set_recursive", lambda _on: None)
    w, calls = _toggle_window(recursive=True)

    AXPlayerWindow.set_recursive(w, True)

    assert calls == [], "a no-op toggle rescanned the whole folder"


def test_with_no_folder_open_it_only_remembers_the_setting(monkeypatch):
    saved = []
    monkeypatch.setattr(settings, "set_recursive", saved.append)
    w, calls = _toggle_window(recursive=False, folder=None)

    AXPlayerWindow.set_recursive(w, True)

    assert saved == [True]
    assert calls == [], "there is no folder to re-list"


# -- the two request sets are not the same rule, on purpose ----------------
def test_a_thumbnail_is_grabbed_once_per_file_however_often_the_row_repaints():
    """_RowDelegate.paint asks for a thumbnail every time it paints a row
    without one. Sidebar._queue_thumb absorbs the repaints inside one
    event-loop turn -- measured: 30 paints, 1 request -- but not across turns:
    ten paints in ten turns are ten requests, which is what scrolling past an
    un-grabbable file looks like. This set is what stands between such a file
    and two mpv subprocesses per turn for as long as its row is on screen.

    Which is why it must NOT be made to match _requested_sheets, whose
    _sheet_finished discards on completion. A sheet is asked for by hovering a
    row: a deliberate, debounced act. Making these agree looks like tidying up
    and is a respawn loop.
    """
    started = []
    w = types.SimpleNamespace(
        _requested_thumbs=set(),
        _thumb_pool=types.SimpleNamespace(start=lambda _job: started.append(1)),
        _jobs=object(),
        sidebar=types.SimpleNamespace(set_thumbnail=lambda _p, _px: None),
    )
    video = Path(r"C:\V\broken.mkv")

    AXPlayerWindow.request_thumbnail(w, video)
    AXPlayerWindow._on_thumb_done(w, str(video), "")  # the grab failed
    for _ in range(20):
        AXPlayerWindow.request_thumbnail(w, video)

    assert len(started) == 1, f"a failing file span up {len(started)} grabs"


def test_reopening_the_folder_is_what_gives_a_failed_row_another_chance(monkeypatch, tmp_path):
    """The cost of the rule above is a row that stays grey. open_folder
    clearing the set is what bounds that to the current listing rather than
    the whole session."""
    w = _OpenWindow()
    w._requested_thumbs = {r"C:\V\broken.mkv"}
    (tmp_path / "vids").mkdir()
    monkeypatch.chdir(tmp_path)

    AXPlayerWindow.open_folder(w, Path("vids"))

    assert w._requested_thumbs == set()
