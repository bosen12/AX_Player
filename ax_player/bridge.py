"""QWebChannel bridge between the HTML shell and the Python side.

Deliberately small: playback itself (play/pause/seek/volume/fullscreen/
next/prev/hover-preview) is owned by mpv's own uosc + thumbfast scripts,
rendered directly onto the video surface. This bridge only carries window
chrome and the folder/thumbnail library -- the things uosc doesn't do.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot


def to_url(path: Path | str) -> str:
    return QUrl.fromLocalFile(str(path)).toString()


class Bridge(QObject):
    # Python -> JS
    folderOpened = Signal(str, list)      # folder name, [{path, name, progress}]
    thumbnailReady = Signal(str, str)     # video path, image url
    nowPlaying = Signal(str)              # video path
    titleChanged = Signal(str)
    maximizedChanged = Signal(bool)
    fullscreenChanged = Signal(bool)
    progressUpdated = Signal(str, float, float)  # video path, pos, duration
    fluidActiveChanged = Signal(bool)

    def __init__(self, controller):
        super().__init__()
        self._c = controller

    # -- window chrome -------------------------------------------------
    @Slot()
    def minimizeWindow(self) -> None:  # noqa: N802
        self._c.minimize_window()

    @Slot()
    def toggleMaximize(self) -> None:  # noqa: N802
        self._c.toggle_maximize()

    @Slot()
    def closeWindow(self) -> None:  # noqa: N802
        self._c.close_window()

    @Slot()
    def startWindowDrag(self) -> None:  # noqa: N802
        self._c.start_window_drag()

    @Slot(int, int, int, int)
    def stageGeometryChanged(self, x: int, y: int, w: int, h: int) -> None:  # noqa: N802
        self._c.set_stage_geometry(x, y, w, h)

    # -- library --------------------------------------------------------
    @Slot()
    def openFolder(self) -> None:  # noqa: N802
        self._c.pick_folder()

    @Slot()
    def openFile(self) -> None:  # noqa: N802
        self._c.pick_file()

    @Slot(str)
    def play(self, path: str) -> None:
        self._c.play(Path(path))

    @Slot(str)
    def requestThumbnail(self, path: str) -> None:  # noqa: N802
        self._c.request_thumbnail(Path(path))

    @Slot(list)
    def openDropped(self, uris: list) -> None:  # noqa: N802
        # The web view consumes drag events before the Qt widget sees them,
        # so drops are handled in the page and the URIs handed back here.
        self._c.open_dropped([str(u) for u in uris])

    @Slot(str)
    def openUrl(self, url: str) -> None:  # noqa: N802
        self._c.play_url(url)

    @Slot(bool)
    def setRecursive(self, on: bool) -> None:  # noqa: N802
        self._c.set_recursive(bool(on))

    @Slot(list)
    def removeFromPlaylist(self, paths: list) -> None:  # noqa: N802
        self._c.remove_from_playlist([str(p) for p in paths])

    @Slot()
    def toggleFluidMotion(self) -> None:  # noqa: N802
        self._c.toggle_fluid_motion()
