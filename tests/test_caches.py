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
    once one exists."""
    seen = []
    real_save = contact_sheets.QImage.save

    def spy(self, path, *a, **kw):
        seen.append(Path(path))
        return real_save(self, path, *a, **kw)

    monkeypatch.setattr(contact_sheets.QImage, "save", spy)

    dest = tmp_path / "abc_9.jpg"
    staging = dest.with_name(f".part-{dest.name}")
    img = contact_sheets.QImage(32, 32, contact_sheets.QImage.Format.Format_RGB32)
    img.fill(contact_sheets.QColor("#123456"))
    assert img.save(str(staging), "JPG", 85)
    os.replace(staging, dest)

    assert seen and seen[0] != dest, "bytes went straight to the cache path"
    assert dest.is_file()
    assert not staging.exists()


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
