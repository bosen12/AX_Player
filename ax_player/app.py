from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QRect, QRunnable, QThread, QThreadPool, QUrl, Qt, Signal, Slot
from PySide6.QtGui import QIcon, QRegion
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox, QProgressDialog, QWidget

from ax_player import resume
from ax_player.bridge import Bridge, to_url
from ax_player.paths import VIDEO_EXTENSIONS, icon_path, is_video_file, web_dir
from ax_player.player_widget import PlayerWidget
from ax_player.thumbnails import generate_thumbnail, prune_thumbnail_cache

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


class _PruneCacheJob(QRunnable):
    @Slot()
    def run(self) -> None:
        prune_thumbnail_cache()


class _ScanSignals(QObject):
    done = Signal(str, list, str)  # folder path, [str video path], select path ("" for none)


class _ScanJob(QRunnable):
    """Directory scan + sort runs here instead of the UI thread -- a folder
    with thousands of files (or a recursive scan) would otherwise freeze
    dragging/clicking for as long as the scan takes.
    """

    def __init__(self, folder: Path, recursive: bool, select: Path | None, signals: _ScanSignals):
        super().__init__()
        self._folder = folder
        self._recursive = recursive
        self._select = select
        self._signals = signals

    @Slot()
    def run(self) -> None:
        try:
            entries = self._folder.rglob("*") if self._recursive else self._folder.iterdir()
            playlist = sorted(
                (p for p in entries if p.is_file() and is_video_file(p)),
                key=lambda p: p.name.lower(),
            )
        except OSError:
            playlist = []
        self._signals.done.emit(
            str(self._folder), [str(p) for p in playlist], str(self._select) if self._select else ""
        )


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
        self._recursive = False
        # Bulk thumbnail work is capped and separate from everything else, so
        # a folder of thousands of files can't starve the UI thread pool.
        # Each frame-grab is its own mpv.exe subprocess doing hardware decode
        # -- GPU decode sessions are a hard-limited resource (and shared with
        # both the main embedded mpv instance and thumbfast's own on-demand
        # subprocess for hover previews), not just CPU cores, so this stays
        # capped low rather than scaling up with core count: too many at once
        # is exactly what produces "thumbfast: cannot create mpv subprocess".
        self._thumb_pool = QThreadPool(self)
        self._thumb_pool.setMaxThreadCount(min(max(os.cpu_count() or 4, 2), 4))
        self._requested_thumbs: set[str] = set()

        self._jobs = _JobSignals()
        self._jobs.thumb_done.connect(self._on_thumb_done)

        # Directory scans run one at a time; a second open_folder() while one
        # is still scanning naturally queues behind it, and _on_folder_scanned
        # discards stale results if a third supersedes both.
        self._scan_pool = QThreadPool(self)
        self._scan_pool.setMaxThreadCount(1)
        self._scan_signals = _ScanSignals(self)
        self._scan_signals.done.connect(self._on_folder_scanned)

        self._thumb_pool.start(_PruneCacheJob())

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
        self.player.progress_changed.connect(self._on_progress)
        self.player.fluid_active_changed.connect(self.bridge.fluidActiveChanged.emit)
        self.player.lower()
        self.web.raise_()
        self.player.setFocus(Qt.FocusReason.OtherFocusReason)

        self._stage_rect = QRect()
        self.setAcceptDrops(True)

    # -- layout --------------------------------------------------------
    def resizeEvent(self, event) -> None:  # noqa: N802
        if self.isFullScreen():
            # The web view is hidden during fullscreen entirely (see
            # _on_mpv_fullscreen) -- nothing to give it geometry for. Just
            # keep the player widget filling the window in case it resizes
            # while still fullscreen (moved to another monitor, DPI change).
            rect = self.rect()
            self._stage_rect = QRect(rect)
            self.player.setGeometry(rect)
        else:
            self.web.setGeometry(self.rect())
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
        #
        # The white-gap bug wasn't actually a geometry-timing race in our own
        # code: QWebEngineView's Chromium surface lives in a separate process
        # and resizes over IPC, asynchronously from the Qt widget's own
        # geometry change. Even a perfectly-timed mask update can still lose
        # that race and show Chromium's blank/unpainted backing store in the
        # newly-exposed area -- no amount of retiming set_stage_geometry()
        # fixes that, because the mask was never the bottleneck.
        #
        # The actual fix: don't ask the web view to paint anything during
        # fullscreen at all. It only ever draws the sidebar/titlebar, and
        # neither exists in fullscreen -- so hide it outright instead of
        # masking around it, and let mpv's own native surface (which paints
        # itself, no Chromium/IPC involved) cover the whole screen with
        # nothing else in front of it to race against.
        if on and not self.isFullScreen():
            self.showFullScreen()
        elif not on and self.isFullScreen():
            self.showNormal()
        if on:
            self.web.hide()
            screen = self.screen()
            geo = screen.geometry() if screen is not None else self.rect()
            self._stage_rect = QRect(0, 0, geo.width(), geo.height())
            self.player.setGeometry(self._stage_rect)
            self.player.show()
        else:
            self.web.setMask(QRegion())
            self.web.show()
        self.bridge.fullscreenChanged.emit(on)

    # -- library -----------------------------------------------------------
    def pick_folder(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "開啟資料夾")
        if path:
            self.open_folder(Path(path))

    def pick_file(self) -> None:
        exts = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))
        path, _ = QFileDialog.getOpenFileName(
            self, "開啟影片", filter=f"影片檔案 ({exts});;所有檔案 (*)"
        )
        if path:
            self.play(Path(path))

    def pick_url(self) -> None:
        # A native dialog, not an HTML overlay in the web page: the video
        # stage is a real hole punched in the web view (see
        # _apply_stage_mask) so mpv is visible/clickable through it, and an
        # HTML modal centered on the window would render mostly or entirely
        # inside that hole -- invisible, even though its own JS logic works.
        # A native Qt dialog isn't subject to that at all.
        url, ok = QInputDialog.getText(self, "開啟網址", "輸入影片網址：")
        if ok and url.strip():
            self.play_url(url.strip())

    def open_folder(self, folder: Path, select: Path | None = None) -> None:
        self._folder = folder
        self._requested_thumbs.clear()
        self._scan_pool.start(_ScanJob(folder, self._recursive, select, self._scan_signals))

    def _on_folder_scanned(self, folder_str: str, paths: list[str], select_str: str) -> None:
        folder = Path(folder_str)
        if folder != self._folder:
            return  # a newer open_folder() call already superseded this scan
        self._playlist = [Path(p) for p in paths]
        items = [
            {"path": str(p), "name": p.name, "progress": resume.get_progress(str(p))}
            for p in self._playlist
        ]
        self.bridge.folderOpened.emit(folder.name or str(folder), items)
        select = Path(select_str) if select_str else None
        index = self._playlist.index(select) if select in self._playlist else 0
        self.player.load_playlist(self._playlist, index)
        self.player.setFocus(Qt.FocusReason.OtherFocusReason)

    def set_recursive(self, on: bool) -> None:
        self._recursive = on

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
        if video in self._playlist:
            self.player.play_index(self._playlist.index(video))
        self.player.setFocus(Qt.FocusReason.OtherFocusReason)

    def play_url(self, url: str) -> None:
        url = url.strip()
        if url:
            self.player.play_url(url)

    def remove_from_playlist(self, paths: list[str]) -> None:
        remove_set = {Path(p) for p in paths}
        if not remove_set or not self._playlist:
            return
        for index in sorted(
            (i for i, p in enumerate(self._playlist) if p in remove_set), reverse=True
        ):
            self.player.remove_index(index)
        self._playlist = [p for p in self._playlist if p not in remove_set]
        items = [
            {"path": str(p), "name": p.name, "progress": resume.get_progress(str(p))}
            for p in self._playlist
        ]
        folder_name = self._folder.name or str(self._folder) if self._folder else ""
        self.bridge.folderOpened.emit(folder_name, items)

    def toggle_fluid_motion(self) -> None:
        self.player.toggle_fluid_motion()

    def _on_path_changed(self, path: str) -> None:
        self.bridge.nowPlaying.emit(str(Path(path)))

    def _on_progress(self, path: str, pos: float, duration: float) -> None:
        resume.save_progress(path, pos, duration)
        self.bridge.progressUpdated.emit(path, pos, duration)

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
        urls = [QUrl(u) for u in uris if u]
        if not urls:
            return
        if not urls[0].isLocalFile():
            # A dragged web link (e.g. from a browser) rather than a local
            # file -- QUrl.toLocalFile() would silently return "" for this,
            # which as a Path resolves to ".", so this has to be handled
            # before falling into the local-file branch below at all.
            self.play_url(urls[0].toString())
            return
        paths = [Path(u.toLocalFile()) for u in urls]
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


class _MpvFetchWorker(QThread):
    status = Signal(str)
    failed = Signal(str)

    def run(self) -> None:  # noqa: N802
        from ax_player.mpv_fetch import ensure_runtime

        try:
            ensure_runtime(on_progress=self.status.emit)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed
            self.failed.emit(str(exc))


def _bootstrap_mpv_if_needed() -> bool:
    """Packaged-exe first run only: fetches mpv into a per-user folder if
    nothing usable is found anywhere (see paths.bundled_mpv_root). No-ops
    instantly on every subsequent launch, and always in a source checkout
    where run.bat already called setup_mpv.py before Python even started.

    Returns False (caller should abort startup) only if the fetch failed.
    """
    from ax_player.paths import default_mpv_root

    if not getattr(sys, "frozen", False) or (default_mpv_root() / "libmpv-2.dll").is_file():
        return True

    progress = QProgressDialog("正在準備播放引擎（僅限第一次啟動）…", "", 0, 0)
    progress.setWindowTitle("AX Player")
    progress.setWindowModality(Qt.WindowModality.ApplicationModal)
    progress.setCancelButton(None)
    progress.setMinimumDuration(0)
    progress.show()

    worker = _MpvFetchWorker()
    worker.status.connect(progress.setLabelText)
    error: list[str] = []
    worker.failed.connect(error.append)

    loop = QEventLoop()
    worker.finished.connect(loop.quit)
    worker.start()
    loop.exec()
    progress.close()

    if error:
        QMessageBox.critical(
            None,
            "AX Player",
            f"播放引擎下載失敗：\n{error[0]}\n\n請檢查網路連線後重新啟動 AX Player。",
        )
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv if argv is None else argv
    app = QApplication(argv)
    app.setApplicationName("AX Player")
    icon_file = icon_path()
    if icon_file.is_file():
        app.setWindowIcon(QIcon(str(icon_file)))

    if not _bootstrap_mpv_if_needed():
        return 1

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
