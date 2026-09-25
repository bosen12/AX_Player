from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QWidget

from ax_player import debug_log, dnd
from ax_player.paths import default_mpv_root, libmpv_dll, mpv_exe, ytdlp_exe

_dll = libmpv_dll()
if _dll is not None:
    # python-mpv needs libmpv on PATH before `import mpv` resolves the binding.
    os.environ["PATH"] = str(_dll.parent) + os.pathsep + os.environ.get("PATH", "")

import mpv  # noqa: E402  (deferred: needs PATH set up above)

# On Windows, libmpv's embedded child window (created for `wid`) is WS_DISABLED
# and never receives mouse input from the OS -- a documented libmpv limitation
# (see mpv-player/mpv#6762). Without forwarding events ourselves, mpv never
# learns the cursor moved, so uosc's proximity-based timeline/controls can
# never fade in and on-video clicks/drags never reach it either.

# Names are mpv's current ones (MBTN_*), not the legacy MOUSE_BTN* aliases.
# The aliases are not a straight renaming: MOUSE_BTN0/1/2 still resolve to
# MBTN_LEFT/MID/RIGHT, but MOUSE_BTN5 resolves to no key at all and
# MOUSE_BTN6 resolves to the *horizontal wheel* -- so a back/forward button
# press used to reach mpv as WHEEL_LEFT/WHEEL_RIGHT, firing whatever those
# are bound to and never the binding the user actually wrote.
_MOUSE_BUTTONS = {
    Qt.MouseButton.LeftButton: "MBTN_LEFT",
    Qt.MouseButton.MiddleButton: "MBTN_MID",
    Qt.MouseButton.RightButton: "MBTN_RIGHT",
    Qt.MouseButton.BackButton: "MBTN_BACK",
    Qt.MouseButton.ForwardButton: "MBTN_FORWARD",
}

# A double click is its own key to mpv, and for the left button it is the only
# one that does anything. Asked of a live mpv rather than assumed:
#
#     MBTN_LEFT      -> ignore
#     MBTN_LEFT_DBL  -> cycle fullscreen
#
# So relaying a second MBTN_LEFT -- which is what this did -- lands on the
# binding whose entire job is to do nothing, and double-clicking the video did
# not toggle fullscreen at all.
#
# Only these three names exist. MBTN_BACK_DBL and MBTN_FORWARD_DBL are refused
# with "is not a valid input name", which would put an error line in debug.log
# on every double click of a side button, so those keep the plain name and
# simply register as another click.
_MOUSE_BUTTONS_DBL = {
    Qt.MouseButton.LeftButton: "MBTN_LEFT_DBL",
    Qt.MouseButton.MiddleButton: "MBTN_MID_DBL",
    Qt.MouseButton.RightButton: "MBTN_RIGHT_DBL",
}

# Same WS_DISABLED story applies to the keyboard: mpv never sees a single
# keypress unless we relay it. This is why user input.conf bindings (e.g. the
# CTRL+1..9 Anime4K shortcuts, or F3 for the Fluid Motion IPC toggle) look
# like they're "not working" -- mpv is never told a key was pressed at all.
_KEY_NAMES = {
    Qt.Key.Key_Escape: "ESC",
    Qt.Key.Key_Tab: "TAB",
    Qt.Key.Key_Backtab: "TAB",
    Qt.Key.Key_Backspace: "BS",
    Qt.Key.Key_Return: "ENTER",
    Qt.Key.Key_Enter: "ENTER",
    Qt.Key.Key_Insert: "INS",
    Qt.Key.Key_Delete: "DEL",
    Qt.Key.Key_Home: "HOME",
    Qt.Key.Key_End: "END",
    Qt.Key.Key_PageUp: "PGUP",
    Qt.Key.Key_PageDown: "PGDWN",
    Qt.Key.Key_Left: "LEFT",
    Qt.Key.Key_Right: "RIGHT",
    Qt.Key.Key_Up: "UP",
    Qt.Key.Key_Down: "DOWN",
    Qt.Key.Key_Space: "SPACE",
}
for _n in range(1, 25):
    _KEY_NAMES[getattr(Qt.Key, f"Key_F{_n}")] = f"F{_n}"


def _mpv_key_name(event: QKeyEvent) -> str | None:
    key = event.key()
    if key in (Qt.Key.Key_Shift, Qt.Key.Key_Control, Qt.Key.Key_Alt, Qt.Key.Key_Meta):
        return None  # bare modifier presses aren't bindable on their own
    base = _KEY_NAMES.get(key)
    if base is None:
        if Qt.Key.Key_A <= key <= Qt.Key.Key_Z or Qt.Key.Key_0 <= key <= Qt.Key.Key_9:
            base = chr(key).lower() if key <= Qt.Key.Key_Z else chr(key)
        elif 0x20 < key < 0x7F:
            base = chr(key).lower()
        else:
            return None
    mods = event.modifiers()
    prefix = ""
    if mods & Qt.KeyboardModifier.ControlModifier:
        prefix += "Ctrl+"
    if mods & Qt.KeyboardModifier.AltModifier:
        prefix += "Alt+"
    if mods & Qt.KeyboardModifier.MetaModifier:
        prefix += "Meta+"
    if mods & Qt.KeyboardModifier.ShiftModifier:
        prefix += "Shift+"
    return prefix + base


class PlayerWidget(QWidget):
    """Embeds libmpv and lets the user's own mpv config drive playback.

    config_dir points at C:\\mpv, so mpv.conf, input.conf and the scripts dir
    all load exactly as they do in standalone mpv -- that includes uosc (the
    on-video controls and seek bar) and thumbfast (its hover previews). This
    app deliberately does not reimplement any of that; it supplies the window,
    the library sidebar, and the playlist.
    """

    path_changed = Signal(str)
    title_changed = Signal(str)
    fullscreen_changed = Signal(bool)
    files_dropped = Signal(list)  # list[str] of dropped file:// uris
    progress_changed = Signal(str, float, float)  # path, pos, duration
    fluid_active_changed = Signal(bool)

    PROGRESS_POLL_MS = 5000

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        self.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.setStyleSheet("background-color: #000000;")
        # This widget sits under the hole punched in the web view (see
        # AXPlayerWindow.set_stage_geometry), so drops landing on the video
        # itself arrive here as native Qt/OS drag-and-drop, not as a web
        # "drop" event -- the web page never sees them.
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        script_opts = "uosc-top_bar=never"
        exe = mpv_exe()
        if exe is not None:
            # thumbfast spawns its own mpv.exe subprocess for hover-preview
            # thumbnails and needs to be told where it is explicitly --
            # its auto-detection depends on a frontend setting
            # user-data/frontend/process-path, which python-mpv doesn't.
            script_opts += f",thumbfast-mpv_path={exe}"
        ytdlp = ytdlp_exe()
        if ytdlp is not None:
            # mpv's built-in ytdl_hook shells out to a yt-dlp binary rather
            # than embedding one -- without this it defaults to bare "yt-dlp"
            # on PATH, which isn't there for the bundled mpv-runtime build,
            # so "open URL" silently only works for direct media links.
            script_opts += f",ytdl_hook-ytdl_path={ytdlp}"

        self._mpv = mpv.MPV(
            wid=str(int(self.winId())),
            config=True,
            config_dir=str(default_mpv_root()),
            # Announce this instance on the pipe name Fluid Motion looks for
            # first. Without it an embedded libmpv host is invisible to FM:
            # it enumerates OS processes for mpv.exe (this one is python.exe
            # or AXPlayer.exe) and otherwise falls back to scanning named
            # pipes -- and mpv only opens a pipe at all when something sets
            # input-ipc-server.
            #
            # This is a request, not a guarantee. It used to claim that an
            # init option always wins over a script's later set_property,
            # because mpv binds the IPC listener once -- that is not what
            # mpv does. Measured with exactly this call against C:\\mpv, the
            # pipe that actually appears is mpvSockets.lua's
            # %TEMP%\\mpvSockets\\<pid>: mpv rebinds when the option changes
            # at runtime, so the last writer wins and "zz-" only guarantees
            # zz-fluid-ipc.lua loads *after* mpvSockets.lua, not before.
            #
            # Harmless either way -- Fluid Motion discovers the pid from the
            # mpvSockets pipe too (see its mpv_detect._embedded_player_pids)
            # -- so this stays as the name to prefer when nothing else has
            # taken it, e.g. a config dir without mpvSockets.lua.
            input_ipc_server=f"fluid-mpv-{os.getpid()}",
            input_default_bindings=True,
            input_vo_keyboard=True,
            idle="yes",
            # Without this, mpv doesn't touch its VO surface until a file is
            # loaded -- the embedded window sits there as a raw, unpainted
            # Win32 child (a stark light-gray box) instead of the app's dark
            # theme. force_window makes mpv paint background_color immediately.
            force_window="immediate",
            background_color="#171310",
            # uosc's own top_bar=no-border draws its own minimize/maximize/
            # close buttons on the video whenever mpv has no native window
            # border -- which mpv.conf's border=no always means. AX Player
            # already supplies real window controls in its own titlebar, and
            # uosc's close button issues mpv's own `quit`, which for an
            # embedded (wid) instance shuts mpv's core down without the Qt
            # shell knowing, hanging the app. Overriding it here (not in the
            # shared uosc.conf) only affects this embedded instance --
            # standalone mpv still gets its own top bar as configured.
            script_opts=script_opts,
            log_handler=self._on_mpv_log,
            loglevel="warn",
        )
        self._list_file: Path | None = None
        # The order mpv's own playlist is in. It is not always self._playlist
        # in app.py: a re-sort while something is playing deliberately leaves
        # mpv alone (reloading it would restart playback), and an index taken
        # from the re-sorted sidebar then addresses a different file here.
        self._loaded: list[Path] = []

        self._mpv.observe_property("path", self._on_path)
        self._mpv.observe_property("media-title", self._on_title)
        self._mpv.observe_property("fullscreen", self._on_fullscreen)
        self._mpv.observe_property("vf", self._on_vf)

        # mpv exposes time-pos/duration as properties that change continuously
        # during playback; polling occasionally is far cheaper than observing
        # and re-emitting on every frame, and the sidebar progress bar doesn't
        # need better than ~5s resolution.
        self._progress_timer = QTimer(self)
        self._progress_timer.timeout.connect(self._emit_progress)
        self._progress_timer.start(self.PROGRESS_POLL_MS)

    @staticmethod
    def _on_mpv_log(loglevel: str, component: str, message: str) -> None:
        # mpv's own warn/error log (ytdl_hook failures, network/demuxer
        # errors, etc.) previously went nowhere in a console=False build --
        # loadfile can report success (the command was merely queued) while
        # the actual stream resolution or decode fails silently afterward.
        debug_log.log(f"mpv[{loglevel}][{component}]: {message}")

    # -- property observers ------------------------------------------------
    def _on_path(self, _name, value) -> None:
        if value:
            self.path_changed.emit(str(value))

    def _on_title(self, _name, value) -> None:
        self.title_changed.emit(str(value or ""))

    def _on_fullscreen(self, _name, value) -> None:
        # uosc's fullscreen button sets mpv's own property; mirror it onto the
        # host window, otherwise only the embedded surface would change.
        self.fullscreen_changed.emit(bool(value))

    def _on_vf(self, _name, value) -> None:
        # Mirrors zz-fluid-ipc.lua's own fluid_on() check, so the UI can show
        # whether Fluid Motion's interpolation filter is currently applied.
        vf = str(value or "")
        self.fluid_active_changed.emit("@fluid" in vf or "fluid_rife" in vf)

    def _emit_progress(self) -> None:
        try:
            path = self._mpv.path
            pos = self._mpv.time_pos
            duration = self._mpv.duration
        except Exception:
            return
        if path and pos is not None and duration:
            self.progress_changed.emit(str(path), float(pos), float(duration))

    def _prop(self, name: str):
        """One mpv property, or None.

        Named with underscores: python-mpv's attribute access maps those to
        mpv's hyphenated property names. Reading an unset property raises
        rather than returning None, and between files most of these are unset.
        """
        try:
            return getattr(self._mpv, name)
        except Exception:
            return None

    def diagnostics(self) -> dict:
        """A snapshot of what mpv is actually doing right now.

        Deliberately not a reimplementation of mpv's own stats.lua (Shift+I),
        which already shows codec/resolution/cache well. This exists for the
        parts it can't answer: whether the interpolation filter is keeping up
        with the frame rate it is supposed to be producing.
        """
        vf = str(self._prop("vf") or "")
        return {
            "playing": bool(self._prop("path")),
            "width": self._prop("width"),
            "height": self._prop("height"),
            "codec": self._prop("video_format"),
            "hwdec": self._prop("hwdec_current"),
            "source_fps": self._prop("container_fps"),
            "output_fps": self._prop("estimated_vf_fps"),
            "display_fps": self._prop("display_fps"),
            "dropped": self._prop("frame_drop_count"),
            "delayed": self._prop("vo_delayed_frame_count"),
            "avsync": self._prop("avsync"),
            "cache": self._prop("demuxer_cache_duration"),
            "interpolating": "@fluid" in vf or "fluid_rife" in vf,
            # Anime4K and Fluid Motion's RIFE both run on the GPU and compete
            # for it. The only symptom of overcommitting is dropped frames,
            # which says nothing about which of the two to turn down -- so
            # report how many shader passes are loaded and let the panel say
            # when both are on at once.
            "shaders": len(self._prop("glsl_shaders") or []),
        }

    def _mpv_cmd(self, *args: str) -> None:
        try:
            self._mpv.command(*args)
        except Exception:
            pass

    # -- playback ----------------------------------------------------------
    def load_playlist(self, videos: list[Path], start_index: int) -> bool:
        """Hand the whole folder to mpv so uosc's playlist and next/prev work."""
        if not videos:
            return False
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".m3u8", delete=False, encoding="utf-8", newline="\n"
        )
        with handle as fh:
            for video in videos:
                fh.write(f"{video}\n")
        new_list = Path(handle.name)
        try:
            self._mpv.playlist_start = start_index
            self._mpv.command("loadlist", str(new_list), "replace")
        except Exception:
            debug_log.log_exc("load_playlist: loadlist command FAILED")
            new_list.unlink(missing_ok=True)
            return False
        old = self._list_file
        self._list_file = new_list
        self._loaded = list(videos)
        if old is not None:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                debug_log.log_exc("load_playlist: old list cleanup FAILED")
        return True

    def play_path(self, video: Path) -> bool:
        """Play a file by path rather than by sidebar position.

        False means mpv's playlist does not hold it, and the caller has to
        load a playlist that does.
        """
        try:
            index = self._loaded.index(video)
        except ValueError:
            return False
        try:
            self._mpv.command("playlist-play-index", str(index))
        except Exception:
            return False
        return True

    def play_url(self, url: str) -> None:
        # Not part of the folder playlist -- yt-dlp (bundled in the mpv
        # config dir) resolves streams for anything mpv itself doesn't
        # already handle natively.
        #
        # Logged explicitly (not just via _mpv_cmd's broad except) because
        # every failure report for this feature turned out impossible to
        # diagnose blind -- the packaged exe has no console, and every
        # source-checkout reproduction attempt played back fine, so the
        # actual failure, whatever it is, has to be observed from a real
        # run instead of guessed at again.
        debug_log.log(
            f"play_url: url={debug_log.safe_url(url)!r} "
            f"config_dir={default_mpv_root()} ytdlp={ytdlp_exe()}"
        )
        # "replace" leaves mpv holding a one-entry playlist, so the folder this
        # used to mirror is gone from mpv but would still be sitting in
        # _loaded. play_path() addresses mpv *by index* off that list: clicking
        # the first sidebar row computes index 0, which a one-entry playlist
        # accepts, so the URL restarts instead of the file being clicked -- and
        # play_path returns True, so open_folder()'s self-heal never runs. Rows
        # 1+ raise IndexError and do self-heal, which is why only the first row
        # looked stuck. remove_paths() has the same dependency: 移除選取 on row
        # 0 would issue playlist-remove 0 and drop the playing URL.
        try:
            self._mpv.command("loadfile", url, "replace")
            self._loaded = []
            debug_log.log("play_url: loadfile command sent OK")
        except Exception:
            debug_log.log_exc("play_url: loadfile command FAILED")

    def remove_paths(self, videos: set[Path]) -> set[Path]:
        """Drop these files from mpv's playlist, addressed by path.

        Descending order so each removal cannot shift the index of one that
        has not been removed yet.

        Returns the paths mpv's playlist no longer holds -- removed just now,
        *or never loaded in the first place*. Only a refusal keeps a path out
        of the answer. The window deletes exactly these rows, so the two
        cases must not look alike: mpv cannot refuse to drop a file it does
        not have.

        They did look alike for one release. This returned only what it had
        just removed, which made "mpv refused" and "mpv never had it" both an
        empty set, and remove_from_playlist() returns early on empty. The
        second is the state after every normal launch -- main() restores the
        library with reload_player=False, so the sidebar lists the folder
        while _loaded is still [] -- and also any row a re-sort, F5 or 含子
        資料夾 re-list surfaced while something was playing. In all of those,
        從清單移除 did nothing at all, with no log line. The window-level
        tests missed it because their fake remove_paths used set() to mean
        "refused": the fixture made the same conflation as the bug.
        """
        held = {video for video in self._loaded if video in videos}
        removed: set[Path] = set()
        indexed = ((i, video) for i, video in enumerate(self._loaded) if video in videos)
        for index, video in sorted(indexed, reverse=True):
            try:
                self._mpv.command("playlist-remove", str(index))
            except Exception:
                debug_log.log_exc(f"remove_paths: playlist-remove {index} FAILED")
                continue
            removed.add(video)
        if removed:
            self._loaded = [video for video in self._loaded if video not in removed]
        refused = held - removed
        return set(videos) - refused

    def toggle_fluid_motion(self) -> None:
        # Reuses the F3 binding zz-fluid-ipc.lua already registers, instead
        # of reimplementing its alive-check/IPC-notify dance here.
        self._mpv_cmd("keypress", "F3")

    def set_fullscreen(self, on: bool) -> None:
        try:
            self._mpv.fullscreen = bool(on)
        except Exception:
            pass

    # -- mouse forwarding ----------------------------------------------------
    # mpv's embedded window can't receive these from the OS (see the
    # WS_DISABLED note above), so every move/click/wheel is relayed through
    # mpv's own input command API instead. This is what lets uosc/thumbfast
    # see the cursor at all -- hover-to-reveal, timeline scrubbing, dragging
    # the volume/speed sliders, right-click menu, wheel-seek, etc.
    def _send_pos(self, event: QMouseEvent) -> None:
        pos = event.position()
        self._mpv_cmd("mouse", str(int(pos.x())), str(int(pos.y())))

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._send_pos(event)
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self.setFocus(Qt.FocusReason.MouseFocusReason)
        name = _MOUSE_BUTTONS.get(event.button())
        if name is not None:
            self._send_pos(event)
            self._mpv_cmd("keydown", name)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        name = _MOUSE_BUTTONS.get(event.button())
        if name is not None:
            self._mpv_cmd("keyup", name)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # Qt delivers press, release, *doubleclick*, release -- the second
        # click never arrives as a press -- so this is mpv's only chance to
        # hear about it, and it has to be told the _DBL name to act on it.
        button = event.button()
        name = _MOUSE_BUTTONS_DBL.get(button) or _MOUSE_BUTTONS.get(button)
        if name is not None:
            self._send_pos(event)
            self._mpv_cmd("keypress", name)
        super().mouseDoubleClickEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta()
        if delta.y() > 0:
            name = "WHEEL_UP"
        elif delta.y() < 0:
            name = "WHEEL_DOWN"
        elif delta.x() > 0:
            name = "WHEEL_RIGHT"
        elif delta.x() < 0:
            name = "WHEEL_LEFT"
        else:
            name = None
        if name is not None:
            self._mpv_cmd("keypress", name)
        super().wheelEvent(event)

    # -- keyboard forwarding ---------------------------------------------
    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        name = _mpv_key_name(event)
        if name is None:
            # Not a key we forward (e.g. a bare modifier) -- let Qt's normal
            # handling see it instead of swallowing it unconditionally.
            super().keyPressEvent(event)
            return
        if not event.isAutoRepeat():
            self._mpv_cmd("keydown", name)
        event.accept()

    def keyReleaseEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        name = _mpv_key_name(event)
        if name is None:
            super().keyReleaseEvent(event)
            return
        if not event.isAutoRepeat():
            self._mpv_cmd("keyup", name)
        event.accept()

    # -- drag & drop ---------------------------------------------------------
    # Drops landing on the video arrive here; drops on the window's own chrome
    # arrive at AXPlayerWindow. Both read the mime data through ax_player.dnd,
    # which is where the note about dragged links versus dragged link *text*
    # now lives -- the two handlers had a copy each.
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if dnd.has_uris(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if dnd.has_uris(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        uris = dnd.uris_from_mime(event.mimeData())
        if uris:
            self.files_dropped.emit(uris)
            event.acceptProposedAction()

    def shutdown(self) -> None:
        try:
            self._mpv.terminate()
        except Exception:
            pass
        if self._list_file is not None:
            self._list_file.unlink(missing_ok=True)
