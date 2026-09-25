"""CLI entry point for fetching mpv into mpv-runtime/ in a source checkout.

The actual logic lives in ax_player/mpv_fetch.py, shared with the packaged
AXPlayer.exe's own first-run bootstrap (there's no run.bat there to call
this script first, so the frozen app does the equivalent itself).

Run once after cloning:

    py -3 setup_mpv.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from ax_player.mpv_fetch import fetch_binaries  # noqa: E402
from ax_player.paths import bundled_mpv_root  # noqa: E402


def main() -> int:
    # The progress messages are Chinese and `print` is the progress callback,
    # so an output stream that cannot encode them made the callback raise
    # UnicodeEncodeError from inside fetch_binaries -- which the handler below
    # reported as a failed download and exited 1. A progress line that cannot
    # be displayed was aborting the actual work. That is any piped stdout on a
    # machine whose code page is not a CJK one: CI on windows-latest (cp1252)
    # failed on its very first run, while this zh-TW machine (cp950) never
    # could. Unencodable characters are escaped instead; nothing raises.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, ValueError):
            pass  # not a TextIOWrapper (redirected into something else)
    target = bundled_mpv_root()
    files = ["mpv.exe", "libmpv-2.dll", "yt-dlp.exe"]
    if all((target / name).is_file() for name in files):
        print(f"{target} already has everything -- nothing to do.")
        return 0
    try:
        fetch_binaries(target, on_progress=print)
    except Exception as exc:
        print(f"failed: {exc}", file=sys.stderr)
        return 1
    print("Done:\n  " + "\n  ".join(str(target / name) for name in files))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
