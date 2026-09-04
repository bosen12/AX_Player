"""Every mpv property this app reads has to be one mpv actually has.

inject.py in the sibling project carries the scar: "mpv's property is
estimated-vf-fps. The name used here until now, estimated-vfps, does not
exist, so _get's IpcError guard swallowed the 'property not found' reply and
returned None every single time -- the fps readout has been silently falling
back to container-fps."

All three of §9.40's questions answer yes here. The two sides are joined by a
string, not a signature. A wrong one does not raise: PlayerWidget._prop
catches everything and answers None. And None renders as "—", which is what
the panel also shows when the value is genuinely unavailable.

mpv tells the two apart itself, which is what makes this checkable at all:

    property not found    -> the name is wrong
    property unavailable  -> the name is real, there is just nothing playing

One mpv, one connection, every name in a single pass -- measured at about a
second, which is what it is worth on a suite this size.
"""
import ast
import subprocess
import time
from pathlib import Path

import pytest

import ax_player
from ax_player.paths import mpv_exe

pytestmark = pytest.mark.skipif(
    mpv_exe() is None,
    reason="mpv.exe is gitignored and fetched by setup_mpv.py; nothing to ask",
)


def _property_names() -> set[str]:
    """Every name handed to PlayerWidget._prop, read out of the source.

    Derived rather than listed: a name added to diagnostics() without being
    added here would be exactly the case this exists to catch.
    """
    source = Path(ax_player.__file__).resolve().parent / "player_widget.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "_prop" or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            names.add(first.value)
    return names


def test_the_names_are_actually_being_extracted():
    """Guards the guard: an empty set would make the check below pass by
    asking mpv nothing at all."""
    names = _property_names()
    assert len(names) >= 10, f"only found {sorted(names)}"
    for expected in ("hwdec_current", "estimated_vf_fps", "frame_drop_count"):
        assert expected in names, f"{expected} dropped out of the extraction"


def test_every_property_name_exists_in_mpv(tmp_path):
    exe = mpv_exe()
    pipe = rf"\\.\pipe\axprops-{int(time.time() * 1000) % 100000}"
    proc = subprocess.Popen(
        [str(exe), "--no-config", "--idle=yes", "--vo=null", "--ao=null",
         f"--input-ipc-server={pipe}", "--really-quiet"],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    try:
        handle = None
        for _ in range(100):
            try:
                handle = open(pipe, "r+b", buffering=0)
                break
            except OSError:
                time.sleep(0.05)
        if handle is None:
            pytest.skip("could not reach the probe mpv's IPC pipe")

        import json

        def ask(name: str) -> str:
            handle.write(
                (json.dumps({"command": ["get_property", name], "request_id": 1}) + "\n").encode()
            )
            deadline = time.time() + 5
            buffer = b""
            while time.time() < deadline:
                buffer += handle.read(4096) or b""
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    message = json.loads(line.decode("utf-8", "replace"))
                    if message.get("request_id") == 1:
                        return str(message.get("error", ""))
                time.sleep(0.005)
            return "timed out"

        wrong = [
            name for name in sorted(_property_names())
            if "not found" in ask(name.replace("_", "-"))
        ]
        handle.close()

        assert not wrong, (
            f"mpv has no such properties: {wrong}. _prop swallows the error and "
            "answers None, which the panel draws as '—' -- the same thing it "
            "shows when the value is merely unavailable."
        )
    finally:
        proc.kill()
        proc.wait(timeout=10)
