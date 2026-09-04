"""Every field the diagnostics panel reads has to be one somebody produces.

Two producers feed one consumer: PlayerWidget.diagnostics() answers what mpv is
doing, diagnostics.query_gpu() answers what the GPU is doing, and
ui.DiagnosticsPanel reads both by name out of plain dicts. Nothing connects
them -- a key renamed on either producer leaves that row showing "—", which is
exactly what it shows when the value is genuinely unavailable.

That is the symptom this loop keeps meeting: the failure and the normal state
render identically. Fluid Motion's tests/test_state_contract.py is the same
guard for its own state() -> app.js boundary (HANDOFF §9.39).

Both sides are read out of the source with ast/regex rather than by calling
anything, so this needs neither libmpv nor an nvidia-smi.
"""
import ast
import re
from pathlib import Path

import ax_player


def _module(name: str) -> Path:
    return Path(ax_player.__file__).resolve().parent / name


def _returned_dict_keys(source: Path, function: str) -> set[str]:
    """String keys of the dict literal `function` returns."""
    tree = ast.parse(source.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name != function:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.Return) and isinstance(inner.value, ast.Dict):
                return {
                    k.value for k in inner.value.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)
                }
    return set()


def _panel_reads() -> set[str]:
    text = _module("ui.py").read_text(encoding="utf-8")
    return {
        m.group(2)
        for m in re.finditer(r"\b(stats|gpu)(?:\.get\(|\[)['\"]([a-z_]+)['\"]", text)
    }


def _produced() -> set[str]:
    return (
        _returned_dict_keys(_module("player_widget.py"), "diagnostics")
        | _returned_dict_keys(_module("diagnostics.py"), "query_gpu")
    )


def test_both_sides_are_actually_being_extracted():
    """Guards the guard. Either half coming back empty would make the check
    below pass by comparing nothing against nothing."""
    produced, read = _produced(), _panel_reads()
    assert len(produced) >= 15, f"only found {sorted(produced)} produced"
    assert len(read) >= 15, f"only found {sorted(read)} read"
    for key in ("hwdec", "interpolating", "vram_used"):
        assert key in produced and key in read, f"{key} fell out of one side"


def test_every_field_the_panel_reads_is_produced():
    orphans = sorted(_panel_reads() - _produced())
    assert not orphans, (
        f"DiagnosticsPanel reads {orphans}, which neither diagnostics() nor "
        "query_gpu() produces. The row renders '—', which is what it also "
        "shows when the value is genuinely unavailable."
    )


def test_a_produced_field_nobody_reads_stays_listed_here():
    """Not a failure -- a producer may legitimately run ahead of its consumer.

    Recorded rather than asserted-away so the list is visible: display_fps is
    read from mpv on every refresh and never displayed. One python-mpv property
    read per second while the panel is open, which is not worth removing, but
    it should not silently grow either.
    """
    unused = sorted(_produced() - _panel_reads())

    assert unused == ["display_fps"], (
        f"the set of produced-but-unread fields changed to {unused}. If that is "
        "deliberate, update this list; if not, a panel row stopped reading "
        "something it used to show."
    )
