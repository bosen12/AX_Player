"""The one line a bug report has to lean on.

A windowed build has no console, so `mpv runtime: ...` in debug.log is the only
record of which mpv root won and what it could do. It already covered the
libmpv/VapourSynth/lua split; yt-dlp was missing, and yt-dlp is the capability
that goes absent on an otherwise working install:
mpv_fetch.ensure_runtime() fetches mpv.exe, libmpv-2.dll and yt-dlp.exe
together, but returns before any of it the moment a candidate root already has
libmpv-2.dll -- so a personal C:\\mpv is never topped up.
"""
from pathlib import Path

import ax_player
from ax_player import app as app_mod
from ax_player import debug_log


def _log_once(monkeypatch, root: Path) -> str:
    lines: list[str] = []
    monkeypatch.setattr(debug_log, "log", lines.append)
    monkeypatch.setattr("ax_player.paths.default_mpv_root", lambda: root)
    app_mod._log_mpv_runtime()
    assert len(lines) == 1, "one line per launch, so a log opened later still says which build"
    return lines[0]


def test_safe_url_removes_credentials_query_and_fragment():
    url = "https://user:password@example.com/video/master.m3u8?token=secret#private"

    safe = debug_log.safe_url(url)

    assert safe == "https://example.com/video/master.m3u8"
    for secret in ("user", "password", "token", "secret", "private"):
        assert secret not in safe


def test_both_url_log_call_sites_redact_but_play_the_original(monkeypatch):
    from types import SimpleNamespace

    from ax_player.app import AXPlayerWindow
    from ax_player.player_widget import PlayerWidget

    url = "https://user:password@example.com/live.m3u8?token=secret#private"
    lines: list[str] = []
    monkeypatch.setattr(debug_log, "log", lines.append)

    window_calls = []
    window = SimpleNamespace(player=SimpleNamespace(play_url=window_calls.append))
    AXPlayerWindow.play_url(window, url)

    mpv_calls = []
    widget = SimpleNamespace(
        _loaded=[Path("C:/V/ep1.mkv")],
        _mpv=SimpleNamespace(command=lambda *args: mpv_calls.append(args)),
    )
    PlayerWidget.play_url(widget, url)

    assert window_calls == [url]
    assert mpv_calls == [("loadfile", url, "replace")]
    joined = "\n".join(lines)
    assert "example.com/live.m3u8" in joined
    for secret in ("user", "password", "token", "secret", "private"):
        assert secret not in joined


def test_a_root_without_yt_dlp_says_so(monkeypatch, tmp_path):
    """The failing install: libmpv is there, so ensure_runtime() never runs and
    never fetches yt-dlp.exe. ytdlp_exe() is then None, script_opts drops
    ytdl_hook-ytdl_path, and 開啟網址 silently handles only direct media links.

    Without this field the log says the runtime is fine, because by every other
    measure it is.
    """
    (tmp_path / "libmpv-2.dll").write_bytes(b"x")
    (tmp_path / "mpv.exe").write_bytes(b"x")

    line = _log_once(monkeypatch, tmp_path)

    assert "ytdlp=False" in line, f"yt-dlp is not reported at all: {line}"
    assert "libmpv=True" in line and "mpv_exe=True" in line, (
        "the rest of the line has to keep saying the install is otherwise fine "
        "-- that contrast is the whole diagnostic"
    )


def test_a_complete_runtime_reports_every_capability(monkeypatch, tmp_path):
    """The other half: a field that is always False is not a diagnostic."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    for name in ("libmpv-2.dll", "mpv.exe", "yt-dlp.exe", "vapoursynth.dll"):
        (tmp_path / name).write_bytes(b"x")
    for name in ("zz-fluid-ipc.lua", "mpvSockets.lua"):
        (scripts / name).write_bytes(b"x")

    line = _log_once(monkeypatch, tmp_path)

    for field in ("libmpv", "mpv_exe", "ytdlp", "vapoursynth", "fluid_ipc_lua", "mpv_sockets_lua"):
        assert f"{field}=True" in line, f"{field} missing from: {line}"
    assert str(tmp_path) in line, "the line has to name the root that won"


def test_the_fetcher_and_the_log_agree_on_which_binaries_matter():
    """Derived rather than written out: the log's capability fields for the
    fetched binaries have to be the binaries mpv_fetch actually fetches. A
    fourth download added there without a field here would go unreported in
    exactly the situation this log exists for.
    """
    src = Path(ax_player.__file__).resolve().parent
    fetch = (src / "mpv_fetch.py").read_text(encoding="utf-8")
    logged = (src / "app.py").read_text(encoding="utf-8")

    for binary in ("mpv.exe", "libmpv-2.dll", "yt-dlp.exe"):
        assert binary in fetch, f"{binary} is no longer fetched -- update this test"
        assert f"'{binary}'" in logged or f'"{binary}"' in logged, (
            f"mpv_fetch downloads {binary} but the runtime log never reports it"
        )


# -- which mpv root wins --------------------------------------------------
def test_the_bundled_runtime_is_preferred_over_a_personal_install(tmp_path, monkeypatch):
    r""""a fresh install just works off setup_mpv.py alone" -- the bundled root
    is checked first precisely so a machine that also has C:\mpv does not
    quietly take it over.

    Which root wins is not cosmetic: §9.20 turned on it. The root decides
    whether yt-dlp.exe is there (so whether 開啟網址 resolves anything), and
    whether VapourSynth is (so whether Fluid Motion's filter can load at all).

    The candidate list is injected rather than left to the machine. The first
    version of this test monkeypatched only bundled_mpv_root and asserted the
    answer equalled it -- which deleting the whole search loop also satisfies,
    because the fallback returns the same value. mpv_root_candidates() exists
    so the two can be told apart.
    """
    from ax_player import paths

    bundled = tmp_path / "bundled"
    personal = tmp_path / "personal"
    for root in (bundled, personal):
        root.mkdir()
        (root / "libmpv-2.dll").write_bytes(b"x")

    monkeypatch.setattr(paths, "bundled_mpv_root", lambda: bundled)
    monkeypatch.setattr(paths, "mpv_root_candidates", lambda: [bundled, personal])
    paths.default_mpv_root.cache_clear()
    try:
        assert paths.default_mpv_root() == bundled, "a personal install took over"
    finally:
        paths.default_mpv_root.cache_clear()


def test_a_personal_install_is_used_when_the_bundled_one_is_empty(tmp_path, monkeypatch):
    """The other half, and the one that tells the search from the fallback:
    with no libmpv in the bundled root the loop has to walk on, where the
    fallback would stop at the bundled root and report a runtime that is not
    there. _bootstrap_mpv_if_needed() tests exactly that path.
    """
    from ax_player import paths

    bundled = tmp_path / "bundled"
    personal = tmp_path / "personal"
    bundled.mkdir()
    personal.mkdir()
    (personal / "libmpv-2.dll").write_bytes(b"x")

    monkeypatch.setattr(paths, "bundled_mpv_root", lambda: bundled)
    monkeypatch.setattr(paths, "mpv_root_candidates", lambda: [bundled, personal])
    paths.default_mpv_root.cache_clear()
    try:
        assert paths.default_mpv_root() == personal, "stopped at a root with no libmpv"
    finally:
        paths.default_mpv_root.cache_clear()
