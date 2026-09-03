"""What a drop is allowed to do, and what it must refuse.

dnd.py had no tests at all. The gap mattered because the drop path ends in
play_url(), which issues `loadfile replace` -- so anything that reaches it by
accident does not merely fail, it stops playback and empties the playlist.
"""
from __future__ import annotations

import types
from pathlib import Path

import pytest

from ax_player import dnd
from ax_player.app import AXPlayerWindow

# Built rather than written as literals: a backslash in a test string is one
# transcription mistake away from testing something else entirely, and this
# file is entirely about backslashes.
B = chr(92)
WIN_PATH = "C:" + B + "Videos" + B + "ep1.mkv"
UNC_PATH = B + B + "nas" + B + "media" + B + "ep1.mkv"


@pytest.mark.parametrize(
    "text, kind",
    [
        # The bug this closes: ordinary text used to be handed to play_url.
        ("hello world how are you", ""),
        ("看到一半的那部", ""),
        ("www.example.com", ""),  # no scheme -- a hostname is not a URL
        ("", ""),
        ("   ", ""),
        # Real URLs.
        ("https://youtube.com/watch?v=x", dnd.URL),
        ("http://example.com/v.mkv", dnd.URL),
        ("magnet:?xt=urn:btih:abc", dnd.URL),
        # Local files.
        ("file:///C:/Videos/ep1.mkv", dnd.FILE),
        (WIN_PATH, dnd.PATH),
        ("D:/Videos/ep1.mkv", dnd.PATH),
        (UNC_PATH, dnd.PATH),
    ],
)
def test_classify_separates_urls_paths_and_noise(text, kind):
    assert dnd.classify(text)[0] == kind


def test_a_drive_letter_is_not_a_url_scheme():
    """QUrl("C:/Videos/ep1.mkv") reads the drive letter as the scheme, so
    isLocalFile() is False and the old code sent it to play_url as a URL. No
    scheme in practice is one character long; that is what tells them apart."""
    assert dnd.classify(WIN_PATH) == (dnd.PATH, WIN_PATH)
    assert dnd.classify("c:/x.mkv")[0] == dnd.PATH
    # Two characters or more is a real scheme, even an unfamiliar one.
    assert dnd.classify("rtmp://host/stream")[0] == dnd.URL


# -- what uris_from_mime already promised ----------------------------------
class _Mime:
    def __init__(self, urls=None, text=None):
        self._urls = urls
        self._text = text

    def hasUrls(self):  # noqa: N802 - Qt's name
        return bool(self._urls)

    def urls(self):
        return self._urls or []

    def hasText(self):  # noqa: N802
        return self._text is not None

    def text(self):
        return self._text or ""


def test_dragged_file_objects_win_over_text():
    mime = _Mime(urls=[types.SimpleNamespace(toString=lambda: "file:///C:/a.mkv")],
                 text="something else entirely")

    assert dnd.uris_from_mime(mime) == ["file:///C:/a.mkv"]


def test_plain_text_is_the_fallback_and_skips_playlist_comments():
    """A dropped .m3u fragment must not turn its comments into filenames."""
    mime = _Mime(text="#EXTM3U\nhttps://a/1.mkv\n\n# a note\nhttps://a/2.mkv")

    assert dnd.uris_from_mime(mime) == ["https://a/1.mkv", "https://a/2.mkv"]


def test_drag_enter_still_accepts_text_so_a_dragged_link_is_not_refused():
    """has_uris stays permissive on purpose -- dragging a URL as *text* sets
    only text/plain, and rejecting it at dragEnter gives no feedback at all.
    classify() is what makes that safe, by refusing at the drop instead."""
    assert dnd.has_uris(_Mime(text="https://example.com/v.mkv")) is True
    assert dnd.has_uris(_Mime(text="hello")) is True
    assert dnd.has_uris(_Mime()) is False


# -- the drop path as a whole ----------------------------------------------
def _window(tmp_path):
    """Enough of AXPlayerWindow for open_dropped."""
    calls = []
    return types.SimpleNamespace(
        _calls=calls,
        play_url=lambda u: calls.append(("play_url", u)),
        open_folder=lambda p: calls.append(("open_folder", str(p))),
        play=lambda p: calls.append(("play", str(p))),
    ), calls


def test_dropping_stray_text_does_not_touch_playback(tmp_path):
    """The whole point. play_url issues `loadfile replace`, so reaching it with
    a mis-drag of selected text stopped the current file and left the sidebar
    pointing at a playlist mpv no longer had."""
    window, calls = _window(tmp_path)

    AXPlayerWindow.open_dropped(window, ["just some words I dragged"])

    assert calls == [], "stray text reached the player"


def test_dropping_a_url_still_plays_it(tmp_path):
    window, calls = _window(tmp_path)

    AXPlayerWindow.open_dropped(window, ["https://youtube.com/watch?v=x"])

    assert calls == [("play_url", "https://youtube.com/watch?v=x")]


def test_dropping_a_folder_opens_it(tmp_path):
    folder = tmp_path / "series"
    folder.mkdir()
    window, calls = _window(tmp_path)

    AXPlayerWindow.open_dropped(window, [folder.as_uri()])

    assert calls == [("open_folder", str(folder))]


def test_dropping_a_bare_path_as_text_opens_the_file(tmp_path):
    """The other half of the bug: this is a realistic gesture -- a path copied
    out of an address bar or a chat window -- and it used to be handed to
    play_url as though the drive letter were a URL scheme."""
    video = tmp_path / "ep1.mkv"
    video.write_bytes(b"x")
    window, calls = _window(tmp_path)

    AXPlayerWindow.open_dropped(window, [str(video)])

    assert calls == [("play", str(video))]
