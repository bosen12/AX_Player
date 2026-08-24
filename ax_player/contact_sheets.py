"""Contact sheets: an NxM grid of frames grabbed evenly across a video.

Same idea as thumbnails.py's single-frame grab (mpv itself does the
decoding, no ffmpeg dependency, one frame at a time to --vo=image), just
repeated at evenly spaced timestamps and composed into one image. Cached
under its own directory with the same content-keyed, size-capped,
least-recently-accessed eviction policy as the sidebar thumbnail cache
(see cache.py) -- this is meant for a hover popup, so once a video has been
looked at once, showing it again must be instant, not a repeat of a few
seconds of frame-grabbing.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPainter, QPen

from ax_player.cache import cache_key, prune_cache
from ax_player.paths import contact_sheet_cache_dir, mpv_exe

GRID_COLS = 3
GRID_ROWS = 3
FRAME_COUNT = GRID_COLS * GRID_ROWS
CELL_WIDTH = 220
GAP = 3
# Skip the very start/end: title cards and credits are rarely representative
# of the video, and a 0% grab risks landing before the first keyframe.
START_FRACTION = 0.04
END_FRACTION = 0.96

_DURATION_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$", re.MULTILINE)


def prune_contact_sheet_cache() -> None:
    prune_cache(contact_sheet_cache_dir())


def cached_sheet_path(video: Path, frame_count: int = FRAME_COUNT) -> Path:
    return contact_sheet_cache_dir() / f"{cache_key(video)}_{frame_count}.jpg"


def probe_duration(video: Path) -> float | None:
    """Seconds, via mpv's own --term-playing-msg -- no ffprobe dependency.

    --quiet (not --really-quiet) is load-bearing: really-quiet also
    suppresses term-playing-msg, which is the only thing this needs from
    mpv's stdout.
    """
    exe = mpv_exe()
    if exe is None:
        return None
    try:
        result = subprocess.run(
            [
                str(exe),
                "--no-config",
                "--vo=null",
                "--ao=null",
                "--frames=1",
                "--quiet",
                r"--term-playing-msg=${duration}",
                str(video),
            ],
            capture_output=True,
            # Explicit UTF-8 rather than text=True's locale-dependent decode
            # -- mpv's own stdout (other --quiet chatter, non-ASCII in the
            # video's path) is UTF-8, but Python's default text-mode decode
            # follows the system ANSI codepage (e.g. cp950 on a zh-TW
            # machine), which raises UnicodeDecodeError on the first
            # multi-byte character and silently kills every probe.
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    match = _DURATION_RE.search(result.stdout or "")
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _grab_frame_at(video: Path, seconds: float, dest: Path) -> Path | None:
    exe = mpv_exe()
    if exe is None:
        return None
    tmp_dir = dest.parent / f".tmp-{dest.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    try:
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
                f"--start={seconds:.2f}",
                "--hr-seek=yes",
                "--no-audio",
                "--sub=no",
                f"--vf=scale={CELL_WIDTH}:-2",
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


def _format_timestamp(seconds: float) -> str:
    total = int(seconds)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def generate_contact_sheet(video: Path, frame_count: int = FRAME_COUNT) -> Path | None:
    """Grab frame_count frames and compose them into one cached grid image.

    Runs entirely on a worker thread (called from _ContactSheetJob). QImage
    is used rather than QPixmap for exactly that reason -- QPixmap is only
    safe to touch on the GUI thread, QImage has no such restriction.
    """
    dest = cached_sheet_path(video, frame_count)
    if dest.is_file() and dest.stat().st_size > 0:
        return dest

    duration = probe_duration(video)
    if not duration or duration <= 0:
        return None

    if frame_count <= 1:
        fractions = [0.5]
    else:
        span = END_FRACTION - START_FRACTION
        fractions = [START_FRACTION + span * i / (frame_count - 1) for i in range(frame_count)]

    tmp_dir = dest.parent / f".compose-{dest.stem}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    frames: list[tuple[QImage, str]] = []
    try:
        for i, frac in enumerate(fractions):
            seconds = duration * frac
            frame_path = _grab_frame_at(video, seconds, tmp_dir / f"{i:02d}.jpg")
            if frame_path is None:
                continue
            image = QImage(str(frame_path))
            if not image.isNull():
                frames.append((image, _format_timestamp(seconds)))

        if not frames:
            return None

        cell_h = frames[0][0].height()
        cols = min(GRID_COLS, len(frames))
        rows = (len(frames) + cols - 1) // cols
        sheet_w = cols * CELL_WIDTH + (cols + 1) * GAP
        sheet_h = rows * cell_h + (rows + 1) * GAP

        sheet = QImage(sheet_w, sheet_h, QImage.Format.Format_RGB32)
        sheet.fill(QColor("#0c0a08"))
        painter = QPainter(sheet)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        font = painter.font()
        font.setPixelSize(11)
        painter.setFont(font)
        for i, (frame, label) in enumerate(frames):
            col, row = i % cols, i // cols
            x = GAP + col * (CELL_WIDTH + GAP)
            y = GAP + row * (cell_h + GAP)
            # Frames can vary slightly in height (odd source aspect ratios
            # rounding differently) -- draw at native width, top-aligned, and
            # let the sheet's per-row height already account for the first
            # frame's height rather than assuming every frame matches it.
            painter.drawImage(x, y, frame)
            painter.fillRect(x, y + frame.height() - 16, frame.width(), 16, QColor(0, 0, 0, 150))
            painter.setPen(QPen(QColor("#ece4d9")))
            painter.drawText(x + 4, y + frame.height() - 5, label)
        painter.end()

        dest.parent.mkdir(parents=True, exist_ok=True)
        if not sheet.save(str(dest), "JPG", 85):
            return None
        return dest
    finally:
        try:
            for leftover in tmp_dir.glob("*"):
                leftover.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass
