"""Compile-time warnings, which are invisible on every run but the first.

CPython emits SyntaxWarning while *compiling* a module and then caches the
result in __pycache__, so a bad escape sequence announces itself once -- on
the run right after the file is edited -- and is silent from then on. Two
were sitting in this repo's tests unnoticed for exactly that reason, found
only because a suite run happened to follow a source change.

They are not cosmetic. "\\m" and "\\d" are invalid escape sequences that
Python still resolves to themselves today, with a warning saying "such
sequences will not work in the future"; the plan of record is for them to
become SyntaxError. A docstring that mentions C:\\mpv is a real Windows path
this codebase talks about constantly, so this will keep happening.
"""
import pathlib
import warnings

SKIP_DIRS = {"__pycache__", "build", "dist", ".venv", "venv", ".git"}


def _sources(root: pathlib.Path):
    for path in sorted(root.rglob("*.py")):
        if SKIP_DIRS.isdisjoint(path.parts):
            yield path


def test_no_module_compiles_with_a_warning():
    """Every .py in the repo, compiled fresh with warnings turned up.

    Anchored through this file rather than the cwd: a cwd-relative walk in a
    test once opened a *different repo's* file and passed on it (CLAUDE.md
    records that one), and this test's whole job is to look at these sources.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    assert (root / "ax_player").is_dir(), f"anchored at the wrong tree: {root}"

    found = []
    for path in _sources(root):
        source = path.read_text(encoding="utf-8", errors="replace")
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            compile(source, str(path), "exec")
        for warning in caught:
            found.append(
                f"{path.relative_to(root)}:{warning.lineno} "
                f"{warning.category.__name__}: {warning.message}"
            )

    assert not found, "\n".join(["compile-time warnings:", *found])
