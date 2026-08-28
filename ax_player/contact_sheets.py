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

import os
import re
import subprocess
import time
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QPainter, QPen

from ax_player.cache import cache_key, prune_cache
from ax_player.paths import contact_sheet_cache_dir, mpv_exe

GRID_COLS = 3
GRID_ROWS = 3
FRAME_COUNT = GRID_COLS * GRID_ROWS
# Ceiling for the single-process grab. The nine frames land in about 0.2s on a
# local file; this is only here so a stalled decode cannot hold a worker.
GRAB_TIMEOUT = 30.0
CELL_WIDTH = 220
GAP = 3
# Skip the very start/end: title cards and credits are rarely representative
# of the video, and a 0% grab risks landing before the first keyframe.
START_FRACTION = 0.04
END_FRACTION = 0.96

_DURATION_RE = re.compile(r"^(\d{1,2}):(\d{2}):(\d{2}(?:\.\d+)?)$", re.MULTILINE)


def prune_contact_sheet_cache() -> None:
    # Sheets from a different grid size can never be read again: the filename
    # carries the frame count, and cached_sheet_path() only ever asks for the
    # current one. The 4x3 grid this shipped with before 358704e left a
    # _12.jpg beside every _9.jpg, which then sat in the cache competing for
    # the size cap until the LRU happened to reach it.
    directory = contact_sheet_cache_dir()
    try:
        for stale in directory.glob("*.jpg"):
            suffix = stale.stem.rsplit("_", 1)[-1]
            if suffix.isdigit() and int(suffix) != FRAME_COUNT:
                try:
                    stale.unlink()
                except OSError:
                    pass
    except OSError:
        pass
    prune_cache(directory)


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


def _settled_frames(
    tmp_dir: Path, previous: dict[Path, int]
) -> tuple[list[Path], dict[Path, int]]:
    """Frames whose size has stopped changing, plus this pass's sizes.

    A non-empty file that is the same size as it was one poll ago is done
    being written; anything else is still in flight.
    """
    sizes: dict[Path, int] = {}
    settled: list[Path] = []
    for frame in sorted(tmp_dir.glob("*.jpg")):
        try:
            size = frame.stat().st_size
        except OSError:
            continue
        sizes[frame] = size
        if size > 0 and previous.get(frame) == size:
            settled.append(frame)
    return settled, sizes


def _grab_evenly_spaced(
    video: Path, start: float, step: float, count: int, tmp_dir: Path
) -> list[Path]:
    """Grab `count` frames `step` apart from one mpv, not one mpv per frame.

    Spawning mpv is what this costs, not decoding it: a single frame grab
    measures 0.48s and nine of them 4.54s, which is the same 0.5s of process
    startup nine times over. --sstep walks the file inside one process, and
    the same nine frames come out in 0.22s.

    mpv does not exit once the frames are written, so this waits for the files
    to appear and then ends it rather than blocking on the process. Returns
    the frames it got, in time order; a short read is the caller's to handle.

    "Appear" is not "finished": a file shows up in the directory the moment it
    is created, so the newest one is usually still being written. Only frames
    whose size held steady across two polls are counted, otherwise the last
    cell of the sheet is a truncated JPEG that loads as a null QImage and gets
    silently dropped -- and the eight-frame sheet is then cached for good.
    """
    exe = mpv_exe()
    if exe is None:
        return []
    tmp_dir.mkdir(parents=True, exist_ok=True)
    proc = None
    try:
        proc = subprocess.Popen(
            [
                str(exe),
                "--no-config",
                "--hwdec=auto-copy",
                "--vo=image",
                "--vo-image-format=jpg",
                "--vo-image-jpeg-quality=82",
                f"--vo-image-outdir={tmp_dir}",
                f"--frames={count}",
                f"--start={start:.2f}",
                f"--sstep={step:.3f}",
                "--hr-seek=yes",
                "--no-audio",
                "--sub=no",
                f"--vf=scale={CELL_WIDTH}:-2",
                "--really-quiet",
                str(video),
            ],
            cwd=str(tmp_dir),
            creationflags=subprocess.CREATE_NO_WINDOW,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + GRAB_TIMEOUT
        sizes: dict[Path, int] = {}
        while time.monotonic() < deadline:
            settled, sizes = _settled_frames(tmp_dir, sizes)
            if len(settled) >= count:
                return settled[:count]
            if proc.poll() is not None:
                # Ended early: whatever it managed to write is all there is.
                # Nothing can still be growing once the writer has exited, so
                # the two-pass settling rule is not needed (and would wrongly
                # drop a frame finished between the last poll and the exit).
                return [
                    frame
                    for frame in sorted(tmp_dir.glob("*.jpg"))
                    if frame.stat().st_size > 0
                ][:count]
            time.sleep(0.02)
        return _settled_frames(tmp_dir, sizes)[0][:count]
    except (subprocess.SubprocessError, OSError):
        return []
    finally:
        if proc is not None and proc.poll() is None:
            try:
                proc.kill()
                proc.wait(timeout=5)
            except (subprocess.SubprocessError, OSError):
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
        # Evenly spaced, so one mpv can walk them with --sstep instead of one
        # process per frame. The timestamps come from the same arithmetic that
        # positions them rather than from the files, which carry none.
        times = [duration * frac for frac in fractions]
        step = (times[-1] - times[0]) / (len(times) - 1) if len(times) > 1 else 0.0
        produced = (
            _grab_evenly_spaced(video, times[0], step, len(times), tmp_dir)
            if step > 0
            else []
        )
        if len(produced) < len(times):
            # Any shortfall, not just an empty result. The single-process grab
            # returns what has settled when it hits GRAB_TIMEOUT, and a sheet
            # is cached under a name that states its frame count and is never
            # revisited -- so accepting eight of nine here cached an eight-cell
            # sheet for good. v1.1.4 closed one route to that (a frame read
            # before mpv had finished writing it); a timeout is the other.
            #
            # The fallback re-grabs every frame in its own process, positioning
            # each seek itself, which costs the ~4.5s that --sstep exists to
            # avoid -- acceptable for a path that should be rare, and it is the
            # honest retry: if it too comes up short, that timestamp genuinely
            # will not decode and the shorter sheet is the real answer rather
            # than a timing accident.
            #
            # Paired with its own timestamp rather than zipped against times
            # positionally: a frame the fallback cannot grab is simply absent
            # from the list, so position i stops meaning times[i] and every
            # later cell would be labelled with the wrong one.
            grabbed = []
            for i, seconds in enumerate(times):
                one = _grab_frame_at(video, seconds, tmp_dir / f"fallback{i:02d}.jpg")
                if one is not None:
                    grabbed.append((one, seconds))
        else:
            # The fast path walks the file forward from times[0] in `step`
            # increments, so its nth frame is times[n] by construction.
            grabbed = list(zip(produced, times))
        for frame_path, seconds in grabbed:
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
        # Written beside the destination and renamed onto it, the same way
        # thumbnails.py already lands its frame. Saving straight onto dest
        # leaves a window where a half-written JPEG is on disk -- and it
        # passes cached_sheet_path()'s "is_file() and st_size > 0" check, so
        # that broken image is then served for every hover from then on,
        # since nothing revisits a sheet once it exists.
        staging = dest.with_name(f".part-{dest.name}")
        try:
            if not sheet.save(str(staging), "JPG", 85):
                return None
            os.replace(staging, dest)
        except OSError:
            return None
        finally:
            # In a finally, not just on the OSError path: QImage.save reports
            # a disk-full or permission failure by *returning False*, not by
            # raising, and it can leave a partial file behind when it does.
            # That file then survives every cleanup there is -- the scratch
            # sweep only looks at directories, the stale-grid sweep keeps
            # anything ending in the current frame count, and the LRU only
            # runs once the cache is over its cap -- so it sits there for
            # good. Measured: 353 bytes left behind, present after all three.
            #
            # A successful os.replace has already moved it, so this is a no-op
            # on the path that worked.
            try:
                staging.unlink(missing_ok=True)
            except OSError:
                pass
        return dest
    finally:
        try:
            for leftover in tmp_dir.glob("*"):
                leftover.unlink(missing_ok=True)
            tmp_dir.rmdir()
        except OSError:
            pass
