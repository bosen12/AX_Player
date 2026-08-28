"""Shared disk-cache housekeeping.

Both generated-image caches (sidebar thumbnails and contact sheets) are
unbounded by nature -- nothing removes an entry when a video is deleted or
moved, so a long-lived install would grow them forever. They use the same
policy: a cap, and least-recently-*accessed* entries evicted first, so the
files you actually keep opening survive.
"""

from __future__ import annotations

import hashlib
import os
import time
from pathlib import Path

MAX_CACHE_BYTES = 500 * 1024 * 1024  # 500 MiB, per cache


def cache_key(video: Path) -> str:
    """Identity of a file's *content*, not just its path.

    Size and mtime are in the key so that replacing a video with a different
    cut under the same name produces a new key rather than serving the old
    image forever.
    """
    try:
        stat = video.stat()
        raw = f"{video}|{stat.st_size}|{stat.st_mtime_ns}"
    except OSError:
        raw = str(video)
    return hashlib.sha1(raw.encode("utf-8", errors="replace")).hexdigest()


# A scratch directory older than this is certainly abandoned. The frame
# grabbers clean theirs up in a finally block, but a process killed mid-grab
# cannot, and nothing has ever looked at what they leave -- eight of them,
# holding 48 orphaned frames, were sitting in the thumbnail cache from a build
# that named them differently. They are also invisible to the size cap below,
# which only sums files at the top level, so they were never even evicted.
#
# The only directories that ever exist under a cache dir are these, and a live
# one is at most GRAB_TIMEOUT (30s) old. An hour is a wide margin against
# deleting work a second process is still doing.
SCRATCH_MAX_AGE = 3600.0


def _drop_stale_scratch(entry: os.DirEntry) -> None:
    try:
        if time.time() - entry.stat().st_mtime < SCRATCH_MAX_AGE:
            return
    except OSError:
        return
    for root, dirs, files in os.walk(entry.path, topdown=False):
        for name in files:
            try:
                os.remove(os.path.join(root, name))
            except OSError:
                pass
        for name in dirs:
            try:
                os.rmdir(os.path.join(root, name))
            except OSError:
                pass
    try:
        os.rmdir(entry.path)
    except OSError:
        pass


def prune_cache(cache_dir: Path, max_bytes: int = MAX_CACHE_BYTES) -> None:
    """Evict least-recently-accessed files once cache_dir exceeds max_bytes.

    Cheap enough to call at startup: one os.scandir pass, no hashing, and it
    returns immediately when the cache is under the cap.
    """
    entries = []
    total = 0
    try:
        with os.scandir(cache_dir) as it:
            for entry in it:
                if entry.is_dir():
                    _drop_stale_scratch(entry)
                    continue
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
