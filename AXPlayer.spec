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
pyz = PYZ(a.pure)

# Both layouts are built from this one spec so the lists above can't drift
# apart between them. Measured difference on this machine, click to window:
# onedir ~2.0s, onefile ~3.6s -- onefile re-extracts the whole archive to
# %TEMP% on every launch, which is what that extra time is. onedir is the
# default; onefile stays available because a single portable file is worth
# something when you just want to drop it somewhere.
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
