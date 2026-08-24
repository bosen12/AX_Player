from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from ax_player.paths import mpv_exe, thumbnail_cache_dir

THUMB_WIDTH = 320
MAX_CACHE_BYTES = 500 * 1024 * 1024  # 500 MiB


def prune_thumbnail_cache(max_bytes: int = MAX_CACHE_BYTES) -> None:
    """Evict least-recently-accessed thumbnails once the cache exceeds max_bytes.

    Nothing prunes this cache otherwise, so a long-lived install would
    otherwise grow it forever. Cheap to call at startup: a plain os.scandir
    pass, no hashing.
    """
    cache_dir = thumbnail_cache_dir()
    entries = []
    total = 0
    try:
        with os.scandir(cache_dir) as it:
            for entry in it:
                if not entry.is_file():
                    continue
                stat = entry.stat()
                entries.append((stat.st_atime, stat.st_size, entry.path))
                total += stat.st_size
    except OSError:
        return
    if total <= max_bytes:
        return
    entries.sort(key=lambda e: e[0])  # oldest access first
    for _atime, size, path in entries:
        if total <= max_bytes:
            break
        try:
            os.remove(path)
            total -= size
        except OSError:
            pass


def _cache_key(video: Path) -> str:
    try:
        stat = video.stat()
        raw = f"{video}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        raw = str(video)
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


def cached_thumbnail_path(video: Path) -> Path:
    return thumbnail_cache_dir() / f"{_cache_key(video)}.jpg"


def generate_thumbnail(video: Path) -> Path | None:
    """Grab one frame via mpv itself (no ffmpeg dependency) and cache it."""
    dest = cached_thumbnail_path(video)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    # Very short clips: --start=3s may be past EOF, so fall back to frame 0.
    for seek in ("00:00:03", "00:00:00"):
        result = _grab_frame(video, seek, dest, width=THUMB_WIDTH)
        if result is not None:
            return result
    return None


def _grab_frame(video: Path, seek: str, dest: Path, *, width: int) -> Path | None:
    exe = mpv_exe()
    if exe is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp_dir = dest.parent / f".tmp-{dest.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
        # --vo=image writes numbered frames to --vo-image-outdir on its own;
        # it must NOT be combined with -o/--o (that's mpv's separate encode
        # mode, and the two fight over the same "image" VO and produce
        # nothing -- "Error opening/initializing the selected video_out").
        subprocess.run(
            [
                str(exe),
                "--no-config",
                "--hwdec=auto-copy",
                "--vo=image",
                "--vo-image-format=jpg",
                "--vo-image-jpeg-quality=82",
                f"--vo-image-outdir={tmp_dir}",
                "--frames=1",
                f"--start={seek}",
                "--hr-seek=yes",
                "--no-audio",
                "--sub=no",
                f"--vf=scale={width}:-2",
                "--really-quiet",
                str(video),
            ],
            cwd=str(tmp_dir),
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        produced = next(tmp_dir.glob("*.jpg"), None)
        if produced is None:
            return None
        produced.replace(dest)
        return dest
    except (subprocess.SubprocessError, OSError):
        return None
    finally:
        try:
            for leftover in tmp_dir.glob("*"):
                leftover.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass
