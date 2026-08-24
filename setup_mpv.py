"""Fetches the official mpv/libmpv Windows build into mpv-runtime/.

Everything else in mpv-runtime/ (uosc, thumbfast, fonts, configs) is
checked into this repo directly -- small, stable text/lua files. Only
mpv.exe and libmpv-2.dll are fetched here, since they're large binaries
that change often; see https://mpv.io/installation/ for what's being
downloaded and from where (the official mpv-player-windows builds).

Run once after cloning:

    py -3 setup_mpv.py

Requires nothing beyond Python and Windows' own bundled `tar.exe`
(actually bsdtar, ships with Windows 10 1803+ and Windows 11 -- it can
read 7z archives including the BCJ2-filtered ones mpv ships, which pure
-Python 7z libraries like py7zr cannot).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

RSS_URL = "https://sourceforge.net/projects/mpv-player-windows/rss?path=/"
RUNTIME_DIR = Path(__file__).parent / "mpv-runtime"
TIMEOUT = 60


def _latest_download_url(title_prefix: str) -> str:
    """Find the newest release under title_prefix in the project's feed.

    Skips the -v3 (AVX2-required) variant for broader CPU compatibility.
    """
    with urllib.request.urlopen(RSS_URL, timeout=TIMEOUT) as resp:
        root = ET.fromstring(resp.read())
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if title.startswith(title_prefix) and "-v3" not in title:
            link = item.findtext("link")
            if link:
                return link
    raise RuntimeError(f"no release matching {title_prefix!r} found in mpv-player-windows feed")


def _download(url: str, dest: Path) -> None:
    print(f"downloading {url}")
    with urllib.request.urlopen(url, timeout=300) as resp, open(dest, "wb") as fh:
        shutil.copyfileobj(resp, fh)


def _extract_member(archive: Path, member: str, dest_dir: Path) -> None:
    subprocess.run(["tar", "-xf", str(archive), "-C", str(dest_dir), member], check=True)


def main() -> int:
    if shutil.which("tar") is None:
        print("tar.exe not found -- this needs Windows 10 1803+ or Windows 11.", file=sys.stderr)
        return 1

    RUNTIME_DIR.mkdir(exist_ok=True)
    mpv_exe = RUNTIME_DIR / "mpv.exe"
    libmpv = RUNTIME_DIR / "libmpv-2.dll"
    if mpv_exe.is_file() and libmpv.is_file():
        print(f"{RUNTIME_DIR} already has mpv.exe and libmpv-2.dll -- nothing to do.")
        return 0

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)

        player_archive = tmp_dir / "mpv-player.7z"
        _download(_latest_download_url("/64bit/mpv-x86_64-"), player_archive)
        _extract_member(player_archive, "mpv.exe", RUNTIME_DIR)

        libmpv_archive = tmp_dir / "mpv-libmpv.7z"
        _download(_latest_download_url("/libmpv/mpv-dev-x86_64-"), libmpv_archive)
        _extract_member(libmpv_archive, "libmpv-2.dll", RUNTIME_DIR)

    print(f"Done:\n  {mpv_exe}\n  {libmpv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
