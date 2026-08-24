# -*- mode: python ; coding: utf-8 -*-

datas = [
    ("ax_player/resources", "ax_player/resources"),
    # Only the small, stable mpv-runtime pieces -- NOT mpv.exe/libmpv-2.dll
    # (large, change often; fetched into a writable per-user folder on
    # first launch instead, see ax_player/mpv_fetch.py).
    ("mpv-runtime/scripts", "mpv-runtime/scripts"),
    ("mpv-runtime/fonts", "mpv-runtime/fonts"),
    ("mpv-runtime/script-opts", "mpv-runtime/script-opts"),
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

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="AXPlayer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon="ax_player/resources/icon.ico",
)

# --onedir: no per-launch extraction to %TEMP% (that's what --onefile was
# paying for on every single startup, not just the first).
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="AXPlayer",
)
