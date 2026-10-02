"""What the command line may open: a file, a folder, or -- since the Telegram
relay launches AX with one -- a URL.

open_launch_target() is driven with a recording stand-in for the window, so
these tests never build an AXPlayerWindow or reach libmpv.
"""
from __future__ import annotations

from ax_player.app import open_launch_target


class RecordingWindow:
    def __init__(self):
        self.calls = []

    def play_url(self, url):
        self.calls.append(("play_url", url))

    def play(self, path):
        self.calls.append(("play", path))

    def open_folder(self, path):
        self.calls.append(("open_folder", path))


def test_url_goes_to_play_url():
    w = RecordingWindow()
    url = "http://127.0.0.1:9888/t.me/c/4344549722/28047"
    open_launch_target(w, url)
    # Before: Path(url) was neither file nor folder, and nothing played.
    assert w.calls == [("play_url", url)]


def test_file_and_folder_unchanged(tmp_path):
    video = tmp_path / "第02話.mkv"
    video.write_bytes(b"")
    w = RecordingWindow()
    open_launch_target(w, str(video))
    open_launch_target(w, str(tmp_path))
    assert w.calls == [("play", video), ("open_folder", tmp_path)]


def test_drive_letter_path_is_not_a_url(tmp_path):
    # "C:\\..." has a one-letter scheme; the window must not loadfile it as a
    # URL. Missing on disk, it is simply ignored, as before.
    w = RecordingWindow()
    open_launch_target(w, str(tmp_path / "missing.mkv"))
    assert w.calls == []


def test_unrecognised_text_is_ignored():
    w = RecordingWindow()
    open_launch_target(w, "not a path or a url")
    assert w.calls == []
