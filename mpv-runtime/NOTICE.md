# Bundled components

This folder vendors third-party components so a fresh clone of AX Player
can play video without the user separately installing/configuring mpv.

| Component | Version / commit | License | Source |
|---|---|---|---|
| mpv.exe, libmpv-2.dll | v0.41.0, commit `dd5d17d328`, build 2026-08-09 | **GPLv2+** (see `LICENSES/mpv-GPL-2.0.txt`) | https://github.com/mpv-player/mpv, built by https://github.com/shinchiro/mpv-winbuild-cmake (published via https://sourceforge.net/projects/mpv-player-windows/), fetched by `setup_mpv.py` |
| scripts/uosc/ | vendored from `C:\mpv` install, upstream `main` branch | LGPLv2.1+ (see `LICENSES/uosc-LGPL-2.1.txt`) | https://github.com/tomasklaen/uosc |
| scripts/thumbfast.lua | vendored from `C:\mpv` install, upstream `master` branch | MPL-2.0 (see `LICENSES/thumbfast-MPL-2.0.txt`) | https://github.com/po5/thumbfast |
| fonts/uosc_icons.otf, fonts/uosc_textures.ttf | bundled with uosc above | same as uosc | https://github.com/tomasklaen/uosc |
| yt-dlp.exe | latest release | Unlicense (public domain) | https://github.com/yt-dlp/yt-dlp, fetched by `setup_mpv.py`. Used by mpv's own built-in `ytdl_hook` (not embedded in mpv) to resolve streaming sites for "open URL" playback. |
| shaders/Anime4K_*.glsl (37 files) | vendored from `C:\mpv` install, upstream v4.x | MIT (see `LICENSES/Anime4K-MIT.txt`; the notice is also kept in each `.glsl` header) | https://github.com/bloc97/Anime4K |
| shaders/Anime4K_AutoDownscalePre_x{2,4}.glsl | as above | Unlicense (public domain; notice kept in each file header) | https://github.com/bloc97/Anime4K |

## GPL note -- please read before choosing AX Player's own license

The mpv build fetched by `setup_mpv.py` is licensed **GPLv2+**, not LGPL.
AX Player loads `libmpv-2.dll` in-process via `python-mpv`/ctypes rather
than spawning it as a separate process, which is generally treated as
"linking" for GPL purposes -- unlike LGPL, GPL doesn't carve out an
exception for dynamic linking from a differently-licensed program. In
practice this means the combined work (AX Player + libmpv-2.dll running
together in one process) likely needs to be distributed under
GPL-compatible terms.

**Resolved: AX Player is released under GPLv2+** (see `LICENSE` in the
repository root) -- the first of the options that were open here, chosen
because it needs no build or architecture change and leaves no ambiguity.

Note that the packaged builds do **not** redistribute mpv itself: neither
`mpv.exe` nor `libmpv-2.dll` is inside the exe (see `AXPlayer.spec`), and
`mpv_fetch.py` downloads them to a per-user folder on first launch. So no
GPL binary is being distributed here; the linking question above applies
to the combined work as it runs on the user's machine, which GPLv2+
covers.

The two alternatives, recorded in case they matter later:
- Have `setup_mpv.py` fetch an LGPL-only mpv build instead (mpv can be
  built with `--enable-lgpl`, which excludes some GPL-only optional
  components like certain vf filters) -- would let AX Player relicense.
- Spawn mpv as a *separate process* instead of loading libmpv in-process
  (this is what the standalone `mpv.exe` thumbnail/thumbfast subprocesses
  already do, and process boundaries sidestep the linking question) --
  but that's the embedding architecture change this project deliberately
  avoided for the main playback window.

This file exists so the choice gets made deliberately, not by omission.
