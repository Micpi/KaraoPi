"""Optional HDMI-CEC media-key listener backed by libCEC's ``cec-client``."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable


class CecController:
    """Translate TV remote media keys into KaraoPi playback actions.

    The controller is deliberately optional: on systems without ``cec-client``
    it logs once and remains disabled. If the CEC process disconnects, the
    listener retries automatically until :meth:`stop` is called.
    """

    _KEY_LINE = re.compile(r"key\s+pressed\s*:\s*([^(]+)", re.IGNORECASE)
    _ALIASES = {
        "play": "play",
        "pause": "pause",
        "play pause": "play_pause",
        "pause play": "play_pause",
        "play function": "play",
        "pause function": "pause",
        "pause play function": "play_pause",
        "stop": "stop",
        "stop function": "stop",
        "forward": "next",
        "skip forward": "next",
        "next": "next",
        "backward": "previous",
        "skip backward": "previous",
        "previous": "previous",
    }

    def __init__(
        self,
        on_action: Callable[[str], None],
        *,
        executable: str | None = None,
        reconnect_delay: float = 5.0,
        debounce_seconds: float = 0.35,
    ) -> None:
        self._on_action = on_action
        self._executable = shutil.which("cec-client") if executable is None else executable
        self._reconnect_delay = reconnect_delay
        self._debounce_seconds = debounce_seconds
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[str] | None = None
        self._last_action: str | None = None
        self._last_action_time = 0.0

    @property
    def available(self) -> bool:
        """Whether the libCEC command-line client is installed."""
        return bool(self._executable)

    def start(self) -> bool:
        """Start listening in a daemon thread, returning False when unavailable."""
        if not self.available:
            logging.info("HDMI-CEC controls disabled: cec-client is not installed")
            return False
        if self._thread and self._thread.is_alive():
            return True
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._listen, name="karaopi-cec", daemon=True)
        self._thread.start()
        logging.info("HDMI-CEC media controls enabled")
        return True

    def stop(self) -> None:
        """Stop the listener and its current cec-client process."""
        self._stop_event.set()
        process = self._process
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None
        self._process = None

    @classmethod
    def parse_action(cls, line: str) -> str | None:
        """Return the KaraoPi action represented by a libCEC key log line."""
        match = cls._KEY_LINE.search(line)
        if not match:
            return None
        key_name = re.sub(r"[_/+-]+", " ", match.group(1).strip().lower())
        key_name = " ".join(key_name.split())
        return cls._ALIASES.get(key_name)

    def _listen(self) -> None:
        while not self._stop_event.is_set():
            try:
                self._process = subprocess.Popen(
                    [self._executable or "cec-client", "-d", "31"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                if self._process.stdout is None:
                    raise RuntimeError("cec-client did not expose its output stream")
                for line in self._process.stdout:
                    if self._stop_event.is_set():
                        break
                    action = self.parse_action(line)
                    if action:
                        self._dispatch(action)
                return_code = self._process.wait()
                if not self._stop_event.is_set():
                    logging.warning(
                        "cec-client stopped with code %s; reconnecting in %.1fs",
                        return_code,
                        self._reconnect_delay,
                    )
            except (OSError, RuntimeError) as exc:
                if not self._stop_event.is_set():
                    logging.warning("Unable to listen for HDMI-CEC controls: %s", exc)
            finally:
                self._process = None
            self._stop_event.wait(self._reconnect_delay)

    def _dispatch(self, action: str) -> None:
        now = time.monotonic()
        if action == self._last_action and now - self._last_action_time < self._debounce_seconds:
            return
        self._last_action = action
        self._last_action_time = now
        logging.info("HDMI-CEC media action: %s", action)
        try:
            self._on_action(action)
        except Exception:
            logging.exception("HDMI-CEC action failed: %s", action)
