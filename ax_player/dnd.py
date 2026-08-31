"""What a drop actually carries.

Both drop targets -- the window itself and the mpv surface inside it -- need
the same answer, and had the same fifteen lines and the same paragraph of
comment each. A drop on the sidebar propagates up to the window, a drop on
the video lands on PlayerWidget, and neither should read a dragged link
differently from the other.
"""

from __future__ import annotations


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
