from types import SimpleNamespace

import pytest

from ax_player import app, debug_log


@pytest.mark.parametrize("accepted", [True, False])
def test_url_dialog_does_not_log_credentials_or_tokens(monkeypatch, accepted):
    url = "https://user:secret@example.com/movie?token=private#fragment"
    played = []
    monkeypatch.setattr(app.QInputDialog, "getText", lambda *args: (url, accepted))
    app.AXPlayerWindow.pick_url(SimpleNamespace(play_url=played.append))
    text = debug_log.path().read_text(encoding="utf-8")
    assert "secret" not in text
    assert "private" not in text
    assert "fragment" not in text
    assert played == ([url] if accepted else [])
