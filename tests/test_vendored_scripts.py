"""The vendored thumbfast patch, which nothing pinned.

thumbfast.lua in mpv-runtime/scripts is not upstream's file: it carries three
hand-made changes marked `-- AX Player patch:`. The first of them is the fix
for the bug v1.1.5 spent a release finding -- `thumbfast: cannot create mpv
subprocess` -- and its own comment records the A/B that pinned it:

    8x without env, back to back      ........   (. spawned, X refused)
    8x with env,    back to back      XXXXXXXX
    8x with env,    0.5s apart        ........

So passing `env` is a 100% failure at the rate hovering down the sidebar
produces. Updating thumbfast means reapplying the patches by hand, and until
now a drop-in replacement from upstream would have restored that bug with a
green suite.
"""
from pathlib import Path

import ax_player
from ax_player.paths import bundled_mpv_root

THUMBFAST = bundled_mpv_root() / "scripts" / "thumbfast.lua"


def _lua() -> str:
    return THUMBFAST.read_text(encoding="utf-8", errors="replace")


def test_the_file_under_test_is_this_repos_copy():
    """The anchoring guard, and it is not theoretical.

    The same machine keeps a second copy at C:\\mpv\\scripts\\thumbfast.lua that
    is byte-identical today, so reading the wrong one would pass every content
    assertion below while proving nothing about what this repo ships. That is
    exactly how the build.bat test failed in v1.1.8: it opened a cwd-relative
    path and read a *different repo's* file.

    bundled_mpv_root() resolves through Path(paths.__file__), not the cwd and
    not default_mpv_root() -- which on this machine points at C:\\mpv.
    """
    repo = Path(ax_player.__file__).resolve().parent.parent
    assert THUMBFAST.resolve().is_relative_to(repo), (
        f"reading {THUMBFAST}, which is outside {repo}"
    )
    assert THUMBFAST.is_file()


def test_the_subprocess_helper_passes_no_env():
    """The patch itself. mpv's Windows subprocess implementation refuses the
    spawn when `env` is supplied and the calls are closely spaced --
    CreateProcessW returns FALSE with GetLastError 87, reported up as
    status=-3 / error_string="init".

    Asserted over the helper's body rather than the whole file, which mentions
    env harmlessly elsewhere (`#!/usr/bin/env bash`, `os.getenv`).
    """
    lua = _lua()
    start = lua.index("function subprocess(")
    body = lua[start : lua.index("\nend", start)]
    assert "command_native" in body, "the helper no longer looks like the one that was patched"
    assert "env" not in body, f"`env` is back on a subprocess command:\n{body}"


def test_every_hand_made_change_is_still_marked():
    """A wholesale replacement from upstream would drop all three at once, and
    the env one is the only one whose absence the test above can see. The
    markers are what makes the other two visible.
    """
    lua = _lua()
    assert lua.count("-- AX Player patch:") >= 3
    for marker in (
        "no `env` on the subprocess commands",   # the v1.1.5 root cause
        "retry a refused spawn",                 # per-attempt retry
        "no OSD banner here",                    # the OSD banner removal
    ):
        assert marker in lua, f"the patch marked '{marker}' is gone"
