"""What a drop actually carries.

Both drop targets -- the window itself and the mpv surface inside it -- need
the same answer, and had the same fifteen lines and the same paragraph of
comment each. A drop on the sidebar propagates up to the window, a drop on
the video lands on PlayerWidget, and neither should read a dragged link
differently from the other.
"""

from __future__ import annotations

import re

# A URI scheme per RFC 3986: a letter, then letters/digits/+/-/. up to the colon.
_SCHEME = re.compile(r"^([A-Za-z][A-Za-z0-9+.\-]*):")

FILE = "file"
PATH = "path"
URL = "url"


def classify(uri: str) -> tuple[str, str]:
    """What a dropped string actually is, as (kind, text).

    Kind is FILE (a file:// URL Qt should convert), PATH (a Windows path to use
    as-is), URL (something to hand to mpv's ytdl_hook), or "" for a string that
    is none of those and must be ignored.

    That last case is the point. Accepting any text at all -- which is what
    has_uris() does, deliberately, so a dragged URL in plain text is not
    silently rejected -- means a stray drag of ordinary selected text used to
    reach play_url(), and play_url issues `loadfile replace`: a mis-drag of the
    words from a chat window stopped whatever was playing and emptied the
    playlist.

    A bare Windows path dragged as text was misrouted the same way, for a
    subtler reason: QUrl("C:/Videos/ep1.mkv") parses the drive letter as the
    scheme, so isLocalFile() is False and it went to play_url as a URL. A
    single-character scheme is a drive letter -- no scheme in practice is one
    letter long -- which is what separates the two.
    """
    text = (uri or "").strip()
    if not text:
        return ("", "")
    # UNC share: \\server\share\file.mkv. No scheme, but unambiguously a path.
    if text.startswith("\\\\"):
        return (PATH, text)
    match = _SCHEME.match(text)
    if match is None:
        # No scheme at all: not a URL, and too ambiguous to treat as a path --
        # it is as likely to be a sentence as a filename.
        return ("", "")
    scheme = match.group(1).lower()
    if scheme == FILE:
        return (FILE, text)
    if len(scheme) == 1:
        return (PATH, text)
    return (URL, text)


def uris_from_mime(mime) -> list[str]:
    """The dropped URIs, from whichever mime type actually carries them.

    A real dragged hyperlink (from a browser, say) sets text/uri-list, which
    QMimeData.hasUrls()/.urls() reads. Dragging plain URL *text* -- selected
    text rather than a link object, from a chat window or an address bar --
    usually only sets text/plain, which hasUrls() ignores entirely, so the
    drag would be rejected with no feedback at all. Falls back to parsing the
    text as one URL per line, skipping '#' comment lines so a dropped .m3u
    fragment does not turn its comments into filenames.
    """
    if mime.hasUrls():
        return [url.toString() for url in mime.urls()]
    if mime.hasText():
        return [
            line.strip()
            for line in mime.text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
    return []


def has_uris(mime) -> bool:
    """Whether a dragEnter/dragMove should accept this at all."""
    return bool(mime.hasUrls() or mime.hasText())
