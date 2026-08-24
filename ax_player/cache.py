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
