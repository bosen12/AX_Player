"""The conftest fixture that keeps the suite off the real %LOCALAPPDATA%.

CLAUDE.md: "Without it the suite prunes and rewrites the real user's thumbnail
cache -- which has happened." test_caches.py has the blunt half of the check
(is app_data_dir() a temp path), and that would not notice the failure this
conftest actually spends most of its lines defending against.

That failure is caching. The fixture resets three module globals --
debug_log._log_path, settings._store, resume._cache -- because each one
resolves its path once and keeps it. A fourth appearing, or one of these
resets being dropped, leaves whichever test ran first pinning the directory
for the other hundred: not destructive by itself, one refactor away from
being so, and invisible to a check that only asks whether the path looks
temporary.

So this asks three things the blunt check cannot:
  - every path helper that sits under %LOCALAPPDATA% moves when it moves
  - a cache populated during a test lands inside that test's own directory
  - conftest still resets every module-level cache the package has

Fluid Motion's tests/test_isolation.py is the same guard for %APPDATA%.
"""
import inspect
from pathlib import Path

import pytest

from ax_player import debug_log, paths, resume, settings


def _path_helpers() -> list[str]:
    found = []
    for name, fn in vars(paths).items():
        if name.startswith("_") or not callable(fn) or inspect.isclass(fn):
            continue
        module = getattr(fn, "__module__", None)
        if module != paths.__name__:
            continue
        try:
            sig = inspect.signature(fn)
        except (TypeError, ValueError):
            continue
        if any(p.default is inspect.Parameter.empty for p in sig.parameters.values()):
            continue
        found.append(name)
    return sorted(found)


def _answers(monkeypatch, local: Path) -> dict[str, Path]:
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    out = {}
    for name in _path_helpers():
        try:
            value = getattr(paths, name)()
        except Exception:
            continue
        if isinstance(value, Path):
            out[name] = value
    return out


def test_the_helpers_are_actually_being_enumerated():
    """Guards the guard: a rename that empties the list would make everything
    below pass by checking nothing."""
    names = _path_helpers()
    for expected in ("app_data_dir", "thumbnail_cache_dir", "contact_sheet_cache_dir",
                     "resume_db_path"):
        assert expected in names, f"{expected} dropped out of the enumeration"


def test_every_path_under_localappdata_moves_when_it_moves(tmp_path, monkeypatch):
    """The lru_cache'd helpers exclude themselves: bundled_mpv_root and
    default_mpv_root do not sit under %LOCALAPPDATA% in a source checkout, so
    the rule skips them without anyone having to list them."""
    first, second = tmp_path / "one", tmp_path / "two"

    before = _answers(monkeypatch, first)
    after = _answers(monkeypatch, second)

    tracked = [n for n, p in before.items() if first == p or first in p.parents]
    assert tracked, "nothing resolved under LOCALAPPDATA -- the check measures nothing"

    stuck = [n for n in tracked if not (second == after[n] or second in after[n].parents)]
    assert not stuck, (
        f"these kept the old %LOCALAPPDATA% after it changed: {stuck}. "
        "A cached module global writes into the real user's directory."
    )


def test_the_cached_globals_populate_inside_this_tests_directory():
    """Where these land when something populates them.

    Deliberately not claiming more than that. An earlier version said it
    covered the conftest resets, and it did not: dropping
    `monkeypatch.setattr(debug_log, "_log_path", None)` left it green, because
    running this test alone makes it the first to log and the cache is empty
    anyway. Leakage only shows across tests in one session, and a test that
    depends on another having run first is worse than the hole it fills.

    The resets are covered by the test below instead, which asks whether
    conftest still knows about every cache there is.
    """
    room = paths.app_data_dir()

    debug_log.log("populating the log path")
    assert debug_log._log_path is not None, "logging did not populate the cache"
    assert debug_log._log_path.is_relative_to(room), (
        f"debug.log resolved to {debug_log._log_path}, outside {room}"
    )

    settings.set_last_folder("Z:/somewhere")
    assert settings._store is not None, "the settings store did not populate"
    assert Path(settings._store.fileName()).is_relative_to(room), (
        f"settings.ini resolved to {settings._store.fileName()}, outside {room}"
    )

    resume.save_progress(r"Z:\v\ep1.mkv", 5.0, 100.0)
    assert resume._cache is not None, "the resume cache did not populate"
    assert paths.resume_db_path().is_relative_to(room), (
        f"resume.json resolved to {paths.resume_db_path()}, outside {room}"
    )


def test_the_suite_is_not_pointed_at_a_real_localappdata():
    """The blunt half, kept here beside the rest rather than only in
    test_caches.py: if the fixture stopped applying entirely, every path above
    would agree with each other and still be wrong."""
    home = Path.home()
    room = paths.app_data_dir()

    assert room != home / "AppData" / "Local" / "AXPlayer", (
        "the suite is writing to the real %LOCALAPPDATA%\\AXPlayer"
    )
    assert "tmp" in str(room).lower() or "temp" in str(room).lower(), (
        f"app_data_dir() is {room}, which is not a temporary directory"
    )


def test_conftest_resets_every_module_level_cache_there_is():
    """The risk the resets exist for is a *fourth* one appearing.

    debug_log._log_path, settings._store and resume._cache are each resolved
    once and kept, and each is reset per test. Nothing notices when a new
    module gains the same pattern -- the suite goes on passing while whichever
    test runs first pins that directory for all the others. Not destructive on
    its own; one refactor away from being so, which is what the conftest's own
    comment says.

    Derived from the source rather than listed here, for the reason §9.17
    settled: a hand-kept list is true of what somebody remembered.
    """
    import ast

    package = Path(paths.__file__).resolve().parent
    conftest = (Path(__file__).resolve().parent / "conftest.py").read_text(encoding="utf-8")

    caches: list[str] = []
    for source in sorted(package.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in tree.body:
            targets = []
            if isinstance(node, ast.Assign):
                targets = [t for t in node.targets if isinstance(t, ast.Name)]
                value = node.value
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets, value = [node.target], node.value
            else:
                continue
            if not isinstance(value, ast.Constant) or value.value is not None:
                continue
            for target in targets:
                if target.id.startswith("_"):
                    caches.append(f"{source.stem}.{target.id}")

    assert caches, "no module-level caches found at all -- this check stopped looking"

    missed = [c for c in caches if c.split(".")[-1] not in conftest]
    assert not missed, (
        f"conftest does not reset {missed}. Each is resolved once and kept, so "
        "whichever test runs first pins it for the rest of the session."
    )
