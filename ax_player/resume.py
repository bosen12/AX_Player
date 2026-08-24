"""Per-video playback progress, used only to show a progress bar / watched
badge in the sidebar.

Actual resume-on-reopen is already handled by mpv itself (mpv.conf sets
save-position-on-quit=yes, which uses mpv's own watch-later files) -- this
module doesn't duplicate that. It just gives the UI something to draw.
"""

from __future__ import annotations

import json
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
        data[video] = {"pos": 0.0 if watched else pos, "duration": duration, "watched": watched}
        try:
            resume_db_path().write_text(json.dumps(data), encoding="utf-8")
        except OSError:
            pass
