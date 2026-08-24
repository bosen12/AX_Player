from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

VIDEO_EXTENSIONS = {
    ".mp4", ".mkv", ".avi", ".mov", ".webm", ".wmv", ".flv", ".ts", ".m4v", ".mpg", ".mpeg",
}


def is_video_file(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTENSIONS


@lru_cache(maxsize=1)
def default_mpv_root() -> Path:
    # Cached: this is re-derived from libmpv_dll()/mpv_exe() on every
    # thumbnail job (one per playlist row, run in a thread pool) and doesn't
    # change during the process's lifetime.
    candidates = [Path(r"C:\mpv"), Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "mpv"]
    for path in candidates:
        if (path / "libmpv-2.dll").is_file():
            return path
    return Path(r"C:\mpv")


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
    return Path(__file__).parent / "resources" / "icon.ico"


def web_dir() -> Path:
    return Path(__file__).parent / "web"
