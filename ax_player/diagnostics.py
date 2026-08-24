"""GPU telemetry for the diagnostics panel.

Separate from PlayerWidget.diagnostics(), which reads mpv's own state
directly and costs nothing. This part shells out to nvidia-smi, which takes
long enough (tens of milliseconds) that it has to happen off the UI thread,
and answers the question mpv cannot: whether the GPU itself is the thing
running out of headroom.
"""

from __future__ import annotations

import subprocess

from PySide6.QtCore import QObject, QRunnable, Signal, Slot

_QUERY = (
    "utilization.gpu",
    "utilization.decoder",
    "memory.used",
    "memory.total",
    "temperature.gpu",
)


class GpuSignals(QObject):
    ready = Signal(dict)  # empty dict when there is no usable nvidia-smi


class GpuQueryJob(QRunnable):
    def __init__(self, signals: GpuSignals):
        super().__init__()
        self._signals = signals

    @Slot()
    def run(self) -> None:
        self._signals.ready.emit(query_gpu())


def query_gpu() -> dict:
    """One nvidia-smi sample, or {} on any non-NVIDIA / missing-tool setup.

    Never raises: the panel treats an empty result as "no GPU telemetry" and
    still shows mpv's own numbers, which are the more important half anyway.
    """
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                f"--query-gpu={','.join(_QUERY)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=4,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return {}
    line = (result.stdout or "").strip().splitlines()
    if not line:
        return {}
    parts = [p.strip() for p in line[0].split(",")]
    if len(parts) < len(_QUERY):
        return {}

    def num(text: str) -> float | None:
        try:
            return float(text)
        except ValueError:
            return None

    return {
        "gpu_util": num(parts[0]),
        "decoder_util": num(parts[1]),
        "vram_used": num(parts[2]),
        "vram_total": num(parts[3]),
        "temperature": num(parts[4]),
    }
