from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".ts", ".m4v", ".mpg", ".mpeg",
}


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


def _frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


@lru_cache(maxsize=1)
def _package_dir() -> Path:
    """ax_player/ itself -- where web/ and resources/ live. PyInstaller's
    `datas` keeps this relative layout intact under the extraction root."""
    if _frozen():
        return Path(sys._MEIPASS) / "ax_player"  # type: ignore[attr-defined]
    return Path(__file__).parent


@lru_cache(maxsize=1)
def _project_root() -> Path:
    """Project root -- where mpv-runtime/ sits alongside ax_player/ in a
    source checkout, and the same relative layout under PyInstaller's
    extraction root for the small bundled mpv-runtime config/scripts."""
    if _frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).parent.parent


@lru_cache(maxsize=1)
def bundled_mpv_root() -> Path:
    """The slim mpv runtime shipped alongside AX Player itself.

    In a source checkout this is mpv-runtime/ next to run.bat: the
    scripts/fonts/configs are checked into the repo directly (small,
    stable text/lua files), and mpv.exe/libmpv-2.dll are fetched into it
    by setup_mpv.py.

    In the packaged exe, mpv.exe/libmpv-2.dll are deliberately NOT
    embedded (large, change often) -- this instead points at a writable
    per-user folder that AXPlayerWindow's frozen-mode bootstrap populates
    on first launch (seeding the small bundled config/scripts, then
    fetching the two binaries the same way setup_mpv.py does).
    """
    if _frozen():
        return app_data_dir() / "mpv-runtime"
    return _project_root() / "mpv-runtime"


@lru_cache(maxsize=1)
def default_mpv_root() -> Path:
    # Cached: this is re-derived from libmpv_dll()/mpv_exe() on every
    # thumbnail job (one per playlist row, run in a thread pool) and doesn't
    # change during the process's lifetime.
    #
    # bundled_mpv_root() is checked first so a fresh install "just works"
    # off setup_mpv.py alone. On a machine that also has a full personal
    # mpv setup at C:\mpv (uosc, thumbfast, Anime4K shaders, Fluid Motion
    # IPC scripts already configured there), that one is still picked up
    # automatically as a fallback -- but only once bundled_mpv_root() has
    # no libmpv-2.dll of its own, i.e. setup_mpv.py was never run there.
    candidates = [
        bundled_mpv_root(),
        Path(r"C:\mpv"),
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "mpv",
    ]
    for path in candidates:
        if (path / "libmpv-2.dll").is_file():
            return path
    return bundled_mpv_root()


def libmpv_dll() -> Path | None:
    root = default_mpv_root()
    for name in ("libmpv-2.dll", "libmpv.dll", "mpv-2.dll", "mpv-1.dll"):
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def mpv_exe() -> Path | None:
    candidate = default_mpv_root() / "mpv.exe"
    return candidate if candidate.is_file() else None


def ytdlp_exe() -> Path | None:
    candidate = default_mpv_root() / "yt-dlp.exe"
    return candidate if candidate.is_file() else None


def app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    path = base / "AXPlayer"
    path.mkdir(parents=True, exist_ok=True)
    return path


def thumbnail_cache_dir() -> Path:
    path = app_data_dir() / "thumbnails"
    path.mkdir(parents=True, exist_ok=True)
    return path


def resume_db_path() -> Path:
    return app_data_dir() / "resume.json"


@lru_cache(maxsize=1)
def icon_path() -> Path:
    return _package_dir() / "resources" / "icon.ico"
