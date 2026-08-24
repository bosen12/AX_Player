"""Minimal file-based diagnostic log.

The packaged exe runs with console=False (no window to print to), so
there has been no way to see what actually happens inside it -- only
what happens in ad-hoc source-checkout test scripts, which have kept
working while the real exe reportedly hasn't. This exists to close that
gap: a handful of call sites log to app_data_dir()/debug.log so a real
failure (including ones _mpv_cmd's broad except would otherwise swallow
silently) becomes visible instead of guessed at.
"""

from __future__ import annotations

import traceback
from datetime import datetime

from ax_player.paths import app_data_dir

_log_path = None


def path():
    global _log_path
    if _log_path is None:
        _log_path = app_data_dir() / "debug.log"
    return _log_path


def log(msg: str) -> None:
    try:
        with open(path(), "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='milliseconds')} {msg}\n")
    except OSError:
        pass


def log_exc(context: str) -> None:
    log(f"{context}: {traceback.format_exc()}")
