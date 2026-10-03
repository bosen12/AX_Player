"""A second AX launch hands its target to the first one (single_instance.py).

Every test uses its own random pipe name, so none of them can reach -- or be
reached by -- an AX the person running the suite has open.
"""
from __future__ import annotations

import threading
import uuid
from multiprocessing.connection import Client

import pytest

from ax_player import single_instance
from ax_player.app import receive_handoff


@pytest.fixture
def name():
    return rf"\\.\pipe\AXPlayer-test-{uuid.uuid4().hex}"


@pytest.fixture
def server(name):
    got = []
    arrived = threading.Event()

    def on_message(text):
        got.append(text)
        arrived.set()

    srv = single_instance.serve(on_message, name)
    assert srv is not None
    srv.got, srv.arrived = got, arrived
    yield srv
    srv.close()


def wait(event, timeout=5.0):
    assert event.wait(timeout), "nothing arrived"
    event.clear()


def test_nobody_to_hand_off_to(name):
    assert single_instance.forward("http://127.0.0.1:9888/t.me/x/1", name) is False


def test_url_reaches_the_running_instance(server, name):
    url = "http://127.0.0.1:9888/t.me/c/4344549722/28047?single"
    assert single_instance.forward(url, name) is True
    wait(server.arrived)
    assert server.got == [url]  # untouched: the query is part of what to play


def test_relative_path_is_made_absolute_by_the_sender(server, name, tmp_path, monkeypatch):
    # The receiving instance has its own working directory.
    (tmp_path / "第02話.mkv").write_bytes(b"")
    monkeypatch.chdir(tmp_path)
    assert single_instance.forward("第02話.mkv", name)
    wait(server.arrived)
    assert server.got == [str((tmp_path / "第02話.mkv").resolve())]


def test_plain_launch_just_wakes_the_window(server, name):
    assert single_instance.forward("", name)
    wait(server.arrived)
    assert server.got == [""]


def test_several_handoffs_in_a_row(server, name):
    for n in range(5):
        assert single_instance.forward(f"http://127.0.0.1:9888/t.me/x/{n}", name)
        wait(server.arrived)
    assert server.got == [f"http://127.0.0.1:9888/t.me/x/{n}" for n in range(5)]


def test_second_server_on_the_same_name_steps_aside(server, name):
    assert single_instance.serve(lambda t: None, name) is None


def test_pickled_payload_is_never_unpickled(server, name):
    # recv() would unpickle and so run code from whoever opened the pipe;
    # the server only ever calls recv_bytes().
    conn = Client(name, family="AF_PIPE", authkey=single_instance._AUTHKEY)
    conn.send(("not", "text"))  # pickled on the wire
    conn.close()
    wait(server.arrived)
    assert isinstance(server.got[0], str)


def test_wrong_authkey_is_refused_and_the_server_keeps_going(server, name):
    with pytest.raises(Exception):
        conn = Client(name, family="AF_PIPE", authkey=b"wrong")
        conn.send_bytes(b"x")
    assert single_instance.forward("http://127.0.0.1:9888/t.me/x/9", name)
    wait(server.arrived)
    assert server.got == ["http://127.0.0.1:9888/t.me/x/9"]


def test_pipe_name_is_per_user_and_safe():
    assert single_instance.pipe_name("bo she\\x") == r"\\.\pipe\AXPlayer-bo_she_x"


class RecordingWindow:
    def __init__(self, minimized=False):
        self.calls = []
        self._minimized = minimized

    def isMinimized(self):
        return self._minimized

    def showNormal(self):
        self.calls.append("showNormal")

    def raise_(self):
        self.calls.append("raise")

    def activateWindow(self):
        self.calls.append("activate")

    def play_url(self, url):
        self.calls.append(("play_url", url))

    def play(self, path):
        self.calls.append(("play", path))

    def open_folder(self, path):
        self.calls.append(("open_folder", path))


def test_handoff_brings_the_window_forward_and_plays():
    w = RecordingWindow(minimized=True)
    receive_handoff(w, "http://127.0.0.1:9888/t.me/x/1")
    assert w.calls == ["showNormal", "raise", "activate", ("play_url", "http://127.0.0.1:9888/t.me/x/1")]


def test_empty_handoff_only_wakes():
    w = RecordingWindow()
    receive_handoff(w, "")
    assert w.calls == ["raise", "activate"]


def test_main_hands_off_before_building_anything(monkeypatch):
    from ax_player import app as app_mod

    handed = []
    monkeypatch.setattr(single_instance, "forward", lambda target, name=None: handed.append(target) or True)

    def boom(*a, **k):
        raise AssertionError("a second launch built a QApplication")

    monkeypatch.setattr(app_mod, "QApplication", boom)
    assert app_mod.main(["AXPlayer.exe", "http://127.0.0.1:9888/t.me/x/1"]) == 0
    assert handed == ["http://127.0.0.1:9888/t.me/x/1"]


def test_new_window_flag_skips_the_handoff(monkeypatch):
    from ax_player import app as app_mod

    monkeypatch.setattr(single_instance, "forward", lambda *a, **k: pytest.fail("forwarded despite --new-window"))

    class Stop(Exception):
        pass

    def stop(*a, **k):
        raise Stop

    monkeypatch.setattr(app_mod, "QApplication", stop)
    with pytest.raises(Stop):
        app_mod.main(["AXPlayer.exe", "--new-window", "x.mkv"])


def test_sender_grants_the_foreground(server, name, monkeypatch):
    # Windows lets only the foreground process hand the foreground on, and the
    # launch the user just made is that process -- without the grant the
    # running AX plays the video behind whatever window was on top.
    granted = []
    monkeypatch.setattr(single_instance, "_allow_foreground", lambda: granted.append(True))
    assert single_instance.forward("", name)
    wait(server.arrived)
    assert granted == [True]


def test_a_hung_instance_does_not_hang_the_new_launch(name):
    # A pipe that exists but is never served: what a frozen AX looks like.
    # Before the timeout the second launch waited forever for the handshake --
    # "I pressed play and nothing happened". Now it gives up and the caller
    # opens a window of its own.
    from multiprocessing.connection import Listener
    import time

    hung = Listener(name, family="AF_PIPE", authkey=single_instance._AUTHKEY)  # never accept()s
    try:
        t0 = time.monotonic()
        assert single_instance.forward("http://127.0.0.1:9888/t.me/x/1", name, timeout=0.5) is False
        assert time.monotonic() - t0 < 3
        # The log line is the only trace of why a second window appeared.
        from ax_player import debug_log

        assert "did not answer" in debug_log.path().read_text(encoding="utf-8")
    finally:
        hung.close()
