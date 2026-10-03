"""One AX window: a second launch hands its file/URL to the first and exits.

Opening three files from Explorer used to mean three processes, three windows
and three GPU decode contexts (HANDOFF §7). The Telegram relay made it daily:
every ▶ opened another AX.

A Windows named pipe from the standard library rather than QLocalServer: that
lives in QtNetwork, which AXPlayer.spec deliberately leaves out of the bundle
(UNUSED_QT). Messages go through send_bytes/recv_bytes -- never send/recv,
which unpickle whatever arrives and would run code from any process that can
open the pipe.
"""

from __future__ import annotations

import getpass
import threading
from multiprocessing.connection import Client, Listener
from pathlib import Path
from typing import Callable

from ax_player import debug_log, dnd

# Not a secret: it only keeps unrelated programs that happen to find the pipe
# from speaking to it by accident. The pipe name is per user, so another
# account's AX is a separate instance.
_AUTHKEY = b"AX Player single instance v1"
_MAX_MESSAGE = 64 * 1024


def pipe_name(user: str | None = None) -> str:
    try:
        user = user or getpass.getuser()
    except Exception:  # noqa: BLE001 -- no user name is not a reason to fail
        user = "default"
    safe = "".join(c if c.isalnum() else "_" for c in user)
    return rf"\\.\pipe\AXPlayer-{safe}"


def normalise_target(target: str) -> str:
    """What the running instance should open.

    Paths are made absolute here, in the launching process: the instance that
    receives them has its own working directory, so a relative argument would
    point somewhere else by the time it arrived. URLs pass through untouched.
    """
    target = (target or "").strip()
    if not target:
        return ""
    kind, text = dnd.classify(target)
    if kind == dnd.URL:
        return text
    try:
        return str(Path(target).resolve())
    except OSError:
        return target


# How long a launch waits for the running AX to take its target. The handshake
# normally takes milliseconds; an AX that never answers (frozen, suspended)
# used to keep the new launch waiting forever -- measured: still blocked when
# killed at 8 s -- which looks exactly like "pressed play, nothing happened".
FORWARD_TIMEOUT = 3.0


def forward(target: str, name: str | None = None, timeout: float = FORWARD_TIMEOUT) -> bool:
    """Hand `target` to a running AX. False when there is none to hand it to.

    Also False when the running one does not answer within `timeout`: the
    caller then opens a window of its own rather than appearing to do nothing.
    The attempt runs on a daemon thread because the handshake has no timeout
    of its own; if it is still stuck, it is simply abandoned.
    """
    payload = normalise_target(target).encode("utf-8")
    result: list[bool] = []

    def attempt() -> None:
        try:
            conn = Client(name or pipe_name(), family="AF_PIPE", authkey=_AUTHKEY)
        except (OSError, EOFError):
            result.append(False)
            return
        try:
            _allow_foreground()
            conn.send_bytes(payload)
            result.append(True)
        except (OSError, EOFError):
            result.append(False)
        finally:
            conn.close()

    worker = threading.Thread(target=attempt, name="ax-forward", daemon=True)
    worker.start()
    worker.join(timeout)
    if worker.is_alive():
        debug_log.log(f"single_instance: running AX did not answer within {timeout:.0f}s, opening a new window")
        return False
    return bool(result and result[0])


def _allow_foreground() -> None:
    """Let the running instance bring its window forward.

    Windows only lets the foreground process hand the foreground on; the
    process the user just launched has it, the one that will show the video
    does not. ASFW_ANY (-1) passes it over.
    """
    try:
        import ctypes

        ctypes.windll.user32.AllowSetForegroundWindow(-1)
    except (AttributeError, OSError):
        pass


class Server:
    """Listens on the pipe in a daemon thread; calls `on_message` with each target."""

    def __init__(self, on_message: Callable[[str], None], name: str | None = None):
        self._on_message = on_message
        # FILE_FLAG_FIRST_PIPE_INSTANCE inside multiprocessing's PipeListener:
        # a second server on the same name raises instead of sharing it.
        self._listener = Listener(name or pipe_name(), family="AF_PIPE", authkey=_AUTHKEY)
        self._closed = False
        self._thread = threading.Thread(target=self._serve, name="ax-single-instance", daemon=True)
        self._thread.start()

    def _serve(self) -> None:
        while not self._closed:
            try:
                conn = self._listener.accept()
            except Exception:  # noqa: BLE001 -- bad handshake, or closing
                if self._closed:
                    return
                continue
            try:
                data = conn.recv_bytes(_MAX_MESSAGE)
                self._on_message(data.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001 -- one bad client must not stop the server
                debug_log.log_exc("single_instance: message FAILED")
            finally:
                conn.close()

    def close(self) -> None:
        self._closed = True
        try:
            self._listener.close()
        except OSError:
            pass


def serve(on_message: Callable[[str], None], name: str | None = None) -> Server | None:
    """Become the instance others hand off to; None if someone else already is."""
    try:
        return Server(on_message, name)
    except OSError:
        debug_log.log("single_instance: pipe already owned, running as a separate window")
        return None
