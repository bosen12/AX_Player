# AX Player

Windows desktop video player: a PySide6 shell around **embedded libmpv**. The
philosophy is stated in the README and is load-bearing — mpv already does
playback well, so this app adds only what mpv lacks: window chrome, a
folder-based library sidebar with thumbnails, watch-progress tracking, and
drag-and-drop. Every *playback* control (progress bar, hover previews,
subtitle/audio menus) comes from the vendored **uosc** and **thumbfast**
scripts drawing onto the video surface.

**Do not reimplement anything mpv or uosc already provides.** Proposals that
add a playback UI are almost always wrong here.

GPLv2+, because libmpv is loaded in-process. The README reasons through the
linking question; don't change the license casually.

## Read HANDOFF.md before proposing anything

`HANDOFF.md` is a 476-line engineering journal, and it covers **both this repo
and Fluid_Motion_Player**. It is not a changelog — it is a record of what has
already been investigated, measured, and *rejected*, with the evidence:

- 「量過之後撤回的『效能問題』」 — perf items that were listed on intuition and
  withdrawn after measurement. That section says, in as many words,
  「留著是為了不要有人再列一次」.
- 「查過、判斷不值得動」 and §8.4 — investigated, reasons given for not acting.
- 「這一輪查過、故意沒做的」 — deliberately deferred, with scope notes.
- §8.5 — open decisions waiting on the owner. Don't decide these unilaterally.

Two traps that have actually caught reviewers of this repo:

1. **Transcribing those lists back as new findings.** If you "discover"
   something, check it against HANDOFF first and label it honestly.
2. **Attributing symbols to the wrong repo.** HANDOFF discusses both projects,
   so `snapshot_playback`, `est_matrix`, `resolve_multi`, `watcher.py` and
   `inject.py` are **Fluid Motion's**, not this repo's. Grep before you
   attribute anything you first read about in HANDOFF prose.

§5 records the methodology this repo holds itself to. The ones that bite most
often: measure before claiming a performance problem; a retraction needs as
much evidence as the claim did; and confirm a fix actually *executes* before
calling it fixed.

## Commands

```bat
py -3.10 -m pytest tests -q
```

Use `py -3.10` explicitly. Plain `python -m pytest` picks up 3.12 here, which
has no pytest — and a subprocess quietly exiting non-zero for that reason once
made an entire mutation-testing round report false results (§7).
`py -3.14` also has the full test and build environment.

- Run from source: `run.bat` (installs deps, fetches mpv if needed, launches)
- Build: `build.bat` → onedir; `build.bat onefile` → single portable exe
- After any round that ran tests: `Get-Process mpv | Stop-Process -Force`

`build.bat` requires `py -3.14` explicitly; it does not fall back to an
unversioned interpreter. That is the interpreter releases have been built
with. Building on 3.10 produces a visibly smaller, different bundle.

## Testing discipline

Every fix gets a regression test, and **every test is mutation-verified**:
revert the fix, confirm the new test goes red, restore it. Run the unmutated
control first so you know the harness reports PASS at all.

A test that passes for the wrong reason is worse than a missing one. Two real
examples live in the history: a contact-sheet test that never called the
function it claimed to cover (it asserted over its own `img.save` line), and a
`build.bat` test that read a cwd-relative path and so opened a *different
repo's* file. Anchor reads through `Path(module.__file__)` or `tmp_path`, never
the cwd.

`tests/conftest.py` redirects `LOCALAPPDATA` per test. Without it the suite
prunes and rewrites the real user's thumbnail cache — which has happened.

## Layout

- `ax_player/app.py` — `AXPlayerWindow`: window, folder scan, playlist,
  thumbnail/contact-sheet job queues
- `ax_player/ui.py` — pure Qt widgets: titlebar, sidebar, row delegate, popup,
  diagnostics panel. The largest file; the sidebar list is delegate-rendered
  rather than one widget per row, for large folders.
- `ax_player/player_widget.py` — libmpv embedding and event forwarding
- `ax_player/contact_sheets.py`, `thumbnails.py`, `cache.py` — frame grabbing
  and the on-disk caches
- `ax_player/resume.py` — watch progress (`WATCHED_THRESHOLD` lives here; don't
  re-hardcode 0.95)
- `mpv-runtime/` — vendored mpv config, uosc, thumbfast, shaders, fonts.
  `mpv.exe` / `libmpv-2.dll` are gitignored and fetched on demand.
- `docs/` — the published GitHub Pages site, not developer docs

## Traps that cost time here

- **`QMenu.exec` cannot be stubbed from Python.** A test that reaches it parks
  on a real modal menu. Split the decision out of the show path — see
  `Sidebar._menu_target` and `build_row_menu`.
- **Bash heredocs eat backslashes in this environment.** Write files containing
  them (Lua, Python, `.bat`) with the Write/Edit tools instead.
- **`ctypes` treats HWND as 32-bit by default.** `SetWindowPos` fails silently
  on a 64-bit handle unless you set `argtypes`.
- **`QImage.save()` signals disk-full / permission failure by returning
  `False`, not by raising.** An `except OSError` alone misses it.
- **mpv's wid-embedded child window is `WS_DISABLED` on Windows** (upstream mpv
  #6762), so Qt forwards mouse and keyboard to mpv by hand. That forwarding is
  not incidental complexity.
- **`thumbfast.lua` is a vendored patch.** Updating it means reapplying three
  hand-made changes, marked `-- AX Player patch:`, in **both**
  `mpv-runtime/scripts/` and `C:\mpv\scripts\`.

## Releases

There is **no version constant anywhere** — versions are git tags only. Tag,
push the tag, then `gh release create` with two assets: `AXPlayer-onedir.zip`
and `AXPlayer.exe` (the onefile build). Release titles follow
`AX Player vX.Y.Z`.

One thing does carry a version by hand: the `ver-chip` span in
`docs/index.html`, which is the offline fallback for the number `docs/app.js`
normally fetches from the GitHub API. **Bump it when you tag** — it was two
releases behind before anyone looked. No test pins it here, because there is no
version constant to pin it *to*; Fluid Motion's equivalent is tied to
`__version__` in `test_public_surfaces.py`.

The distribution copy the owner keeps lives at `C:\AX_Player`
(`onedir/`, `onefile/`, `release/`, plus `README.md`, `NOTICE.md`,
`LICENSES/`, `版本說明.txt`).

## Conventions

- UI copy and commit messages describing user-facing behaviour are Traditional
  Chinese; code, comments and identifiers are English.
- Comments explain **why**, especially why a constant has its value or why an
  obvious-looking alternative was rejected. Match that density — it is the main
  reason this codebase is navigable.
- Sort filenames with `natural_key()`; this app points at episode folders,
  where lexicographic order puts 第10話 before 第2話.
