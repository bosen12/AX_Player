from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QObject, QRect, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QIcon, QRegion
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

from ax_player.bridge import Bridge, to_url
from ax_player.paths import icon_path, is_video_file, web_dir
from ax_player.player_widget import PlayerWidget
from ax_player.thumbnails import generate_thumbnail

RESIZE_MARGIN = 6


class _LoggingPage(QWebEnginePage):
    """Surfaces JS errors on stderr -- otherwise a broken handler fails silently."""

    def javaScriptConsoleMessage(self, level, message, line, source):  # noqa: N802
        print(f"[web:{line}] {message}", file=sys.stderr, flush=True)


class _JobSignals(QObject):
    thumb_done = Signal(str, str)


class _ThumbJob(QRunnable):
    def __init__(self, video: Path, signals: _JobSignals):
        super().__init__()
        self._video = video
        self._signals = signals

    @Slot()
    def run(self) -> None:
        path = generate_thumbnail(self._video)
        self._signals.thumb_done.emit(str(self._video), to_url(path) if path else "")


class AXPlayerWindow(QWidget):
    """Frameless shell: a web view draws the chrome + library sidebar, and
    mpv (with the user's own uosc/thumbfast scripts) owns everything about
    actually playing video -- controls, seek bar, hover previews, playlist
    advance, resume-on-reopen. This app supplies the window and the browsable
    folder view; it does not reimplement a player mpv already has tuned.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AX Player")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(860, 520)
        self.setMouseTracking(True)
        self.resize(1320, 780)
        icon_file = icon_path()
        if icon_file.is_file():
            self.setWindowIcon(QIcon(str(icon_file)))

        self._folder: Path | None = None
        self._playlist: list[Path] = []
        # Bulk thumbnail work is capped and separate from everything else, so
        # a folder of thousands of files can't starve the UI thread pool.
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(3)
        self._requested_thumbs: set[str] = set()

        self._jobs = _JobSignals()
        self._jobs.thumb_done.connect(self._on_thumb_done)

        self.web = QWebEngineView(self)
        self.web.setPage(_LoggingPage(self.web))
        settings = self.web.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.ShowScrollBars, False)
        self.web.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.web.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.bridge = Bridge(self)
        channel = QWebChannel(self)
        channel.registerObject("bridge", self.bridge)
        self.web.page().setWebChannel(channel)
        self.web.load(QUrl.fromLocalFile(str(web_dir() / "index.html")))

        # mpv sits *behind* the web view. The web view is masked to a hole
        # over the stage rect (see set_stage_geometry) so mouse input actually
        # reaches mpv/uosc there instead of being captured by the (visually
        # transparent, but still input-opaque) native web widget on top.
        self.player = PlayerWidget(self)
        self.player.title_changed.connect(self.bridge.titleChanged.emit)
        self.player.path_changed.connect(self._on_path_changed)
        self.player.fullscreen_changed.connect(self._on_mpv_fullscreen)
        self.player.files_dropped.connect(self.open_dropped)
        self.player.lower()
        self.web.raise_()
        self.player.setFocus(Qt.FocusReason.OtherFocusReason)

        self._stage_rect = QRect()
        self.setAcceptDrops(True)

    # -- layout --------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        self.web.setGeometry(self.rect())
        if self.isFullScreen():
            # In fullscreen the sidebar/titlebar are hidden, so the stage is
            # always the whole window -- set it synchronously here instead of
            # waiting on the web page's ResizeObserver -> bridge round trip.
            # That round trip lags one frame behind this resize, and until it
            # lands the mpv widget is still sized for the old windowed stage
            # rect while the web view (now covering the full screen) repaints
            # blank around it -- the "tiny video box in a white screen" bug.
            rect = self.rect()
            self.set_stage_geometry(rect.x(), rect.y(), rect.width(), rect.height())
        super().resizeEvent(event)

    def set_stage_geometry(self, x: int, y: int, w: int, h: int) -> None:
        rect = QRect(x, y, max(1, w), max(1, h))
        if rect == self._stage_rect:
            return
        self._stage_rect = rect
        self._apply_stage_mask()

    def _apply_stage_mask(self) -> None:
        rect = self._stage_rect
        if not rect.isValid():
            return
        self.player.setGeometry(rect)
        self.player.show()
        # Punch a real input hole in the web view: everything outside `rect`
        # stays a normal interactive page; inside it, clicks/drags fall
        # through to the mpv widget beneath.
        mask = QRegion(self.web.rect())
        mask -= QRegion(rect)
        self.web.setMask(mask)

    # -- frameless chrome -------------------------------------------------
    def minimize_window(self) -> None:
        self.showMinimized()

    def toggle_maximize(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()
        self.bridge.maximizedChanged.emit(self.isMaximized())

    def close_window(self) -> None:
        self.close()

    def start_window_drag(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def _edges_at(self, pos) -> Qt.Edges:
        edges = Qt.Edge(0)
        if pos.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= self.width() - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= self.height() - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and not self.isMaximized():
            edges = self._edges_at(event.position().toPoint())
            if edges:
                handle = self.windowHandle()
                if handle is not None:
                    handle.startSystemResize(edges)
                    event.accept()
                    return
        super().mousePressEvent(event)

    def _on_mpv_fullscreen(self, on: bool) -> None:
        # uosc's own fullscreen button sets mpv's `fullscreen` property, which
        # does nothing to an embedded (wid=) window on its own -- this is what
        # actually fullscreens the Qt window and hides the sidebar/titlebar.
        if on and not self.isFullScreen():
            self.showFullScreen()
        elif not on and self.isFullScreen():
            self.showNormal()
        self.bridge.fullscreenChanged.emit(on)

    # -- library -----------------------------------------------------------
    def pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "開啟資料夾")
        if path:
            self.open_folder(Path(path))

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "開啟影片")
        if path:
            self.play(Path(path))

    def open_folder(self, folder: Path, select: Path | None = None) -> None:
        self._folder = folder
        self._playlist = sorted(
            (p for p in folder.iterdir() if p.is_file() and is_video_file(p)),
            key=lambda p: p.name.lower(),
        )
        self._requested_thumbs.clear()
        items = [{"path": str(p), "name": p.name} for p in self._playlist]
        self.bridge.folderOpened.emit(folder.name or str(folder), items)
        index = self._playlist.index(select) if select in self._playlist else 0
        self.player.load_playlist(self._playlist, index)
        self.player.setFocus(Qt.FocusReason.OtherFocusReason)

    def request_thumbnail(self, video: Path) -> None:
        key = str(video)
        if key in self._requested_thumbs:
            return
        self._requested_thumbs.add(key)
        self._thumb_pool.start(_ThumbJob(video, self._jobs))

    def play(self, video: Path) -> None:
        video = Path(video).resolve()
        if self._folder is None or video.parent != self._folder:
            self.open_folder(video.parent, select=video)
            return
        self.player.play_index(self._playlist.index(video))
        self.player.setFocus(Qt.FocusReason.OtherFocusReason)

    def _on_path_changed(self, path: str) -> None:
        self.bridge.nowPlaying.emit(str(Path(path)))

    def _on_thumb_done(self, path: str, url: str) -> None:
        if url:
            self.bridge.thumbnailReady.emit(path, url)

    # -- drag & drop ---------------------------------------------------------
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        urls = event.mimeData().urls()
        if urls:
            self.open_dropped([u.toString() for u in urls])
            event.acceptProposedAction()

    def open_dropped(self, uris: list[str]) -> None:
        paths = [Path(QUrl(u).toLocalFile()) for u in uris if u]
        paths = [p for p in paths if str(p)]
        if not paths:
            return
        first = paths[0]
        if first.is_dir():
            self.open_folder(first)
            return
        videos = [p for p in paths if p.is_file() and is_video_file(p)]
        if videos:
            self.play(videos[0])

    def closeEvent(self, event) -> None:  # noqa: N802
        self.player.shutdown()
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("AX Player")
    icon_file = icon_path()
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))

    window = AXPlayerWindow()
    window.show()

    targets = [a for a in argv[1:] if not a.startswith("-")]
    if targets:
        target = Path(targets[0])
        if target.is_file():
            window.play(target)
        elif target.is_dir():
            window.open_folder(target)

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
