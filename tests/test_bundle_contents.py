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


# -- Qt binaries the running app never loads --------------------------------
# What a real session loaded from PySide6, measured from the process's module
# list: open a folder, scan, play through a playlist, generate thumbnails and
# contact sheets. Everything here is load-bearing; the spec's UNUSED_QT may
# never touch any of it. Destination paths as PyInstaller writes them.
LOADED_IN_A_REAL_SESSION = (
    "PySide6/Qt6Core.dll",
    "PySide6/Qt6Gui.dll",
    "PySide6/Qt6Widgets.dll",
    "PySide6/QtCore.pyd",
    "PySide6/QtGui.pyd",
    "PySide6/QtWidgets.pyd",
    "PySide6/pyside6.abi3.dll",
    "PySide6/MSVCP140_1.dll",
    "PySide6/MSVCP140_2.dll",
    "PySide6/plugins/platforms/qwindows.dll",
    "PySide6/plugins/styles/qmodernwindowsstyle.dll",
    "PySide6/plugins/imageformats/qgif.dll",
    "PySide6/plugins/imageformats/qicns.dll",
    "PySide6/plugins/imageformats/qico.dll",   # the window icon is icon.ico
    "PySide6/plugins/imageformats/qjpeg.dll",  # every thumbnail and sheet
)


def _spec_tree() -> ast.Module:
    return ast.parse((_repo() / "AXPlayer.spec").read_text(encoding="utf-8"))


def _spec_qt_filter():
    """The spec's own UNUSED_QT and _unused_qt, executed -- not a copy of them."""
    wanted = []
    for node in _spec_tree().body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "UNUSED_QT" for t in node.targets
        ):
            wanted.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name == "_unused_qt":
            wanted.append(node)
    assert len(wanted) == 2, "AXPlayer.spec lost UNUSED_QT or _unused_qt"
    namespace: dict = {}
    exec(compile(ast.Module(body=wanted, type_ignores=[]), "AXPlayer.spec", "exec"), namespace)
    return namespace["UNUSED_QT"], namespace["_unused_qt"]


def test_nothing_a_real_session_loads_is_dropped():
    _prefixes, dropped = _spec_qt_filter()
    hit = [dest for dest in LOADED_IN_A_REAL_SESSION if dropped(dest)]
    assert not hit, f"UNUSED_QT drops what the running app loads: {hit}"
    hit = [dest for dest in LOADED_IN_A_REAL_SESSION if dropped(dest.replace("/", "\\"))]
    assert not hit, f"...and in the Windows spelling: {hit}"


def test_the_filter_reads_the_paths_pyinstaller_actually_writes():
    """On Windows the TOC says PySide6\\opengl32sw.dll, not PySide6/opengl32sw.dll.
    Every other test here spells paths with "/", so a predicate that stopped
    normalising separators would pass them all and drop nothing from a real
    build -- the ~40 MB would quietly come back."""
    _prefixes, dropped = _spec_qt_filter()
    assert dropped("PySide6\\opengl32sw.dll")
    assert dropped("PySide6\\plugins\\platforminputcontexts\\qtvirtualkeyboardplugin.dll")
    assert not dropped("PySide6\\Qt6Widgets.dll")


def test_no_qt_module_the_app_imports_is_dropped():
    """Derived from the source: a new `from PySide6.QtX import ...` anywhere in
    the package makes its .pyd and Qt6X.dll load-bearing, whether or not
    anybody remembers this list exists. Function-level imports count."""
    _prefixes, dropped = _spec_qt_filter()
    shipped = sorted((_repo() / "ax_player").rglob("*.py")) + [_repo() / "packaging" / "launch.py"]
    modules = set()
    for path in shipped:
        for name in _all_imports(path.read_text(encoding="utf-8")):
            parts = name.split(".")
            if parts[0] == "PySide6" and len(parts) > 1 and parts[1].startswith("Qt"):
                modules.add(parts[1])
    assert {"QtCore", "QtGui", "QtWidgets"} <= modules, f"scanned the wrong tree: {modules}"

    hit = []
    for module in sorted(modules):
        suffix = module[2:]  # QtWidgets -> Widgets
        for dest in (f"PySide6/{module}.pyd", f"PySide6/Qt6{suffix}.dll"):
            if dropped(dest):
                hit.append(f"{module}: {dest}")
    assert not hit, "\n".join(["the source uses it, the release would not have it:", *hit])


def test_the_qt_filter_is_actually_applied():
    """The list and the predicate are pinned above; this pins that the spec
    runs them. A helper nobody calls passed every test once already here
    (HANDOFF 9.39)."""
    rebound = set()
    for node in _spec_tree().body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "a"
                and any(isinstance(n, ast.Name) and n.id == "_unused_qt" for n in ast.walk(node.value))
            ):
                rebound.add(target.attr)
    assert rebound >= {"binaries", "datas"}, (
        f"only {sorted(rebound) or 'nothing'} is filtered; the rest of UNUSED_QT still ships"
    )
