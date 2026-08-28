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

import os
import traceback
from datetime import datetime

from ax_player.paths import app_data_dir

_log_path = None


def path():
    global _log_path
    if _log_path is None:
        _log_path = app_data_dir() / "debug.log"
    return _log_path


# Rotate at this size, keeping one previous generation.
#
# This file only grows: mpv's own warn/error stream feeds it, and one noisy
# script can add thousands of lines a session (thumbfast's spawn failures put
# 1275 lines in here before their cause was found). Left unbounded it defeats
# its own purpose -- it is the only diagnostic channel a console=False build
# has, and nobody reads a 50MB file to find the line that mattered.
#
# One generation, not many: this is a live diagnostic, not an archive.
MAX_BYTES = 1024 * 1024


def _rotate_if_needed(target) -> None:
    try:
        if target.stat().st_size < MAX_BYTES:
            return
    except OSError:
        return  # not there yet, or unreadable -- either way nothing to rotate
    try:
        os.replace(target, target.with_name(target.name + ".1"))
    except OSError:
        pass


def log(msg: str) -> None:
    try:
        target = path()
        _rotate_if_needed(target)
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='milliseconds')} {msg}\n")
    except OSError:
        pass


def log_exc(context: str) -> None:
    log(f"{context}: {traceback.format_exc()}")
