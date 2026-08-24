"""Fetches the official mpv/libmpv Windows build.

Shared by two callers:
- setup_mpv.py (project root): the source-checkout CLI entry point.
- app.py's frozen-mode bootstrap: the packaged AXPlayer.exe runs this on
  first launch, since there's no run.bat there to call setup_mpv.py first.

See https://mpv.io/installation/ for what's being downloaded and from
where (the official mpv-player-windows builds).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

RSS_URL = "https://sourceforge.net/projects/mpv-player-windows/rss?path=/"
YTDLP_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"
_CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _latest_download_url(title_prefix: str) -> str:
    """Find the newest release under title_prefix in the project's feed.

    Skips the -v3 (AVX2-required) variant for broader CPU compatibility.
    """
    with urllib.request.urlopen(RSS_URL, timeout=60) as resp:
        root = ET.fromstring(resp.read())
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if title.startswith(title_prefix) and "-v3" not in title:
            link = item.findtext("link")
            if link:
                return link
    raise RuntimeError(f"no release matching {title_prefix!r} found in mpv-player-windows feed")


def _download(url: str, dest: Path, on_progress: Callable[[str], None] | None) -> None:
    if on_progress:
        on_progress(f"下載中：{dest.name}")
    with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _extract_member(archive: Path, member: str, dest_dir: Path) -> None:
    subprocess.run(
        ["tar", "-xf", str(archive), "-C", str(dest_dir), member],
        check=True,
        creationflags=_CREATE_NO_WINDOW,
    )


def fetch_binaries(runtime_dir: Path, on_progress: Callable[[str], None] | None = None) -> None:
    """Download mpv.exe + libmpv-2.dll + yt-dlp.exe into runtime_dir. Each
    is skipped individually if already present. Raises on failure --
    callers decide how to surface that (CLI prints it, the packaged app
    shows a dialog).

    Requires nothing beyond Windows' own bundled `tar.exe` (actually
    bsdtar, ships with Windows 10 1803+ and Windows 11) to extract the 7z
    archives -- including the BCJ2-filtered ones mpv ships, which
    pure-Python 7z libraries like py7zr can't handle.
    """
    if shutil.which("tar") is None:
        raise RuntimeError("tar.exe not found -- this needs Windows 10 1803+ or Windows 11.")

    runtime_dir.mkdir(parents=True, exist_ok=True)
    mpv_exe = runtime_dir / "mpv.exe"
    libmpv = runtime_dir / "libmpv-2.dll"
    ytdlp = runtime_dir / "yt-dlp.exe"

    if not (mpv_exe.is_file() and libmpv.is_file()):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_dir = Path(tmp)

            player_archive = tmp_dir / "mpv-player.7z"
            _download(_latest_download_url("/64bit/mpv-x86_64-"), player_archive, on_progress)
            _extract_member(player_archive, "mpv.exe", runtime_dir)

            libmpv_archive = tmp_dir / "mpv-libmpv.7z"
            _download(_latest_download_url("/libmpv/mpv-dev-x86_64-"), libmpv_archive, on_progress)
            _extract_member(libmpv_archive, "libmpv-2.dll", runtime_dir)

    if not ytdlp.is_file():
        # mpv's built-in ytdl_hook shells out to a yt-dlp binary -- it isn't
        # embedded in mpv itself. Without this, "open URL" silently can't
        # resolve anything from YouTube/Twitch/etc, only direct media links.
        _download(YTDLP_URL, ytdlp, on_progress)


def ensure_runtime(on_progress: Callable[[str], None] | None = None) -> None:
    """Full first-run bootstrap for the packaged (frozen) app: no-ops if
    mpv is already resolvable anywhere (a previous fetch, or a personal
    C:\\mpv / Program Files install) -- only does work on a genuinely
    fresh install with nothing else available.
    """
    from ax_player.paths import bundled_mpv_root, default_mpv_root

    if (default_mpv_root() / "libmpv-2.dll").is_file():
        return

    target = bundled_mpv_root()
    if getattr(sys, "frozen", False):
        # Seed the small, read-only config/scripts bundled into the exe
        # (uosc, thumbfast, mpv.conf, ...) into the writable per-user
        # runtime dir alongside the two binaries fetched below -- mpv
        # needs config_dir to hold all of it together.
        bundled_source = Path(sys._MEIPASS) / "mpv-runtime"  # type: ignore[attr-defined]
        if bundled_source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            for item in bundled_source.iterdir():
                dest = target / item.name
                if dest.exists():
                    continue
                if item.is_dir():
                    shutil.copytree(item, dest)
                else:
                    shutil.copy2(item, dest)

    fetch_binaries(target, on_progress=on_progress)
