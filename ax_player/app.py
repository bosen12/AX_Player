from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import (
    QEventLoop,
    QObject,
    QRunnable,
    QThread,
    QThreadPool,
    QTimer,
    QUrl,
    Qt,
    Signal,
    Slot,
)
from PySide6.QtGui import QColor, QIcon, QPalette, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QMessageBox,
    QProgressDialog,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ax_player import contact_sheets, debug_log, diagnostics, resume, settings, ui
from ax_player.paths import VIDEO_EXTENSIONS, icon_path, is_video_file
from ax_player.player_widget import PlayerWidget
from ax_player.thumbnails import generate_thumbnail, prune_thumbnail_cache

RESIZE_MARGIN = 6


class _JobSignals(QObject):
    thumb_done = Signal(str, str)  # video path, thumbnail image path ("" on failure)


class _ThumbJob(QRunnable):
    def __init__(self, video: Path, signals: _JobSignals):
        super().__init__()
        self._video = video
        self._signals = signals

    @Slot()
    def run(self) -> None:
        path = generate_thumbnail(self._video)
        self._signals.thumb_done.emit(str(self._video), str(path) if path else "")


class _PruneCacheJob(QRunnable):
    @Slot()
    def run(self) -> None:
        prune_thumbnail_cache()
        contact_sheets.prune_contact_sheet_cache()


class _SheetSignals(QObject):
    done = Signal(str, str)  # video path, sheet image path ("" on failure)


class _SheetJob(QRunnable):
    """Grabs FRAME_COUNT frames and composes them -- several seconds of mpv
    subprocess work, so this shares _thumb_pool's cap rather than running
    unbounded: it is exactly the same kind of GPU-decode-subprocess load as
    a thumbnail grab, just repeated, and the concurrency limit exists
    because too many of these at once is what produces "thumbfast: cannot
    create mpv subprocess" (too many simultaneous GPU decode sessions).
    """

    def __init__(self, video: Path, signals: _SheetSignals):
        super().__init__()
        self._video = video
        self._signals = signals

    @Slot()
    def run(self) -> None:
        path = contact_sheets.generate_contact_sheet(self._video)
        self._signals.done.emit(str(self._video), str(path) if path else "")


def _sort_playlist(paths: list[Path], mode: str) -> list[Path]:
    if mode == settings.SORT_NAME:
        return sorted(paths, key=lambda p: p.name.lower())

    def stat_key(path: Path) -> float:
        try:
            st = path.stat()
        except OSError:
            return 0.0
        return st.st_mtime if mode == settings.SORT_DATE else float(st.st_size)

    # Negated so date and size both read newest/largest first; name breaks ties
    # so the order is stable across rescans of files sharing a timestamp.
    return sorted(paths, key=lambda p: (-stat_key(p), p.name.lower()))


class _ScanSignals(QObject):
    # folder path, [str video path], select path ("" for none), reload player
    done = Signal(str, list, str, bool)


class _ScanJob(QRunnable):
    """Directory scan + sort runs here instead of the UI thread -- a folder
    with thousands of files (or a recursive scan) would otherwise freeze
    dragging/clicking for as long as the scan takes.
    """

    def __init__(
        self,
        folder: Path,
        recursive: bool,
        select: Path | None,
        signals: _ScanSignals,
        sort_mode: str,
        reload_player: bool,
    ):
        super().__init__()
        self._folder = folder
        self._recursive = recursive
        self._select = select
        self._signals = signals
        self._sort_mode = sort_mode
        self._reload_player = reload_player

    @Slot()
    def run(self) -> None:
        try:
            entries = self._folder.rglob("*") if self._recursive else self._folder.iterdir()
            # Sorting by date/size stats every file, so it belongs here on the
            # worker thread with the scan, not on the UI thread afterwards.
            playlist = _sort_playlist(
                [p for p in entries if p.is_file() and is_video_file(p)], self._sort_mode
            )
        except OSError:
            playlist = []
        self._signals.done.emit(
            str(self._folder),
            [str(p) for p in playlist],
            str(self._select) if self._select else "",
            self._reload_player,
        )


class AXPlayerWindow(QWidget):
    """Frameless shell: native Qt chrome + library sidebar (see ui.py), with
    mpv -- running the user's own uosc/thumbfast scripts -- owning everything
    about actually playing video: controls, seek bar, hover previews, playlist
    advance, resume-on-reopen. This app supplies the window and the browsable
    folder view; it does not reimplement a player mpv already has tuned.

    The sidebar and mpv are plain siblings in a layout. There is no overlay,
    no mask, and no cross-process compositor in front of the video, which is
    what the previous QWebEngineView-based shell required.
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("AX Player")
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setMinimumSize(860, 520)
        self.setMouseTracking(True)
        self.resize(1320, 780)
        # No-op on first run, when nothing has been saved yet.
        self.restoreGeometry(settings.geometry())
        icon_file = icon_path()
        if icon_file.is_file():
            self.setWindowIcon(QIcon(str(icon_file)))

        # Palette rather than a stylesheet: a stylesheet set on the window
        # propagates to every descendant, PlayerWidget included, and would
        # paint over the surface mpv renders into.
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(ui.PAPER))
        self.setPalette(palette)

        self._folder: Path | None = None
        self._playlist: list[Path] = []
        self._current: Path | None = None
        self._recursive = settings.recursive()
        self._sort_mode = settings.sort_mode()
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

        self.titlebar = ui.TitleBar(self)
        self.titlebar.minimize_clicked.connect(self.showMinimized)
        self.titlebar.maximize_clicked.connect(self.toggle_maximize)
        self.titlebar.close_clicked.connect(self.close)
        self.titlebar.fluid_clicked.connect(self.toggle_fluid_motion)
        self.titlebar.stats_clicked.connect(self.toggle_diagnostics)
        self.titlebar.drag_started.connect(self.start_window_drag)

        # mpv's own numbers are free to read, so they refresh every second.
        # nvidia-smi costs ~160ms, so it runs in the pool and only while the
        # panel is actually visible.
        self._gpu_signals = diagnostics.GpuSignals()
        self._gpu_signals.ready.connect(self._on_gpu_sample)
        self._gpu_sample: dict = {}
        self._gpu_pending = False
        self._diag_timer = QTimer(self)
        self._diag_timer.setInterval(1000)
        self._diag_timer.timeout.connect(self._refresh_diagnostics)

        self.sidebar = ui.Sidebar(self)
        self.sidebar.open_folder_clicked.connect(self.pick_folder)
        self.sidebar.open_file_clicked.connect(self.pick_file)
        self.sidebar.open_url_clicked.connect(self.pick_url)
        self.sidebar.recursive_changed.connect(self.set_recursive)
        self.sidebar.sort_changed.connect(self.set_sort_mode)
        self.sidebar.restore_state(
            recursive=self._recursive,
            sort_mode=self._sort_mode,
            unwatched_only=settings.unwatched_only(),
        )
        self.sidebar.play_requested.connect(lambda p: self.play(Path(p)))
        self.sidebar.remove_requested.connect(self.remove_from_playlist)
        self.sidebar.thumb_requested.connect(lambda p: self.request_thumbnail(Path(p)))
        self.sidebar.sheet_requested.connect(self.request_contact_sheet)
        self._sheet_signals = _SheetSignals()
        self._sheet_signals.done.connect(self._on_sheet_done)

        self.player = PlayerWidget(self)
        self.player.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.player.setMinimumSize(320, 180)
        self.player.title_changed.connect(self.titlebar.set_title)
        self.player.path_changed.connect(self._on_path_changed)
        self.player.fullscreen_changed.connect(self._on_mpv_fullscreen)
        self.player.files_dropped.connect(self.open_dropped)
        self.player.progress_changed.connect(self._on_progress)
        self.player.fluid_active_changed.connect(self.titlebar.set_fluid_active)

        root = QVBoxLayout(self)
        root.setContentsMargins(RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN, RESIZE_MARGIN)
        root.setSpacing(0)
        root.addWidget(self.titlebar)
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)
        body.addWidget(self.sidebar)
        body.addWidget(self.player, 1)
        root.addLayout(body, 1)

        self.setAcceptDrops(True)

    # -- frameless chrome -------------------------------------------------
    def toggle_maximize(self) -> None:
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def start_window_drag(self) -> None:
        handle = self.windowHandle()
        if handle is not None:
            handle.startSystemMove()

    def changeEvent(self, event) -> None:  # noqa: N802
        # The window keeps a RESIZE_MARGIN border of its own around the
        # content purely so all four edges belong to the window itself and
        # can start a native resize. Maximized/fullscreen can't be resized
        # by dragging anyway, and the border would just be a dead frame.
        layout = self.layout()
        if layout is not None:
            margin = 0 if (self.isMaximized() or self.isFullScreen()) else RESIZE_MARGIN
            layout.setContentsMargins(margin, margin, margin, margin)
        super().changeEvent(event)

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

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (self.isMaximized() or self.isFullScreen()):
            edges = self._edges_at(event.position().toPoint())
            horizontal = edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge)
            vertical = edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge)
            if horizontal and vertical:
                diagonal = bool(edges & Qt.Edge.LeftEdge) == bool(edges & Qt.Edge.TopEdge)
                shape = Qt.CursorShape.SizeFDiagCursor if diagonal else Qt.CursorShape.SizeBDiagCursor
            elif horizontal:
                shape = Qt.CursorShape.SizeHorCursor
            elif vertical:
                shape = Qt.CursorShape.SizeVerCursor
            else:
                shape = Qt.CursorShape.ArrowCursor
            self.setCursor(shape)
        super().mouseMoveEvent(event)

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
        # actually fullscreens the Qt window and hides the chrome. With the
        # sidebar/titlebar simply hidden, the layout gives mpv the whole
        # window, and there is no second surface left to race against (which
        # is what produced the white gap back when a Chromium view had to
        # resize over IPC to get out of the way).
        if on and not self.isFullScreen():
            self.showFullScreen()
        elif not on and self.isFullScreen():
            self.showNormal()
        self.titlebar.setVisible(not on)
        self.sidebar.setVisible(not on)

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
        url, ok = QInputDialog.getText(self, "開啟網址", "輸入影片網址：")
        debug_log.log(f"pick_url: ok={ok} raw={url!r}")
        if ok and url.strip():
            self.play_url(url.strip())

    def open_folder(
        self, folder: Path, select: Path | None = None, *, reload_player: bool = True
    ) -> None:
        self._folder = folder
        self._requested_thumbs.clear()
        settings.set_last_folder(str(folder))
        self._scan_pool.start(
            _ScanJob(
                folder,
                self._recursive,
                select,
                self._scan_signals,
                self._sort_mode,
                reload_player,
            )
        )

    def _on_folder_scanned(
        self, folder_str: str, paths: list[str], select_str: str, reload_player: bool
    ) -> None:
        folder = Path(folder_str)
        if folder != self._folder:
            return  # a newer open_folder() call already superseded this scan
        self._playlist = [Path(p) for p in paths]
        self.sidebar.set_items(folder.name or str(folder), self._playlist_items())
        if not reload_player:
            # A re-sort while something is playing: mpv's only way to take a
            # new playlist is "loadlist ... replace", which restarts playback
            # from the top. Reordering the sidebar is not worth interrupting
            # the video for, so mpv keeps its order until the folder is
            # reopened.
            return
        select = Path(select_str) if select_str else None
        index = self._playlist.index(select) if select in self._playlist else 0
        self.player.load_playlist(self._playlist, index)
        self.player.setFocus(Qt.FocusReason.OtherFocusReason)

    def _playlist_items(self) -> list[dict]:
        return [
            {"path": str(p), "name": p.name, "progress": resume.get_progress(str(p))}
            for p in self._playlist
        ]

    def set_recursive(self, on: bool) -> None:
        self._recursive = on
        settings.set_recursive(on)

    def set_sort_mode(self, mode: str) -> None:
        if mode == self._sort_mode:
            return
        self._sort_mode = mode
        settings.set_sort_mode(mode)
        if self._folder is not None:
            # Re-sorting must not restart whatever is playing (see
            # _on_folder_scanned), so the player's playlist is left alone
            # while a file is loaded.
            self.open_folder(
                self._folder, select=self._current, reload_player=self._current is None
            )

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
        debug_log.log(f"AXPlayerWindow.play_url: url={url!r}")
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
        folder_name = (self._folder.name or str(self._folder)) if self._folder else ""
        self.sidebar.set_items(folder_name, self._playlist_items())

    def toggle_fluid_motion(self) -> None:
        self.player.toggle_fluid_motion()

    def toggle_diagnostics(self) -> None:
        panel = self.sidebar.diagnostics
        showing = not panel.isVisible()
        panel.setVisible(showing)
        self.titlebar.set_stats_active(showing)
        if showing:
            self._refresh_diagnostics()
            self._diag_timer.start()
        else:
            self._diag_timer.stop()

    def _refresh_diagnostics(self) -> None:
        self.sidebar.diagnostics.update_data(self.player.diagnostics(), self._gpu_sample)
        # One nvidia-smi in flight at a time: at ~160ms a piece they would
        # otherwise pile up behind a stalled call.
        if not self._gpu_pending:
            self._gpu_pending = True
            self._thumb_pool.start(diagnostics.GpuQueryJob(self._gpu_signals))

    def _on_gpu_sample(self, sample: dict) -> None:
        self._gpu_pending = False
        self._gpu_sample = sample

    def _on_path_changed(self, path: str) -> None:
        self._current = Path(path)
        self.sidebar.set_playing(str(self._current))

    def _on_progress(self, path: str, pos: float, duration: float) -> None:
        resume.save_progress(path, pos, duration)
        self.sidebar.set_progress(path, pos, duration)

    def _on_thumb_done(self, path: str, image_path: str) -> None:
        if image_path:
            self.sidebar.set_thumbnail(path, ui.thumbnail_pixmap(image_path))

    def request_contact_sheet(self, path: str) -> None:
        video = Path(path)
        cached = contact_sheets.cached_sheet_path(video)
        if cached.is_file() and cached.stat().st_size > 0:
            # Already on disk (a repeat hover, or generated in an earlier
            # session): load and hand it back directly rather than paying a
            # thread hop for a case that should feel instant.
            self.sidebar.show_contact_sheet(path, ui.thumbnail_pixmap(cached))
            return
        self._thumb_pool.start(_SheetJob(video, self._sheet_signals))

    def _on_sheet_done(self, path: str, image_path: str) -> None:
        pixmap = ui.thumbnail_pixmap(image_path) if image_path else QPixmap()
        self.sidebar.show_contact_sheet(path, pixmap)

    # -- drag & drop ---------------------------------------------------------
    # A real dragged hyperlink sets text/uri-list (hasUrls()), but dragged
    # plain URL text usually only sets text/plain, which hasUrls() ignores --
    # fall back to it, one URL per line. Children that don't accept drops
    # (the sidebar and its list) let the drop propagate up to here.
    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if event.mimeData().hasUrls() or event.mimeData().hasText():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls():
            uris = [u.toString() for u in mime.urls()]
        elif mime.hasText():
            uris = [
                line.strip()
                for line in mime.text().splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
        else:
            uris = []
        if uris:
            self.open_dropped(uris)
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
        # Saved before hiding, while the window still reports a real geometry.
        settings.set_geometry(self.saveGeometry())
        settings.set_unwatched_only(self.sidebar.unwatched_only())
        settings.flush()
        # Tearing mpv down takes ~0.5s here (releasing the GPU context and
        # writing mpv's watch-later position), and Qt only hides the window
        # *after* closeEvent returns -- so the window sat on screen, frozen,
        # for that entire time. Hide it first and force the repaint through,
        # so the teardown happens behind a window that is already gone.
        self.hide()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
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
    # A windowed (console=False) build has nowhere for an uncaught exception
    # to go -- Qt just prints to a stderr nobody can see and the app either
    # limps on or vanishes. Route it to the same debug.log everything else
    # uses.
    def _log_uncaught(exc_type, exc_value, exc_tb):
        debug_log.log(
            "UNCAUGHT: " + "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_uncaught

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
    else:
        # Reopen whatever library was last in use, so a normal launch lands
        # on the file list rather than an empty sidebar. Skipped when a file
        # or folder was passed in -- that is a more specific request.
        last = settings.last_folder()
        if last and Path(last).is_dir():
            window.open_folder(Path(last))

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
