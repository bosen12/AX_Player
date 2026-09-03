from __future__ import annotations

import os
import subprocess
from pathlib import Path

from ax_player.cache import cache_key, clear_scratch, prune_cache
from ax_player.paths import mpv_exe, thumbnail_cache_dir

THUMB_WIDTH = 320
# Where in the video to grab the sidebar thumbnail from (see generate_thumbnail).
THUMB_SEEK = "10%"


def prune_thumbnail_cache() -> None:
    prune_cache(thumbnail_cache_dir())


def cached_thumbnail_path(video: Path) -> Path:
    return thumbnail_cache_dir() / f"{cache_key(video)}.jpg"


def generate_thumbnail(video: Path) -> Path | None:
    """Grab one frame via mpv itself (no ffmpeg dependency) and cache it."""
    dest = cached_thumbnail_path(video)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest
    # A fraction of the way in, not a fixed three seconds. Three seconds into
    # a video is the studio logo, a black frame, or the first bar of an OP --
    # which is what the sidebar was showing for whole folders at a time. mpv's
    # own --start takes a percentage ("Relative time or percent position", and
    # verified against the bundled mpv.exe), so this costs no duration probe.
    #
    # It also makes the second pass genuinely a fallback. A percentage is
    # inside the file by construction, so the frame-0 retry no longer runs for
    # every clip shorter than the old fixed seek -- only when a percent seek
    # really fails, i.e. mpv could not work out a duration at all.
    for seek in (THUMB_SEEK, "00:00:00"):
        result = _grab_frame(video, seek, dest, width=THUMB_WIDTH)
        if result is not None:
            return result
    return None


def _grab_frame(video: Path, seek: str, dest: Path, *, width: int) -> Path | None:
    exe = mpv_exe()
    if exe is None:
        return None
    dest.parent.mkdir(parents=True, exist_ok=True)
    # Per process, not just per video: dest.stem is the content hash, so two
    # AX Players grabbing the same file (three files opened from Explorer is
    # three processes -- there is no single-instance handover) picked the same
    # scratch dir. The first one's finally-block unlink emptied it under the
    # second, whose glob then found nothing, and the row it belonged to keeps
    # its grey placeholder for the rest of the session because the path is
    # already in _requested_thumbs and is never retried.
    tmp_dir = dest.parent / f".tmp-{dest.stem}-{os.getpid()}"
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
        clear_scratch(tmp_dir)
