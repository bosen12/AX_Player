"""What the release bundle leaves out, and why leaving it out is safe.

AXPlayer.spec excludes PIL and numpy. Neither is a dependency of this app --
requirements.txt lists PySide6 and python-mpv -- but PyInstaller's analysis
follows imports into function bodies and TYPE_CHECKING blocks, and the build
interpreter's site-packages is shared with Fluid Motion. The chain it walked:

    mpv (python-mpv)  --lazy, in screenshot_raw / ImageOverlay.update-->  PIL
    PIL._typing       --under `if TYPE_CHECKING:`-->                     numpy
    numpy.testing -> psutil, numpy.__config__ -> yaml, numpy.f2py -> charset_normalizer

Measured in the v1.3.10 onedir: 39.5 MB of 165 MB, 24% of what shipped, none
of it imported at runtime.

An exclude has one failure mode worth a test, and it is the worst kind: the
source tree has the module, so everything works from a checkout and in this
suite, and only the frozen build dies -- with an ImportError nobody who ran
the tests could have seen. So these pin the two things that make the exclude
safe, not just the exclude itself.
"""
import ast
import importlib.util
from pathlib import Path

import ax_player

DEAD_CHAIN = ("PIL", "numpy")


def _repo() -> Path:
    # Through the package, never the cwd -- see test_public_surfaces._repo.
    return Path(ax_player.__file__).resolve().parent.parent


def _spec_excludes() -> list[str]:
    tree = ast.parse((_repo() / "AXPlayer.spec").read_text(encoding="utf-8"))
    for node in tree.body:
        if (
            isinstance(node, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "excludes" for t in node.targets)
        ):
            return list(ast.literal_eval(node.value))
    raise AssertionError("AXPlayer.spec has no top-level `excludes = [...]`")


def _all_imports(source: str) -> set[str]:
    """Every module imported anywhere in the source, function bodies included."""
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.add(node.module)
    return found


def _import_time_imports(source: str) -> set[str]:
    """Imports that run when the module is imported: anything not inside a
    function body. Class bodies and module-level if/try blocks count -- they
    execute at import too."""
    found = set()

    def visit(node):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                continue
            if isinstance(child, ast.Import):
                found.update(alias.name for alias in child.names)
            elif isinstance(child, ast.ImportFrom) and child.module and child.level == 0:
                found.add(child.module)
            visit(child)

    visit(ast.parse(source))
    return found


def _covers(module: str, excluded: str) -> bool:
    return module == excluded or module.startswith(excluded + ".")


def test_the_release_spec_leaves_out_the_dead_chain():
    excludes = _spec_excludes()
    missing = [name for name in DEAD_CHAIN if name not in excludes]
    assert not missing, (
        f"AXPlayer.spec no longer excludes {missing}; the release grows by the "
        "~40 MB this app never imports"
    )


def test_nothing_the_app_ships_imports_an_excluded_module():
    """Derived from the spec, so a new exclude is checked without editing this.

    Function-level imports count: the frozen build has no copy to import
    lazily either, and a lazy import is exactly the one that passes every
    test and fails for a user the first time that code path runs.
    """
    excludes = _spec_excludes()
    shipped = sorted((_repo() / "ax_player").rglob("*.py")) + [_repo() / "packaging" / "launch.py"]
    assert len(shipped) > 5, f"found almost nothing to check under {_repo()}"

    offenders = []
    for path in shipped:
        for module in _all_imports(path.read_text(encoding="utf-8")):
            for excluded in excludes:
                if _covers(module, excluded):
                    offenders.append(f"{path.relative_to(_repo())}: imports {module} (excluded: {excluded})")
    assert not offenders, "\n".join(
        ["the source runs, the release would not:", *offenders]
    )


def test_python_mpv_still_imports_pil_only_lazily():
    """The exclude is safe only while python-mpv keeps PIL inside the two
    methods that use it. A release of python-mpv that imported it at module
    level would make the frozen app die at `import mpv` -- on start-up, for
    everyone -- while every test here still passed.

    Located with find_spec, which does not execute the module: importing mpv
    for real needs libmpv on PATH.
    """
    spec = importlib.util.find_spec("mpv")
    assert spec is not None and spec.origin, "python-mpv is not installed"
    source = Path(spec.origin).read_text(encoding="utf-8")

    assert any(_covers(m, "PIL") for m in _all_imports(source)), (
        "python-mpv no longer imports PIL at all -- then nothing pulls it in "
        "and this test's premise is stale; re-derive the exclude list"
    )
    eager = [m for m in _import_time_imports(source) for e in DEAD_CHAIN if _covers(m, e)]
    assert not eager, (
        f"python-mpv now imports {eager} when the module loads; the frozen "
        "build excludes it and would fail at `import mpv`"
    )


def test_the_import_time_scan_tells_eager_from_lazy():
    """Control for the test above: a scanner that saw nothing would pass it."""
    source = (
        "import os\n"
        "try:\n    import PIL\nexcept ImportError:\n    pass\n"
        "class C:\n    from numpy import array\n"
        "def f():\n    from yaml import safe_load\n"
    )
    assert _import_time_imports(source) == {"os", "PIL", "numpy"}
    assert _all_imports(source) == {"os", "PIL", "numpy", "yaml"}
