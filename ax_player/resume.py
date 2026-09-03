"""Per-video playback progress, used only to show a progress bar / watched
badge in the sidebar.

Actual resume-on-reopen is already handled by mpv itself (mpv.conf sets
save-position-on-quit=yes, which uses mpv's own watch-later files) -- this
module doesn't duplicate that. It just gives the UI something to draw.
"""

from __future__ import annotations

import json
import os
import threading

from ax_player.paths import resume_db_path

_lock = threading.Lock()
_cache: dict[str, dict] | None = None

WATCHED_THRESHOLD = 0.95


def _load() -> dict[str, dict]:
    global _cache
    if _cache is not None:
        return _cache
    try:
        _cache = json.loads(resume_db_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _cache = {}
    return _cache


def get_progress(video: str) -> dict | None:
    entry = _load().get(video)
    # Only ever written by save_progress() below, which always writes this
    # shape -- but the file is user-editable JSON on disk, and at least one
    # real install has been found with bare-number entries from some earlier
    # write path. Treating those as "no data" rather than returning them
    # raw matters because callers (the sidebar list build) do entry.get(...)
    # unconditionally: one malformed entry used to raise mid-loop and
    # silently truncate every row after it in the list.
    if not isinstance(entry, dict) or "duration" not in entry:
        return None
    return entry


def save_progress(video: str, pos: float, duration: float) -> None:
    if duration <= 0 or pos < 0:
        return
    with _lock:
        data = _load()
        watched = pos / duration >= WATCHED_THRESHOLD
        # Watched: report 0 progress so a finished episode doesn't sit at
        # "resume from 23:58" in the UI forever.
        entry = {"pos": 0.0 if watched else pos, "duration": duration, "watched": watched}
        # The 5-second poll fires whether or not playback advanced, so a paused
        # player used to rewrite the entire database -- byte for byte identical
        # -- 12 times a minute, indefinitely. Measured at 5000 entries that is
        # a 630 KiB file, i.e. 7.4 MiB/minute of writes for no change at all.
        # (The CPU side is not the argument: one save is 3.79 ms there, well
        # under the bar other performance items were withdrawn against. The
        # write amplification is.)
        if data.get(video) == entry:
            return
        data[video] = entry
        _write(data)


def set_watched(video: str, watched: bool) -> None:
    """Mark a video watched (or not) by hand, from the sidebar's menu.

    Unmarking deletes the entry outright rather than storing watched=False:
    "not watched" and "never opened" should look identical in the list, and a
    zeroed entry would otherwise keep the row's progress bar and duration
    alive for a video the user just said they had not seen.

    Marking without a known duration stores 0.0 for it, which the sidebar
    reads as "no progress bar" while still drawing the check badge -- the
    honest rendering of what is actually known here.
    """
    with _lock:
        data = _load()
        removed: frozenset[str] = frozenset()
        if not watched:
            if data.pop(video, None) is None:
                return
            # Named so _write's merge does not read it back off disk and put
            # it straight back -- which is what it did, silently, until now.
            removed = frozenset({video})
        else:
            previous = data.get(video)
            duration = (
                float(previous.get("duration") or 0.0) if isinstance(previous, dict) else 0.0
            )
            entry = {"pos": 0.0, "duration": duration, "watched": True}
            if previous == entry:
                return
            data[video] = entry
        _write(data, removed)


def _merge_from_disk(
    data: dict[str, dict], removed: frozenset[str] = frozenset()
) -> dict[str, dict]:
    """Fold in entries written by another AX Player since this one loaded.

    `removed` is what this process just deleted on purpose. Without it the
    merge resurrects them: set_watched(video, False) pops the entry and calls
    _write, _write reads the file back -- where the entry still is, because the
    swap has not happened yet -- and setdefault puts it straight back. Measured
    on a fresh database: after 標記為未看 the entry was still on disk, still
    saying watched=True, and so was the in-memory cache, because this function
    mutates the very dict it was handed. The row cleared in the sidebar and came
    back watched on the next launch, which is the only place it was visible.

    A deletion therefore beats another process's entry for the same key, where
    the note below settles for the opposite. That asymmetry is deliberate: the
    deletion is something the user just asked for by name.

    Each process holds the whole database in memory and writes all of it back,
    so without this the last writer replaces the others' entries wholesale.
    Measured with three processes saving 400 videos each: 792 of 1200 writes
    lost. That is not a contrived setup -- opening three files from Explorer is
    three processes (§7 of HANDOFF: there is no single-instance handover), each
    polling every five seconds, so two windows watching two episodes means one
    of them silently records no progress at all.

    setdefault, not update: our own entry has to win for the video this process
    is actually playing. Two processes updating the *same* key would still lose
    one, but they would have to be playing the same file in two windows, where
    there is no correct answer to pick anyway.
    """
    try:
        on_disk = json.loads(resume_db_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return data
    if not isinstance(on_disk, dict):
        return data
    for key, value in on_disk.items():
        if key in removed:
            continue
        data.setdefault(key, value)
    return data


def _write(data: dict[str, dict], removed: frozenset[str] = frozenset()) -> None:
    """Written via a temp file and swapped in with os.replace: this rewrites
    the whole database, and it runs on every 5-second progress poll, so an
    in-place write is a standing chance for a crash or power loss to leave a
    truncated file -- which _load()'s ValueError guard then reads as "no data
    at all", wiping every video's progress and watched badge.

    The temp name carries the pid. It used to be a bare "resume.json.tmp",
    which every concurrent process picked too: one could truncate the file
    another was mid-write to, and then os.replace a half-written database over
    the real one -- the exact failure this atomic write exists to prevent.
    Fluid Motion's save_settings has always done it this way.
    """
    path = resume_db_path()
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(_merge_from_disk(data, removed)), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
