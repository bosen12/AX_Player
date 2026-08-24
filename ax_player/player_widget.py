from __future__ import annotations

import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent, QWheelEvent
from PySide6.QtWidgets import QWidget

from ax_player import debug_log
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
_MOUSE_BUTTONS = {
    Qt.MouseButton.LeftButton: "MOUSE_BTN0",
    Qt.MouseButton.MiddleButton: "MOUSE_BTN1",
    Qt.MouseButton.RightButton: "MOUSE_BTN2",
    Qt.MouseButton.BackButton: "MOUSE_BTN5",
    Qt.MouseButton.ForwardButton: "MOUSE_BTN6",
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

    def _mpv_cmd(self, *args: str) -> None:
        try:
            self._mpv.command(*args)
        except Exception:
            pass

    # -- playback ----------------------------------------------------------
    def load_playlist(self, videos: list[Path], start_index: int) -> None:
        """Hand the whole folder to mpv so uosc's playlist and next/prev work."""
        if not videos:
            return
        handle = tempfile.NamedTemporaryFile(
            "w", suffix=".m3u8", delete=False, encoding="utf-8", newline="\n"
        )
        with handle as fh:
            for video in videos:
                fh.write(f"{video}\n")
        old = self._list_file
        self._list_file = Path(handle.name)
        try:
            self._mpv.playlist_start = start_index
            self._mpv.command("loadlist", str(self._list_file), "replace")
        except Exception:
            pass
        if old is not None:
            old.unlink(missing_ok=True)

    def play_index(self, index: int) -> None:
        try:
            self._mpv.command("playlist-play-index", str(index))
        except Exception:
            pass

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
        debug_log.log(f"play_url: url={url!r} config_dir={default_mpv_root()} ytdlp={ytdlp_exe()}")
        try:
            self._mpv.command("loadfile", url, "replace")
            debug_log.log("play_url: loadfile command sent OK")
        except Exception:
            debug_log.log_exc("play_url: loadfile command FAILED")

    def remove_index(self, index: int) -> None:
        self._mpv_cmd("playlist-remove", str(index))

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
        name = _MOUSE_BUTTONS.get(event.button())
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
    # A real dragged hyperlink (e.g. from a browser) sets text/uri-list,
    # which QMimeData.hasUrls()/.urls() reads. Dragging plain URL *text*
    # (selected text, not a link object -- from a chat window, an address
    # bar, etc.) usually only sets text/plain, which hasUrls() ignores
    # entirely -- the drag would be silently rejected with no feedback at
    # all. Falls back to parsing plain text as one URL per line, matching
    # what the web-page drop handler (app.js) already does for drops
    # landing outside this widget's area.
    def _dropped_uris(self, mime) -> list[str]:
        if mime.hasUrls():
            return [u.toString() for u in mime.urls()]
        if mime.hasText():
            return [line.strip() for line in mime.text().splitlines() if line.strip() and not line.strip().startswith("#")]
        return []

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        uris = self._dropped_uris(event.mimeData())
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
