# -*- mode: python ; coding: utf-8 -*-
import os

datas = [
    ("ax_player/resources", "ax_player/resources"),
    # Only the small, stable mpv-runtime pieces -- NOT mpv.exe/libmpv-2.dll
    # (large, change often; fetched into a writable per-user folder on
    # first launch instead, see ax_player/mpv_fetch.py).
    ("mpv-runtime/scripts", "mpv-runtime/scripts"),
    ("mpv-runtime/fonts", "mpv-runtime/fonts"),
    ("mpv-runtime/script-opts", "mpv-runtime/script-opts"),
    # Anime4K: ~2.4MB of plain GLSL text, off until a key is pressed.
    ("mpv-runtime/shaders", "mpv-runtime/shaders"),
    ("mpv-runtime/mpv.conf", "mpv-runtime"),
    ("mpv-runtime/input.conf", "mpv-runtime"),
    ("mpv-runtime/NOTICE.md", "mpv-runtime"),
    ("mpv-runtime/LICENSES", "mpv-runtime/LICENSES"),
]

hiddenimports = [
    "ax_player",
    "ax_player.app",
    "ax_player.debug_log",
    "ax_player.paths",
    "ax_player.player_widget",
    "ax_player.resume",
    "ax_player.thumbnails",
    "ax_player.ui",
    "ax_player.mpv_fetch",
    "mpv",
]

# The UI is plain QtWidgets now. Nothing pulls QtWebEngine in any more, but
# PyInstaller's PySide6 hook still ships it (and its ~150MB Chromium payload,
# plus QtQuick/QtQml/QtPositioning behind it) whenever the module is present
# in the environment -- so exclude it explicitly.
excludes = [
    "pytest",
    "unittest",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQml",
    "PySide6.QtPositioning",
    # python-mpv imports PIL inside two methods this app never calls
    # (MPV.screenshot_raw and ImageOverlay.update), and PyInstaller's static
    # analysis follows imports into function bodies. PIL._typing then imports
    # numpy under `if TYPE_CHECKING:` -- also followed -- and numpy's own
    # submodules drag in psutil (numpy.testing), yaml (numpy.__config__) and
    # charset_normalizer (numpy.f2py). None of it is imported at runtime and
    # none of it is in requirements.txt; it was only here because the build
    # interpreter's site-packages is shared with Fluid Motion. Measured in the
    # v1.3.10 onedir: 39.5 MB of 165 MB (24%), numpy 27.5 and PIL 11.2 of it.
    # Excluding the two roots drops the whole chain. HANDOFF §9.56.
    "PIL",
    "numpy",
]

a = Analysis(
    ["packaging/launch.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# Qt pieces the running app never loads. The PySide6 hook ships them because
# they are *present*, not because anything here asks for them, and a plugin
# brings its whole dependency tree: platforminputcontexts' virtual-keyboard
# plugin alone pulls Qt6VirtualKeyboard -> Qt6Quick -> Qt6Qml/QmlModels/
# OpenGL/Network, and imageformats' qpdf pulls Qt6Pdf. opengl32sw.dll (Mesa's
# software OpenGL, 19.7 MB) has no dependant at all -- the hook adds it on its
# own, for apps that render through Qt OpenGL. This one does not: widgets are
# raster, and mpv draws into a native child window with its own GPU context.
#
# Chosen by measurement, not by name: a real session -- open a folder, scan,
# play, generate thumbnails and contact sheets -- loaded exactly Qt6Core/Gui/
# Widgets and their .pyd, qwindows, qmodernwindowsstyle and the qgif/qicns/
# qico/qjpeg image plugins from PySide6. Nothing below was among them, and the
# code has no SVG, OpenGL, Qt-network, PDF or input-method use (downloads go
# through urllib; the window icon is icon.ico). Everything that *was* loaded
# stays, and so do the small image plugins and translations nobody measured.
# tests/test_bundle_contents.py pins that the two lists never overlap.
UNUSED_QT = (
    "pyside6/opengl32sw.dll",
    "pyside6/qt6virtualkeyboard",
    "pyside6/qt6quick",
    "pyside6/qt6qml",
    "pyside6/qt6opengl",
    "pyside6/qt6pdf",
    "pyside6/qt6network",
    "pyside6/qt6svg",
    "pyside6/qtnetwork.",
    "pyside6/plugins/platforminputcontexts/",
    "pyside6/plugins/tls/",
    "pyside6/plugins/networkinformation/",
    "pyside6/plugins/generic/",
    "pyside6/plugins/iconengines/",
    "pyside6/plugins/imageformats/qpdf",
    "pyside6/plugins/imageformats/qsvg",
    "pyside6/plugins/platforms/qdirect2d",
)


def _unused_qt(dest):
    name = dest.replace("\\", "/").lower()
    return any(name.startswith(prefix) for prefix in UNUSED_QT)


a.binaries = [entry for entry in a.binaries if not _unused_qt(entry[0])]
a.datas = [entry for entry in a.datas if not _unused_qt(entry[0])]
pyz = PYZ(a.pure)

# Both layouts are built from this one spec so the lists above can't drift
# apart between them. Launch to window on this machine, median of five,
# re-measured 09-26 after the trims above: onedir 1.06s, onefile 1.53s
# (v1.3.10's untrimmed onefile: 2.04s). The gap is onefile re-extracting the
# whole archive to %TEMP% on every launch, which is also why every megabyte
# left out above is paid back on each start. onedir is the default; onefile
# stays available because a single portable file is worth something when you
# just want to drop it somewhere.
ONEFILE = os.environ.get("AXPLAYER_ONEFILE") == "1"

common = dict(
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="ax_player/resources/icon.ico",
)

if ONEFILE:
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="AXPlayer",
        upx_exclude=[],
        runtime_tmpdir=None,
        **common,
    )
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="AXPlayer", **common)
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="AXPlayer",
    )
