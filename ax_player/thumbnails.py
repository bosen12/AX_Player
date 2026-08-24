from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from ax_player.paths import mpv_exe, thumbnail_cache_dir

THUMB_WIDTH = 320


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
