"""Regression cover for the library/playlist routing fixed in v1.1.5-v1.1.7."""
import types
from pathlib import Path

from PySide6.QtGui import QCloseEvent

from ax_player import resume, settings
from ax_player.app import (
    THUMB_POOL_MAX,
    AXPlayerWindow,
    _emit_safely,
    _ScanJob,
    _sort_playlist,
    _thumb_pool_size,
)


class _Window:
    """Enough of AXPlayerWindow for the unbound methods under test."""

    def __init__(self, folder, playlist, recursive=False, mpv_holds=(), mpv_loads=True):
        self._folder = folder
        self._playlist = playlist
        self._recursive = recursive
        self._requested_sheets = set()
        self._holds = set(mpv_holds)
        self.opened = None
        self.selected = None
        self.loads = []

        def load_playlist(videos, index):
            self.loads.append((list(videos), index))
            return mpv_loads

        self.player = types.SimpleNamespace(
            play_path=lambda v: v in self._holds,
            load_playlist=load_playlist,
            setFocus=lambda *a: None,
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


def test_a_stale_mpv_playlist_reloads_from_the_list_on_screen():
    """mpv holds nothing -- the state after every launch, since main()
    restores the library with reload_player=False.

    This used to reopen the folder, and a rescan reads the disk: rows removed
    with 從清單移除 came back, into the sidebar and into mpv's playlist, so
    next/prev played what the user had just taken out. The listed library is
    what they are looking at, so that is what mpv gets.
    """
    w = _Window(ROOT, LISTED, recursive=True)  # mpv holds nothing
    AXPlayerWindow.play(w, SUB / "b.mp4")
    assert w.opened is None, "a click is not a refresh; nothing should be rescanned"
    assert w.loads == [(LISTED, 1)], "mpv must get the listed library, at the clicked row"


def test_a_refused_reload_falls_back_to_rescanning_the_library_root():
    """The rescan survives as the fallback, and keeps its own guarantee:
    reopen the library root, not the subdirectory the file happens to be in."""
    w = _Window(ROOT, LISTED, recursive=True, mpv_loads=False)
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
        _list_file=None,
        _sent=sent,
        _mpv=types.SimpleNamespace(command=lambda *a: sent.append(a)),
        _mpv_cmd=lambda *a: sent.append(a),
    )


def test_rejected_playlist_load_keeps_the_previous_mirror(tmp_path):
    from ax_player.player_widget import PlayerWidget

    old = [tmp_path / "old-1.mkv", tmp_path / "old-2.mkv"]
    new = [tmp_path / "new-1.mkv", tmp_path / "new-2.mkv"]
    old_list = tmp_path / "old.m3u8"
    old_list.write_text("old", encoding="utf-8")

    class RejectingMpv:
        playlist_start = 0

        def command(self, *_args):
            raise RuntimeError("loadlist rejected")

    widget = types.SimpleNamespace(
        _loaded=list(old), _list_file=old_list, _mpv=RejectingMpv()
    )

    assert PlayerWidget.load_playlist(widget, new, 1) is False
    assert widget._loaded == old
    assert widget._list_file == old_list
    assert old_list.exists()


def test_rejected_playlist_removal_keeps_the_path_to_index_mirror(tmp_path):
    from ax_player.player_widget import PlayerWidget

    playlist = [tmp_path / f"ep{i}.mkv" for i in range(3)]

    class RejectingMpv:
        def command(self, *_args):
            raise RuntimeError("playlist-remove rejected")

    widget = types.SimpleNamespace(_loaded=list(playlist), _mpv=RejectingMpv())
    widget._mpv_cmd = types.MethodType(PlayerWidget._mpv_cmd, widget)

    assert PlayerWidget.remove_paths(widget, {playlist[1]}) == set()
    assert widget._loaded == playlist


def test_rejected_url_load_keeps_the_folder_playlist_mirror(tmp_path):
    from ax_player.player_widget import PlayerWidget

    playlist = [tmp_path / f"ep{i}.mkv" for i in range(2)]

    class RejectingMpv:
        def command(self, *_args):
            raise RuntimeError("loadfile rejected")

    widget = types.SimpleNamespace(_loaded=list(playlist), _mpv=RejectingMpv())

    PlayerWidget.play_url(widget, "https://example.com/live.m3u8")

    assert widget._loaded == playlist


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


# -- how many frame-grabs may run at once ---------------------------------
def test_a_small_machine_gets_fewer_grabs_than_it_used_to():
    """The old rule was min(max(cpu_count, 2), 4), i.e. 4 on anything with four
    or more cores -- a four-core laptop with integrated graphics gave every one
    of them to background thumbnailing while a video was playing.

    That is the machine the measurement behind THUMB_POOL_MAX could not cover
    (24 logical CPUs, RTX 5070 Ti here), so the formula has to be *lower* than
    the old constant wherever it is in doubt, not just higher where it is not.
    """
    assert _thumb_pool_size(4) == 2, "a four-core machine kept the old cap"
    assert _thumb_pool_size(6) == 3
    assert _thumb_pool_size(8) == 4, "eight cores is where it matches the old 4"


def test_a_big_machine_is_allowed_more_but_not_unbounded():
    """Measured with a 1080p HEVC file playing on gpu-next, 12 uncached 1080p
    HEVC grabs: cap 4 2.12s, cap 8 1.43s, cap 12 1.24s, and zero dropped or
    delayed frames at every setting. 8 is the knee -- 8 to 12 buys 0.19s -- and
    a ceiling is what keeps a queued folder from becoming one process per file.
    """
    assert _thumb_pool_size(16) == THUMB_POOL_MAX
    assert _thumb_pool_size(24) == THUMB_POOL_MAX
    assert _thumb_pool_size(128) == THUMB_POOL_MAX, "no ceiling at all"


def test_the_pool_never_collapses_to_a_single_worker():
    """os.cpu_count() returns None when it cannot tell, and 1 exists. Either
    one dropping the pool to a single thread would serialise a folder open
    behind one mpv process at a time.
    """
    assert _thumb_pool_size(None) == 2
    assert _thumb_pool_size(1) == 2
    assert _thumb_pool_size(0) == 2


# -- the three ways a contact sheet is asked for ---------------------------
class _SheetWindow:
    """Enough of AXPlayerWindow for request_contact_sheet."""

    def __init__(self):
        self._requested_sheets = set()
        self.queued = []
        self.shown = []
        self._sheet_signals = object()
        self._thumb_pool = types.SimpleNamespace(
            start=lambda job, priority=0: self.queued.append(priority)
        )
        self.sidebar = types.SimpleNamespace(
            show_contact_sheet=lambda path, pixmap: self.shown.append((path, pixmap))
        )


def _cached_sheet_for(video: Path) -> Path:
    from ax_player import contact_sheets

    dest = contact_sheets.cached_sheet_path(video)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(b"x" * 64)
    return dest


def test_a_sheet_already_on_disk_skips_the_thread_pool(tmp_path):
    """A repeat hover, an eager pre-generation, or a sheet from an earlier
    session: all three land here, and all three have to feel instant. Paying a
    thread hop for a file that is already there is the one thing this branch
    exists to avoid."""
    video = tmp_path / "ep1.mkv"
    video.write_bytes(b"x" * 32)
    _cached_sheet_for(video)
    w = _SheetWindow()

    AXPlayerWindow.request_contact_sheet(w, str(video))

    assert w.queued == [], "queued a job for a sheet that was already cached"
    assert [p for p, _ in w.shown] == [str(video)], "the cached sheet was never handed back"
    assert w._requested_sheets == set(), "a cache hit should not be recorded as in flight"


def test_a_sheet_already_being_generated_is_not_queued_twice(tmp_path):
    """The eager sweep from _on_folder_scanned and a live hover race for the
    same file, and each queued job is two mpv subprocesses."""
    video = tmp_path / "ep2.mkv"
    video.write_bytes(b"x" * 32)
    w = _SheetWindow()

    AXPlayerWindow.request_contact_sheet(w, str(video), priority=-1)
    AXPlayerWindow.request_contact_sheet(w, str(video))

    assert w.queued == [-1], f"queued {len(w.queued)} jobs for one file"
    assert w.shown == [], "showed a sheet that has not been generated yet"


def test_a_hover_outranks_the_background_sweep(tmp_path):
    """_queue_all_contact_sheets queues at -1 so a row the user is actually
    looking at jumps the line ahead of twelve it has not asked for."""
    eager = tmp_path / "ep3.mkv"
    hovered = tmp_path / "ep4.mkv"
    for f in (eager, hovered):
        f.write_bytes(b"x" * 32)
    w = _SheetWindow()

    AXPlayerWindow.request_contact_sheet(w, str(eager), priority=-1)
    AXPlayerWindow.request_contact_sheet(w, str(hovered))

    assert w.queued == [-1, 0], f"priorities came out as {w.queued}"


def test_a_subfolder_the_scan_cannot_open_is_reported(tmp_path, monkeypatch):
    """os.walk's default is to drop an unreadable directory without a word.

    _scan used to call it that way, and run()'s `except OSError` could not
    help -- os.walk never raises one. A folder half of which could not be read
    listed as a folder that simply had fewer episodes, which is exactly what a
    folder with fewer episodes looks like.

    Demonstrated on a six-file tree with one subfolder denied via icacls:
    three files listed, nothing raised, nothing logged. The likeliest trigger
    is not permissions but path length -- over 260 characters fails unless the
    machine has LongPathsEnabled, which Windows still ships off, and a nested
    "[SubsPlease] ... (1080p) [Batch]" folder reaches that without trying.

    The files stay unreadable either way. What changes is that the omission
    leaves a trace.
    """
    import os

    from ax_player import debug_log

    readable = tmp_path / "season 1"
    readable.mkdir()
    (readable / "ep01.mkv").write_bytes(b"")
    blocked = tmp_path / "season 2"
    blocked.mkdir()
    (blocked / "ep02.mkv").write_bytes(b"")

    # A real OSError travelling os.walk's real code path, rather than a fake
    # walk: os.walk calls os.scandir, and only this one directory refuses.
    real_scandir = os.scandir

    def refusing(path=".", *args, **kwargs):
        if Path(path) == blocked:
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path, *args, **kwargs)

    monkeypatch.setattr(os, "scandir", refusing)

    found = _scan(tmp_path, recursive=True)

    assert found == ["ep01.mkv"], "the readable half must still be listed"
    text = debug_log.path().read_text(encoding="utf-8", errors="replace")
    assert "season 2" in text, (
        "the unreadable subtree was dropped with no trace; a bug report about "
        "missing episodes would have nothing to go on"
    )


def test_closing_hides_the_window_before_tearing_mpv_down(qapp, monkeypatch, tmp_path):
    """The order in closeEvent is the whole reason a close feels instant.

    Tearing mpv down takes ~0.5s (GPU context release plus mpv's watch-later
    write), and Qt only hides the window after closeEvent returns -- so doing
    it in the obvious order leaves the window on screen, frozen, for that
    long. hide() plus a forced repaint first is what moves it behind a window
    that is already gone.

    Measured while writing this: the process itself does *not* leave when the
    window does. Exit waits for every frame grab already on a pool thread --
    2.2s with none running, 8.4s with one that had 6s left, 20.2s with one
    stalled into GRAB_TIMEOUT. So the wait _emit_safely's docstring describes
    avoiding is not avoided; it is merely spent behind a hidden window, which
    is the part worth protecting and the part nothing was checking.
    """
    from PySide6.QtWidgets import QWidget

    from ax_player import app as app_mod
    from ax_player import settings as settings_mod

    order = []

    class _Stub(app_mod.AXPlayerWindow):
        # Skips AXPlayerWindow.__init__, which builds a real libmpv player.
        def __init__(self):
            QWidget.__init__(self)
            self.sidebar = types.SimpleNamespace(unwatched_only=lambda: False)
            self.player = types.SimpleNamespace(
                shutdown=lambda: order.append("player.shutdown")
            )
            self._thumb_pool = types.SimpleNamespace(
                clear=lambda: order.append("thumb_pool.clear")
            )
            self._scan_pool = types.SimpleNamespace(clear=lambda: None)

        def hide(self):
            order.append("hide")
            super().hide()

    monkeypatch.setattr(settings_mod, "set_geometry", lambda _g: None)
    monkeypatch.setattr(settings_mod, "set_unwatched_only", lambda _v: None)
    monkeypatch.setattr(settings_mod, "flush", lambda: None)

    window = _Stub()
    try:
        window.closeEvent(QCloseEvent())
    finally:
        window.deleteLater()

    assert "hide" in order, "the window was never hidden by closeEvent"
    assert order.index("hide") < order.index("player.shutdown"), (
        f"mpv is torn down before the window is hidden ({order}) -- that is "
        "~0.5s of a frozen window still on screen"
    )
    assert order.index("thumb_pool.clear") < order.index("player.shutdown"), (
        "queued grabs are dropped after the teardown they were meant to skip"
    )


# -- sorting names the library actually contains ----------------------------
def test_a_part_marker_in_one_filename_does_not_take_out_the_folder():
    r"""①②③ / ⑴⑵⑶ / ❶❷❸ are Numeric_Type=Digit but not category Nd.

    str.isdigit() says yes for 128 such characters; the \d that split the
    name never matched them, and int() rejects them. One of them standing
    alone as a part -- it only has to be flanked by digit runs, or start the
    name -- made the sort key raise, and _ScanJob.run() caught OSError and
    nothing else. The folder then never listed at all.
    """
    names = ["ep1.mkv", "ep2.mkv", "ep10.mkv", "①1.mkv", "1① 2.mkv"]

    ordered = _sort_playlist([Path(n) for n in names], settings.SORT_NAME)

    assert len(ordered) == len(names), "the sort dropped or duplicated a file"
    assert [p.name for p in ordered][:3] == ["ep1.mkv", "ep2.mkv", "ep10.mkv"], (
        "the ordinary episodes must still sort numerically among themselves"
    )


def test_the_scan_job_reports_a_sort_it_could_not_finish(tmp_path, monkeypatch):
    """`done` is not optional, and neither is saying why it is empty.

    run() executes on a pool thread, so an escaping exception goes to a
    stderr a windowed build does not have -- and the sidebar, never having
    been told anything, keeps showing the previous folder. An empty list is
    still a wrong answer, so the log line is the only thing that makes the
    difference between "this broke" and "there was nothing here".
    """
    from ax_player import app as app_mod
    from ax_player import debug_log

    (tmp_path / "ep01.mkv").write_bytes(b"")

    def exploding(paths, mode):
        raise ValueError("invalid literal for int() with base 10: '①'")

    monkeypatch.setattr(app_mod, "_sort_playlist", exploding)

    seen = []
    signals = app_mod._ScanSignals()
    signals.done.connect(lambda *args: seen.append(args))
    job = _ScanJob(tmp_path, False, None, signals, settings.SORT_NAME, False)

    job.run()

    assert seen, "done was never emitted; the sidebar waits on it forever"
    assert seen[0][1] == [], "a failed sort must not report a playlist it does not have"
    text = debug_log.path().read_text(encoding="utf-8", errors="replace")
    assert "ValueError" in text and "scan/sort" in text, (
        "the folder came back empty with no trace of why"
    )


def test_a_removed_row_stays_removed_through_the_first_click(qapp, tmp_path):
    """The whole flow a user walks after launching, on the real pieces.

    main() restores the library without loading mpv, the user takes a row out
    with 從清單移除, then clicks another. Two releases each broke one half:
    v1.3.9's remove did nothing in this state at all, and every release before
    it let the removal through only for the click to rescan the disk and bring
    the row back -- into the sidebar and into mpv's playlist.
    """
    from ax_player import ui
    from ax_player.app import _ScanSignals
    from ax_player.player_widget import PlayerWidget

    folder = tmp_path.resolve()
    for i in range(1, 6):
        (folder / f"ep{i}.mkv").write_bytes(b"")

    class Mpv:
        playlist_start = 0

        def command(self, *args):
            pass

    player = types.SimpleNamespace(
        _loaded=[], _list_file=None, _mpv=Mpv(), setFocus=lambda *a: None
    )
    for name in ("remove_paths", "play_path", "load_playlist"):
        setattr(player, name, types.MethodType(getattr(PlayerWidget, name), player))

    window = types.SimpleNamespace(
        _folder=None, _playlist=[], _listed=None, _recursive=False,
        _sort_mode=settings.SORT_NAME, _current=None,
        sidebar=ui.Sidebar(), player=player, rescans=0,
        _queue_all_contact_sheets=lambda: None,
    )
    for name in ("play", "remove_from_playlist", "_on_folder_scanned",
                 "_playlist_items", "_first_unwatched_index"):
        setattr(window, name, types.MethodType(getattr(AXPlayerWindow, name), window))

    def open_folder(target, select=None, *, reload_player=True):
        window.rescans += 1
        window._folder = Path(target).resolve()
        signals = _ScanSignals()
        signals.done.connect(window._on_folder_scanned)
        _ScanJob(window._folder, False, select, signals, window._sort_mode, reload_player).run()

    window.open_folder = open_folder

    window.open_folder(folder, reload_player=False)  # what main() does
    window.remove_from_playlist([str(folder / "ep2.mkv")])
    window.play(folder / "ep4.mkv")

    listed = [Path(p).name for p in window.sidebar._rows]
    handed = [p.name for p in player._loaded]
    assert "ep2.mkv" not in listed, "the click rescanned the disk and the row came back"
    assert "ep2.mkv" not in handed, "mpv's next/prev would play the removed episode"
    assert handed == ["ep1.mkv", "ep3.mkv", "ep4.mkv", "ep5.mkv"]
    assert window.rescans == 1, "only the launch should have scanned"
    window.sidebar.deleteLater()


# -- restoring the last library without freezing the window -----------------
def test_find_library_answers_without_raising(tmp_path, monkeypatch):
    from ax_player import app as app_mod

    assert app_mod._find_library(str(tmp_path)) == str(tmp_path.resolve())
    assert app_mod._find_library(str(tmp_path / "gone")) is None

    def unreachable(self):
        raise OSError(64, "The specified network name is no longer available")

    monkeypatch.setattr(Path, "is_dir", unreachable)
    assert app_mod._find_library(str(tmp_path)) is None


def test_restoring_the_library_does_not_block_the_calling_thread(qapp, tmp_path, monkeypatch):
    """With the library on a NAS that is off, the first call that touches the
    share took 21 s. main() made that call on the UI thread before app.exec(),
    so every such launch showed a window "Not Responding" for 21 seconds.

    The fake below blocks until released, standing in for that timeout: the
    call has to return while it is still blocked, and the question has to have
    been asked on some other thread.
    """
    import threading
    import time

    from ax_player import app as app_mod

    release = threading.Event()
    asked_on = []

    def slow_share(folder):
        asked_on.append(threading.current_thread())
        release.wait(5)
        return str(tmp_path)

    monkeypatch.setattr(app_mod, "_find_library", slow_share)
    opened = []

    # A QObject living on this (the UI) thread, borrowing the real slot --
    # because that is what receives the signal in the app: AXPlayerWindow is a
    # QObject, so the answer is queued to its thread. The first version used a
    # SimpleNamespace here, and on CI (windows-latest, 3.10) the queued call
    # never arrived within 5 s: 0 of 48 local runs reproduced it, and PySide6
    # routes a non-QObject callable through a hidden receiver whose thread is
    # its own business. Testing the shape the app actually has.
    from PySide6.QtCore import QObject

    class Window(QObject):
        _on_library_found = AXPlayerWindow._on_library_found

        def __init__(self):
            super().__init__()
            self._folder = None
            self._restore_signals = app_mod._RestoreSignals(self)
            self._restore_signals.found.connect(self._on_library_found)

        def open_folder(self, folder, **kw):
            opened.append((folder, kw))

    window = Window()

    started = time.perf_counter()
    AXPlayerWindow.restore_library(window, "any")
    returned_after = time.perf_counter() - started
    assert returned_after < 0.5, f"restore_library held its caller for {returned_after:.2f}s"

    release.set()
    deadline = time.monotonic() + 5
    while not opened and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)

    assert asked_on and asked_on[0] is not threading.main_thread(), "the share was asked on the UI thread"
    assert opened == [(Path(tmp_path), {"reload_player": False})], (
        "a found library must be listed without being handed to mpv"
    )


def test_a_late_answer_does_not_replace_a_folder_opened_meanwhile():
    """The check can take 21 s. Whatever the user opened in that time is the
    newer request; the restore must not pull the window back to last time."""
    opened = []
    window = types.SimpleNamespace(
        _folder=Path("C:/Newer"), open_folder=lambda folder, **kw: opened.append(folder)
    )
    AXPlayerWindow._on_library_found(window, "C:/Last")
    assert opened == []


def test_main_does_not_touch_the_library_path_on_the_ui_thread():
    """The restore branch of main() runs before app.exec(): any filesystem
    call there blocks the window for as long as the share takes to fail."""
    import ast
    import inspect

    from ax_player import app as app_mod

    tree = ast.parse(inspect.getsource(app_mod.main))
    branches = [
        node.orelse
        for node in ast.walk(tree)
        if isinstance(node, ast.If) and isinstance(node.test, ast.Name) and node.test.id == "targets"
    ]
    assert len(branches) == 1 and branches[0], "could not find main()'s restore branch"
    restore = ast.Module(body=branches[0], type_ignores=[])

    touched = [
        node.func.attr
        for node in ast.walk(restore)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"is_dir", "exists", "resolve", "is_file", "stat", "open_folder"}
    ]
    assert not touched, f"main()'s restore branch calls {touched} on the UI thread"
    assert any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "restore_library"
        for node in ast.walk(restore)
    ), "main() no longer restores the last library at all"


def test_relisting_the_open_folder_does_not_touch_the_share(tmp_path, monkeypatch):
    """F5, a re-sort and 含子資料夾 all hand self._folder back to open_folder().
    It was resolved when first opened; resolving it again is a no-op that
    still goes to the share -- 21 s of a frozen window once a NAS has gone to
    sleep. The scan that follows fails on a worker thread instead."""
    canonical = tmp_path.resolve()
    started = []
    window = types.SimpleNamespace(
        _folder=canonical,
        _requested_thumbs=set(),
        _recursive=False,
        _sort_mode=settings.SORT_NAME,
        _scan_signals=None,
        _scan_pool=types.SimpleNamespace(start=lambda job: started.append(job)),
    )
    real_resolve = Path.resolve
    resolved = []

    def recording_resolve(self, *args, **kwargs):
        resolved.append(self)
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", recording_resolve)

    # Same folder, spelled in a different case: Windows paths compare equal.
    AXPlayerWindow.open_folder(window, Path(str(canonical).upper()), reload_player=False)
    assert resolved == [], "re-listing the open folder went back to the share"
    assert str(window._folder) == str(canonical), "the canonical spelling was replaced"
    assert len(started) == 1, "the re-list must still scan"

    other = tmp_path / "other"
    other.mkdir()
    AXPlayerWindow.open_folder(window, other, reload_player=False)
    assert resolved, "control: a folder that is not the open one is still resolved"


def test_playing_a_listed_row_does_not_touch_the_share(monkeypatch):
    """A listed row came out of a scan of a resolved folder. play() resolving
    it again cost nothing locally and 21 s per click once the NAS dropped off."""
    handed = []
    w = _Window(ROOT, LISTED, recursive=True, mpv_holds=LISTED)
    w.player.play_path = lambda v: (handed.append(v), v in w._holds)[1]

    resolved = []
    real_resolve = Path.resolve

    def recording_resolve(self, *args, **kwargs):
        resolved.append(self)
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", recording_resolve)

    AXPlayerWindow.play(w, Path(str(SUB / "b.mp4").upper()))
    assert resolved == [], "clicking a listed row went back to the share"
    assert handed and str(handed[0]) == str(SUB / "b.mp4"), (
        "mpv must be given the listed, canonical spelling"
    )

    AXPlayerWindow.play(w, Path("relative.mp4"))
    assert resolved, "control: an unlisted, relative path is still resolved"


def test_reveal_hands_explorer_one_glued_command_line(tmp_path, monkeypatch):
    """explorer parses its own command line, and /select has to stay glued to
    the path by the comma. An argument list goes through list2cmdline, which
    quotes the pair as one token -- and explorer then opens Documents."""
    from ax_player import app as app_mod

    video = tmp_path / "第1話 ep.mkv"
    video.write_bytes(b"")
    launched = []
    monkeypatch.setattr(app_mod.subprocess, "Popen", lambda cmd, *a, **kw: launched.append(cmd))

    app_mod._reveal(video)
    assert launched == [f'explorer /select,"{video}"'], launched

    launched.clear()
    app_mod._reveal(tmp_path / "gone.mkv")
    assert launched == [], "a missing file would open Documents instead"


def test_reveal_does_not_block_the_ui_thread(monkeypatch):
    """exists() on a share that has gone to sleep is 21 s; it must not be the
    window's 21 s."""
    import threading
    import time

    from ax_player import app as app_mod

    release = threading.Event()
    ran_on = []

    def slow_reveal(video):
        ran_on.append(threading.current_thread())
        release.wait(5)

    monkeypatch.setattr(app_mod, "_reveal", slow_reveal)
    started = time.perf_counter()
    AXPlayerWindow.reveal_in_explorer(None, "C:/nas/ep.mkv")
    took = time.perf_counter() - started
    release.set()
    deadline = time.monotonic() + 5
    while not ran_on and time.monotonic() < deadline:
        time.sleep(0.01)

    assert took < 0.5, f"reveal_in_explorer held the UI thread for {took:.2f}s"
    assert ran_on and ran_on[0] is not threading.main_thread()
