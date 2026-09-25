"""Staging for the first-run download, which had no tests.

Everything here is about the same hazard, and it is not hypothetical: there is
no single-instance handover (HANDOFF §7), the first run pulls 79 MB behind a
progress dialog, and double-clicking the exe again because "nothing happened"
is an ordinary thing to do. Two processes then shared every staging path.

Measured on Windows: two writers on one path do not exclude each other, they
interleave, and the file ends up holding bytes from both. `fetch_binaries`
skips anything that merely exists, so that corrupt binary is renamed into
place looking complete and is never re-fetched.
"""
from __future__ import annotations

import os
import tarfile
from pathlib import Path

import pytest

from ax_player import mpv_fetch


class _Response:
    """Just enough of urlopen's return for shutil.copyfileobj.

    `declared` is what the server *claims* in Content-Length, which is not
    always what it sends -- that gap is the whole point of one test below.
    """

    def __init__(self, payload: bytes, declared: int | None = None):
        self._payload = payload
        self._read = False
        self.headers = {"Content-Length": str(len(payload) if declared is None else declared)}

    def read(self, size=-1):
        if self._read:
            return b""
        self._read = True
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


def test_the_download_stages_under_a_name_only_this_process_uses(monkeypatch, tmp_path):
    seen: list[str] = []

    def fake_open(_url, timeout=None):
        # Whatever staging path exists at this moment is the one being written.
        seen.extend(p.name for p in tmp_path.glob("*.part"))
        return _Response(b"binary payload")

    monkeypatch.setattr(mpv_fetch.urllib.request, "urlopen", fake_open)

    # The staging file only exists during the write, so it is captured from
    # inside the request rather than looked for afterwards.
    def fake_copy(resp, fh):
        seen.extend(p.name for p in tmp_path.glob("*.part"))
        fh.write(resp.read())

    monkeypatch.setattr(mpv_fetch.shutil, "copyfileobj", fake_copy)

    dest = tmp_path / "libmpv-2.dll"
    mpv_fetch._download("https://example/x", dest, None)

    assert dest.read_bytes() == b"binary payload"
    assert seen, "the staging file was never observed"
    assert any(str(os.getpid()) in name for name in seen), (
        f"staging name is shared between processes: {seen}"
    )


def test_nothing_is_left_behind_when_the_download_fails(monkeypatch, tmp_path):
    """The half-written file must not survive: fetch_binaries skips whatever
    exists, so a leftover is never re-fetched and every URL then fails inside
    mpv's ytdl_hook with nothing to say why."""
    def fake_open(_url, timeout=None):
        raise OSError("connection reset")

    monkeypatch.setattr(mpv_fetch.urllib.request, "urlopen", fake_open)

    dest = tmp_path / "yt-dlp.exe"
    with pytest.raises(OSError):
        mpv_fetch._download("https://example/x", dest, None)

    assert not dest.exists()
    assert list(tmp_path.glob("*.part")) == [], "a staging file survived the failure"


def _archive(tmp_path: Path, member: str, payload: bytes) -> Path:
    src = tmp_path / member
    src.write_bytes(payload)
    arc = tmp_path / "bundle.tar"
    with tarfile.open(arc, "w") as tf:
        tf.add(src, arcname=member)
    src.unlink()
    return arc


def test_extraction_lands_the_member_and_leaves_no_staging(tmp_path):
    """tar writes its output directly, so two processes extracting the same
    member into one directory fight over it the same way two downloads to one
    .part do. Staged per process and renamed in, so each run lands a complete
    file and the loser is merely redundant."""
    payload = b"MZ" + b"\x00" * 4094
    arc = _archive(tmp_path, "mpv.exe", payload)
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    mpv_fetch._extract_member(arc, "mpv.exe", runtime)

    assert (runtime / "mpv.exe").read_bytes() == payload
    assert [p for p in runtime.iterdir() if p.is_dir()] == [], "a staging directory survived"


def test_extraction_stages_where_only_this_process_writes(monkeypatch, tmp_path):
    """Asserted on the directory tar is actually told to write into.

    The first version of this test only checked that no `.stage-*` glob
    survived, which a shared `.stage` also satisfies -- it is cleaned up
    either way, and a single-process extraction works regardless. It passed
    against a mutation that removed the pid, so it was testing the cleanup and
    not the property it claimed.
    """
    arc = _archive(tmp_path, "mpv.exe", b"MZ")
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    told: list[str] = []
    real_run = mpv_fetch.subprocess.run

    def spy(args, **kwargs):
        told.append(args[args.index("-C") + 1])
        return real_run(args, **kwargs)

    monkeypatch.setattr(mpv_fetch.subprocess, "run", spy)

    mpv_fetch._extract_member(arc, "mpv.exe", runtime)

    assert told, "tar was never invoked"
    assert str(os.getpid()) in told[0], (
        f"tar was pointed at a directory other processes share: {told[0]}"
    )
    assert Path(told[0]).parent == runtime, (
        "staging has to sit on the destination's volume for the rename to be atomic"
    )


def test_a_missing_member_raises_rather_than_landing_nothing(tmp_path):
    arc = _archive(tmp_path, "mpv.exe", b"MZ")
    runtime = tmp_path / "runtime"
    runtime.mkdir()

    with pytest.raises(Exception):
        mpv_fetch._extract_member(arc, "libmpv-2.dll", runtime)

    assert not (runtime / "libmpv-2.dll").exists()
    assert list(runtime.glob(".stage-*")) == [], "a staging directory survived the failure"


def test_a_truncated_response_is_refused_rather_than_renamed_into_place(monkeypatch, tmp_path):
    """copyfileobj stops at EOF, and a connection cut mid-body looks exactly
    like the end of one -- so a short read was renamed onto dest as though it
    were whole.

    Demonstrated against a real HTTP server declaring 5 MB and sending 1: no
    error raised, 1 MB landed. fetch_binaries skips whatever exists, so that
    truncated 30 MB DLL is then never fetched again -- the failure this
    module's docstring is about, arriving over the network instead of through
    a crash.
    """
    monkeypatch.setattr(
        mpv_fetch.urllib.request,
        "urlopen",
        lambda _url, timeout=None: _Response(b"x" * 1000, declared=5000),
    )

    dest = tmp_path / "libmpv-2.dll"
    with pytest.raises(RuntimeError, match="不完整"):
        mpv_fetch._download("https://example/x", dest, None)

    assert not dest.exists(), "a truncated file was renamed into place"
    assert list(tmp_path.glob("*.part")) == [], "staging survived the failure"


def test_a_complete_response_still_lands(monkeypatch, tmp_path):
    """The control: the size check must not reject a good download."""
    monkeypatch.setattr(
        mpv_fetch.urllib.request,
        "urlopen",
        lambda _url, timeout=None: _Response(b"x" * 2048),
    )

    dest = tmp_path / "yt-dlp.exe"
    mpv_fetch._download("https://example/x", dest, None)

    assert dest.stat().st_size == 2048


def test_a_chunked_response_is_not_second_guessed(monkeypatch, tmp_path):
    """Chunked responses carry no Content-Length, so there is nothing to
    compare against and the length check has to stand down.

    Standing down is safe *here specifically*: a chunked stream that is cut
    mid-body has no terminating zero-chunk, and http.client raises
    IncompleteRead on its own. Measured against a real socket sending a
    chunk header and then hanging up: IncompleteRead(1000000 bytes read).
    """
    resp = _Response(b"x" * 512)
    resp.headers = {"Transfer-Encoding": "chunked"}
    monkeypatch.setattr(mpv_fetch.urllib.request, "urlopen", lambda _url, timeout=None: resp)

    dest = tmp_path / "mpv.exe"
    mpv_fetch._download("https://example/x", dest, None)

    assert dest.stat().st_size == 512


def test_a_response_with_neither_framing_is_refused(monkeypatch, tmp_path):
    """The version of this test that shipped asserted the opposite, under the
    heading "a server that declares nothing is not second guessed" and the
    reason "chunked responses carry no Content-Length".

    Half of that is right and it is the wrong half that mattered. The fixture
    set `headers = {}` -- no Transfer-Encoding either -- so it was not
    modelling a chunked response at all. It was modelling the one framing that
    has no protection: the body ends when the connection does, and a cut is
    indistinguishable from a clean finish.

    Measured across all three shapes before the fix: declared-length-short was
    caught, chunked-and-cut raised IncompleteRead, and this one accepted 1 MB
    of a 5 MB file and renamed it into place -- where fetch_binaries' "skip
    what exists" means it is never fetched again.

    Refusing is the asymmetric choice on purpose: a false refusal is an error
    and a retry, a false accept is a permanently corrupt binary. HTTP/1.1
    requires one of the two framings, so this rejects only a 1.0 server or a
    malformed 1.1 one -- not GitHub or SourceForge, where all three of these
    URLs live.
    """
    resp = _Response(b"x" * 512)
    resp.headers = {}
    monkeypatch.setattr(mpv_fetch.urllib.request, "urlopen", lambda _url, timeout=None: resp)

    dest = tmp_path / "mpv.exe"
    with pytest.raises(RuntimeError, match="無法驗證"):
        mpv_fetch._download("https://example/x", dest, None)

    assert not dest.exists(), "an unverifiable body was renamed into place"
    assert not list(tmp_path.glob("*.part")), "staging file left behind"


# -- setup_mpv.py on a console that cannot print Chinese ---------------------
_SETUP_ON_CP1252 = '''
import sys
from pathlib import Path

repo, target = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(repo))
import setup_mpv

setup_mpv.bundled_mpv_root = lambda: target


def fake_fetch(dest, on_progress=print):
    on_progress("下載中：mpv.exe")          # what the real fetcher reports
    for name in ("mpv.exe", "libmpv-2.dll", "yt-dlp.exe"):
        (dest / name).write_bytes(b"x")


setup_mpv.fetch_binaries = fake_fetch
raise SystemExit(setup_mpv.main())
'''


def test_setup_mpv_survives_an_output_that_cannot_encode_its_progress(tmp_path):
    """CI's first run on windows-latest: stdout is a pipe in cp1252, `print`
    is the progress callback, and the first Chinese progress line raised
    UnicodeEncodeError from inside the download. setup_mpv reported that as a
    failed fetch and exited 1 -- a line it could not display aborted the work.
    This zh-TW machine (cp950) could never show it."""
    import subprocess
    import sys

    import ax_player

    repo = Path(ax_player.__file__).resolve().parent.parent
    env = dict(os.environ, PYTHONIOENCODING="cp1252")
    result = subprocess.run(
        [sys.executable, "-c", _SETUP_ON_CP1252, str(repo), str(tmp_path)],
        capture_output=True,
        env=env,
        timeout=60,
    )
    output = (result.stdout + result.stderr).decode("cp1252", errors="replace")
    assert result.returncode == 0, f"setup_mpv failed on a cp1252 pipe:\n{output}"
    assert "Done:" in output
    assert all((tmp_path / n).is_file() for n in ("mpv.exe", "libmpv-2.dll", "yt-dlp.exe"))
