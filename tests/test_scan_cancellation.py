"""A new library request supersedes work, not merely its folder name."""
import threading
from types import SimpleNamespace

from ax_player import app
from PySide6.QtCore import Qt, QObject, Slot, QCoreApplication, QEvent


def test_relisting_cancels_running_scan_and_drops_queued_scans(tmp_path):
    jobs = []
    cleared = []
    previous = threading.Event()
    window = SimpleNamespace(
        _folder=tmp_path, _recursive=False, _requested_thumbs=set(),
        _sort_mode="name", _scan_signals=object(), _scan_cancel=previous,
        _scan_pool=SimpleNamespace(start=jobs.append, clear=lambda: cleared.append(True)),
    )
    app.AXPlayerWindow.open_folder(window, tmp_path, reload_player=False)
    assert previous.is_set()
    assert cleared == [True]
    assert not window._scan_cancel.is_set()
    assert jobs[0]._cancel is window._scan_cancel


def test_cancelled_result_already_queued_cannot_restart_same_folder(tmp_path):
    cancelled = threading.Event()
    cancelled.set()
    # A stale result must return before accessing any sidebar or player state.
    window = SimpleNamespace(_folder=tmp_path)
    app.AXPlayerWindow._on_folder_scanned(window, str(tmp_path), [], "", True, cancelled)


def test_cancelled_job_never_opens_the_directory(tmp_path, monkeypatch):
    cancelled = threading.Event()
    cancelled.set()
    calls = []
    job = app._ScanJob(tmp_path, False, None, object(), "name", True, cancelled)
    monkeypatch.setattr(app.os, "scandir", lambda _: calls.append(True))
    job.run()
    assert calls == []


def test_recursive_scan_stops_before_visiting_next_subtree(tmp_path, monkeypatch):
    cancelled = threading.Event()
    visited = []

    def walk(*args, **kwargs):
        for index in range(100):
            visited.append(index)
            if index == 1:
                cancelled.set()
            yield str(tmp_path), [], ["clip.mkv"]

    monkeypatch.setattr(app.os, "walk", walk)
    emitted = []
    signals = SimpleNamespace(done=SimpleNamespace(emit=lambda *args: emitted.append(args)))
    job = app._ScanJob(tmp_path, True, None, signals, "name", True, cancelled)
    job.run()
    assert visited == [0, 1]
    assert emitted == []


def test_qt_queued_result_keeps_its_cancel_token(tmp_path, qapp):
    calls = []
    window = SimpleNamespace(
        _folder=tmp_path, _listed=None, _playlist_items=lambda: [],
        sidebar=SimpleNamespace(set_items=lambda *a, **kw: calls.append("sidebar")),
        _queue_all_contact_sheets=lambda: None,
    )
    signals = app._ScanSignals()

    class Receiver(QObject):
        @Slot(str, list, str, bool, object)
        def receive(self, *args):
            app.AXPlayerWindow._on_folder_scanned(window, *args)

    receiver = Receiver()
    signals.done.connect(
        receiver.receive,
        Qt.ConnectionType.QueuedConnection,
    )
    cancelled = threading.Event()
    signals.done.emit(str(tmp_path), [], "", False, cancelled)
    cancelled.set()
    # Dispatch only our receiver's events, not other tests' pending widget
    # events: those widgets may deliberately contain incomplete player fakes.
    QCoreApplication.sendPostedEvents(receiver, QEvent.Type.MetaCall)
    assert calls == []
    signals.done.emit(str(tmp_path), [], "", False, threading.Event())
    QCoreApplication.sendPostedEvents(receiver, QEvent.Type.MetaCall)
    assert calls == ["sidebar"]


def test_cancelled_size_sort_stops_metadata_reads(tmp_path, monkeypatch):
    cancelled = threading.Event()
    reads = []

    def stat(path):
        reads.append(path)
        cancelled.set()
        return SimpleNamespace(st_size=1, st_mtime=1)

    monkeypatch.setattr(type(tmp_path), "stat", stat)
    paths = [tmp_path / f"{index}.mkv" for index in range(100)]
    app._sort_playlist(paths, app.settings.SORT_SIZE, cancelled)
    assert len(reads) == 1
