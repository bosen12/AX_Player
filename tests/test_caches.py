"""Regression cover for the on-disk caches and the diagnostic log."""
import os
import time
from pathlib import Path

from ax_player import cache, contact_sheets, debug_log
from ax_player.paths import app_data_dir


def test_the_cache_key_follows_the_files_content_not_just_its_name(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"a" * 100)
    first = cache.cache_key(video)
    video.write_bytes(b"b" * 200)
    assert cache.cache_key(video) != first, "a recut under the same name reused the old image"


def test_prune_removes_an_abandoned_scratch_dir_but_not_a_live_one(tmp_path):
    """The frame grabbers clean theirs up in a finally, but a process killed
    mid-grab cannot -- and prune_cache only ever looked at files, so what they
    left was invisible to the size cap as well as to eviction. Eight of them
    were found in the live cache holding 48 orphaned frames."""
    (tmp_path / "keep.jpg").write_bytes(b"x" * 100)

    live = tmp_path / ".tmp-inprogress"
    live.mkdir()
    (live / "00001.jpg").write_bytes(b"y" * 100)

    abandoned = tmp_path / "legacy-scratch"
    abandoned.mkdir()
    (abandoned / "00001.jpg").write_bytes(b"z" * 100)
    old = time.time() - cache.SCRATCH_MAX_AGE - 60
    os.utime(abandoned, (old, old))

    cache.prune_cache(tmp_path)

    names = sorted(p.name for p in tmp_path.iterdir())
    assert "keep.jpg" in names
    assert ".tmp-inprogress" in names, "deleted a grab that is still running"
    assert "legacy-scratch" not in names, "kept an abandoned scratch dir"


def test_prune_evicts_by_size_and_leaves_the_cache_under_the_cap(tmp_path):
    for i in range(10):
        f = tmp_path / f"{i:02d}.jpg"
        f.write_bytes(b"x" * 1000)
        stamp = time.time() - (10 - i) * 60  # 00 oldest
        os.utime(f, (stamp, stamp))
    cache.prune_cache(tmp_path, max_bytes=5000)
    total = sum(p.stat().st_size for p in tmp_path.iterdir())
    assert total <= 5000
    assert not (tmp_path / "00.jpg").exists(), "kept the least recently used"
    assert (tmp_path / "09.jpg").exists(), "evicted the most recently used"


def test_sheets_from_a_retired_grid_size_are_dropped():
    """The filename carries the frame count and lookups only ever ask for the
    current one, so a _12.jpg from the old 4x3 grid could never be read again
    -- it just competed for the size cap. 19 were still in the live cache."""
    directory = contact_sheets.contact_sheet_cache_dir()
    current = directory / f"abc_{contact_sheets.FRAME_COUNT}.jpg"
    retired = directory / "abc_12.jpg"
    unrelated = directory / "notasheet.jpg"
    for f in (current, retired, unrelated):
        f.write_bytes(b"x" * 10)

    contact_sheets.prune_contact_sheet_cache()

    assert current.exists(), "deleted a sheet at the current grid size"
    assert not retired.exists(), "kept a sheet no lookup can reach"
    assert unrelated.exists(), "deleted a file it could not identify"


def test_a_sheet_is_never_written_straight_onto_its_cache_path(tmp_path, monkeypatch):
    """Saving onto dest leaves a window where a half-written JPEG is on disk,
    and it passes the "exists and is non-empty" check -- so that broken image
    is served for every hover from then on, since nothing revisits a sheet
    once one exists.

    The version this replaces never called generate_contact_sheet at all: it
    installed the spy, then did its own img.save(staging) and asserted the spy
    had seen `staging`. That is a tautology over the test's own line -- putting
    `sheet.save(str(dest))` back in contact_sheets.py left it green, so the
    only cover for the v1.1.6 fix was cover for nothing.
    """
    video = tmp_path / "clip.mkv"
    video.write_bytes(b"x" * 64)

    real_save = contact_sheets.QImage.save
    seen: list[Path] = []

    def fake_grab(_video, _first, _step, count, tmp_dir):
        """Real JPEGs on disk, written through the unpatched save so the
        frames the composer reads do not show up as sheet writes."""
        made = []
        for i in range(count):
            frame = Path(tmp_dir) / f"f{i:02d}.jpg"
            image = contact_sheets.QImage(160, 90, contact_sheets.QImage.Format.Format_RGB32)
            image.fill(contact_sheets.QColor("#334455"))
            assert real_save(image, str(frame), "JPG", 85)
            made.append(frame)
        return made

    def spy(self, path, *a, **kw):
        seen.append(Path(path))
        return real_save(self, path, *a, **kw)

    monkeypatch.setattr(contact_sheets, "probe_duration", lambda _v: 120.0)
    monkeypatch.setattr(contact_sheets, "_grab_evenly_spaced", fake_grab)
    monkeypatch.setattr(contact_sheets.QImage, "save", spy)

    dest = contact_sheets.generate_contact_sheet(video)

    assert dest is not None, "the sheet was not produced at all"
    assert dest.is_file() and dest.stat().st_size > 0
    assert seen, "the composed sheet was never saved"
    assert dest not in seen, "bytes went straight to the cache path"
    assert seen[-1].name.startswith(".part-"), f"unexpected staging name: {seen[-1].name}"
    assert not seen[-1].exists(), "staging file left behind"


def test_debug_log_rotates_and_keeps_one_generation(monkeypatch):
    """It only grows -- mpv's warn/error stream feeds it, and one noisy script
    added 1275 lines in a session. Unbounded it defeats its own purpose: it is
    the only diagnostic channel a console=False build has."""
    monkeypatch.setattr(debug_log, "MAX_BYTES", 2048)
    for i in range(400):
        debug_log.log("filler %04d padded out so this rotates within the test" % i)

    live = debug_log.path()
    previous = live.with_name(live.name + ".1")
    assert previous.is_file(), "no previous generation kept"
    assert live.stat().st_size < debug_log.MAX_BYTES * 2, "live file grew past the cap"
    assert "filler 0399" in live.read_text(encoding="utf-8"), "newest line lost"


def test_the_suite_never_touches_the_real_cache():
    """Guards the conftest fixture itself."""
    assert "Temp" in str(app_data_dir()) or "tmp" in str(app_data_dir()).lower()


def test_an_unchanged_position_is_not_written_again(monkeypatch):
    """The 5-second progress poll fires whether or not playback advanced, so a
    paused player rewrote the whole database -- byte for byte identical -- 12
    times a minute for as long as it sat there.

    Counted by intercepting the swap rather than by looking at the file's size
    or mtime: stat() on this filesystem reports values minutes out of date
    (see HANDOFF 1.2), so a size/mtime comparison cannot answer this.
    """
    from ax_player import resume

    swaps = []
    real_replace = resume.os.replace
    monkeypatch.setattr(
        resume.os, "replace", lambda src, dst: (swaps.append(dst), real_replace(src, dst))[1]
    )

    resume.save_progress(r"C:\V\a.mkv", 120.0, 1440.0)
    assert len(swaps) == 1, "the first write has to happen"

    resume.save_progress(r"C:\V\a.mkv", 120.0, 1440.0)
    assert len(swaps) == 1, "an identical sample rewrote the whole database"

    resume.save_progress(r"C:\V\a.mkv", 125.0, 1440.0)
    assert len(swaps) == 2, "a real move forward stopped being recorded"

    assert resume.get_progress(r"C:\V\a.mkv")["pos"] == 125.0


def test_a_leftover_directory_does_not_abort_the_scratch_sweep(tmp_path):
    """Both frame grabbers had their own copy of a sweep that could not survive
    one unexpected entry.

    Measured on Windows: unlink() on a directory raises PermissionError
    (WinError 5), and with a single try around the whole loop that one entry
    aborted the sweep *and* skipped the rmdir -- so the scratch directory and
    everything beside it leaked until _drop_stale_scratch reached it an hour
    later. contact_sheets was fixed and thumbnails was not; the helper is
    shared now so neither can drift again.
    """
    from ax_player.cache import clear_scratch

    scratch = tmp_path / ".tmp-abc-1234"
    scratch.mkdir()
    # A leftover subdirectory, which is what a fallback grab can leave behind,
    # sorted first so it is hit before the frames.
    (scratch / "-fallback").mkdir()
    (scratch / "-fallback" / "00.jpg").write_bytes(b"x")
    (scratch / "frame.jpg").write_bytes(b"x")

    clear_scratch(scratch)

    assert not scratch.exists(), "the scratch directory leaked"


def test_clearing_scratch_survives_an_already_gone_directory(tmp_path):
    """It runs in a finally, so it has to be safe on every path out --
    including one where the grab never created the directory at all."""
    from ax_player.cache import clear_scratch

    clear_scratch(tmp_path / "never-existed")  # must not raise


def test_a_second_ax_player_does_not_erase_the_first_ones_progress():
    """Each process holds the whole database in memory and writes all of it
    back, so the last writer used to replace the others' entries wholesale.

    Measured with three real processes saving 400 videos each: 792 of 1200
    writes lost, down to 5 with the merge. Not contrived -- opening three files
    from Explorer is three processes (HANDOFF §7: no single-instance handover),
    each polling every five seconds, so two windows watching two episodes meant
    one of them silently recorded nothing.

    Simulated here by writing the other process's entry straight to disk, which
    is exactly what this process cannot see: its own _cache was loaded before
    that entry existed.
    """
    import json

    from ax_player import resume
    from ax_player.paths import resume_db_path

    resume.save_progress(r"C:\V\mine.mkv", 100.0, 1440.0)

    # Another AX Player writes its own episode while this one is running.
    path = resume_db_path()
    other = json.loads(path.read_text(encoding="utf-8"))
    other[r"C:\V\theirs.mkv"] = {"pos": 55.0, "duration": 1440.0, "watched": False}
    path.write_text(json.dumps(other), encoding="utf-8")

    # This process saves again, from a cache that never saw theirs.
    resume.save_progress(r"C:\V\mine.mkv", 200.0, 1440.0)

    final = json.loads(path.read_text(encoding="utf-8"))
    assert final[r"C:\V\mine.mkv"]["pos"] == 200.0, "our own update has to win"
    assert r"C:\V\theirs.mkv" in final, "the other player's episode was erased"
    assert final[r"C:\V\theirs.mkv"]["pos"] == 55.0


def test_the_temp_file_is_per_process():
    """A bare resume.json.tmp is picked by every concurrent process, so one can
    truncate the file another is mid-write to and then os.replace a
    half-written database over the real one -- the exact failure the atomic
    write exists to prevent. Fluid Motion's save_settings has always keyed its
    temp name by pid."""
    import os

    from ax_player import resume
    from ax_player.paths import resume_db_path

    seen = []
    real_replace = resume.os.replace
    monkeypatch_target = resume.os
    original = monkeypatch_target.replace
    try:
        monkeypatch_target.replace = lambda src, dst: (seen.append(str(src)), real_replace(src, dst))[1]
        resume.save_progress(r"C:\V\a.mkv", 10.0, 1440.0)
    finally:
        monkeypatch_target.replace = original

    assert seen, "nothing was swapped in"
    assert str(os.getpid()) in seen[0], f"temp name is not per-process: {seen[0]}"
    assert not list(resume_db_path().parent.glob("*.tmp")), "temp file left behind"


# -- two decisions a mutation sweep found nothing pinning --------------------
def test_the_watched_cutoff_is_one_constant_and_both_sides_use_it():
    """CLAUDE.md: "WATCHED_THRESHOLD lives here; don't re-hardcode 0.95".

    Two places decide "watched": resume.save_progress writes the flag, and
    ui.set_progress paints the badge from the same ratio. A copy of the literal
    in either one drifts silently -- the store and the row would disagree about
    the same video, and the only symptom is a tick that does not match the list
    filter.

    Pinned on the *boundary the constant produces*, not on 0.95, so moving the
    threshold deliberately stays green and hard-coding a second copy does not.
    """
    from ax_player import resume, ui

    threshold = resume.WATCHED_THRESHOLD
    duration = 1000.0
    just_under = duration * threshold - 1
    just_over = duration * threshold + 1

    resume.save_progress(r"C:\V\under.mkv", just_under, duration)
    resume.save_progress(r"C:\V\over.mkv", just_over, duration)
    assert resume.get_progress(r"C:\V\under.mkv")["watched"] is False
    assert resume.get_progress(r"C:\V\over.mkv")["watched"] is True

    # set_progress is the sidebar half of the same decision, and it has to be
    # reading the constant rather than a literal of its own. Scoped to that
    # method: ui.py has an unrelated 0.95 in the diagnostics verdict (output
    # fps against source fps), and asserting over the whole file matched it.
    ui_src = Path(ui.__file__).read_text(encoding="utf-8")
    start = ui_src.index("def set_progress")
    body = ui_src[start : ui_src.index(chr(10) + "    def ", start + 1)]
    assert "resume.WATCHED_THRESHOLD" in body, "the sidebar decides watched on its own"
    assert "0.95" not in body, "a second copy of the cutoff is back in set_progress"


def test_the_thumbnail_seek_is_a_fraction_of_the_file_not_a_fixed_time():
    """§7 measured this one: a fixed three seconds lands on the studio logo, a
    black frame, or the first bar of an OP -- which is what whole folders of
    the sidebar were showing.

    A percentage is also inside the file *by construction*, which is what makes
    the second pass a real fallback: the frame-0 retry stops running for every
    clip shorter than the old fixed seek and only runs when mpv could not work
    out a duration at all.

    So the property pinned here is "a fraction", not the digits. Moving it to
    15% is a decision and stays green; going back to a wall-clock offset is the
    regression and does not.
    """
    from ax_player import thumbnails

    assert thumbnails.THUMB_SEEK.endswith("%"), (
        f"THUMB_SEEK is {thumbnails.THUMB_SEEK!r}, a fixed offset again"
    )
    assert 0 < float(thumbnails.THUMB_SEEK.rstrip("%")) < 100

    src = Path(thumbnails.__file__).read_text(encoding="utf-8")
    start = src.index("for seek in (")
    order = src[start : src.index(")", start)]
    assert "THUMB_SEEK" in order and order.index("THUMB_SEEK") < order.index('"00:00:00"'), (
        "the percentage has to be tried first; frame 0 is the fallback"
    )
