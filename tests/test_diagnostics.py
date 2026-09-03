"""The GPU telemetry job, which had no tests at all.

query_gpu() is deliberately total -- it answers {} for every non-NVIDIA or
missing-tool setup rather than raising, because the panel still has mpv's own
numbers to show. GpuQueryJob is the part that runs it on _thumb_pool, and the
teardown rule for everything on that pool lives in app._emit_safely.
"""
import shiboken6

from ax_player import diagnostics


def test_a_gpu_sample_survives_the_window_closing_under_it(qapp, monkeypatch):
    """Every other job on _thumb_pool emits through app._emit_safely; this one
    emitted directly, and was the only worker left unguarded when v1.1.7 fixed
    the rest.

    Closing the window destroys GpuSignals while a job may already be on a
    thread -- closeEvent's pool clear() drops only what has not started -- and
    the emit then raises "Signal source has been deleted" straight out of
    run(), where nothing catches it. The C++ object is deleted explicitly here
    rather than by racing a real close, because the question is only what
    run() does once its signals object is gone.
    """
    monkeypatch.setattr(diagnostics, "query_gpu", lambda: {"gpu_util": 1.0})
    signals = diagnostics.GpuSignals()
    job = diagnostics.GpuQueryJob(signals)
    shiboken6.delete(signals)  # what the window's teardown does

    job.run()  # must not raise


def test_a_gpu_sample_still_reaches_a_live_panel(qapp, monkeypatch):
    """The other half: guarding the emit must not swallow the working case.

    A guard that returned early, or one applied to the wrong object, would
    leave the panel showing mpv's numbers and a permanently blank GPU row --
    which looks exactly like a machine with no nvidia-smi, so nothing would
    ever report it.
    """
    sample = {"gpu_util": 12.0, "decoder_util": 3.0, "vram_used": 1024.0,
              "vram_total": 16384.0, "temperature": 41.0}
    monkeypatch.setattr(diagnostics, "query_gpu", lambda: sample)
    signals = diagnostics.GpuSignals()
    received: list[dict] = []
    signals.ready.connect(received.append)

    diagnostics.GpuQueryJob(signals).run()

    assert received == [sample], "the sample never reached the panel"


def test_one_unsupported_field_does_not_cost_every_reading(monkeypatch):
    """All five fields are asked for in one nvidia-smi call, so an unsupported
    one fails the whole query and the panel goes blank rather than partial.

    Pinned because it is invisible when it happens: verified against this
    machine's own nvidia-smi, the query returns "0, 0, 9252, 16303, 38" and
    exit 0, so utilization.decoder is a real field. A future field that is not
    would take the other four down with it.
    """
    assert "utilization.decoder" in diagnostics._QUERY

    class _Result:
        stdout = "0, 0, 9252, 16303, 38"

    monkeypatch.setattr(diagnostics.subprocess, "run", lambda *a, **k: _Result())
    assert diagnostics.query_gpu() == {
        "gpu_util": 0.0, "decoder_util": 0.0,
        "vram_used": 9252.0, "vram_total": 16303.0, "temperature": 38.0,
    }


def test_a_missing_nvidia_smi_is_an_empty_sample_not_an_exception(monkeypatch):
    """A worker thread has nowhere to put an exception, and the panel is meant
    to keep working on a machine that simply has no NVIDIA GPU."""
    def _boom(*args, **kwargs):
        raise FileNotFoundError("nvidia-smi")

    monkeypatch.setattr(diagnostics.subprocess, "run", _boom)
    assert diagnostics.query_gpu() == {}
