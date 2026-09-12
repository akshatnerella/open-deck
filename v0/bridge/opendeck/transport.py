"""Serial link to the deck.

Owns the port on a background thread and reconnects on drop, publishing parsed
events onto a queue.
"""

from __future__ import annotations

import glob
import logging
import queue
import re
import threading
import time

from .events import Connected, DeckEvent, Disconnected, Edge, EncoderEvent, Heartbeat, KeyEvent
from .serialport import BAUD, SerialPort

log = logging.getLogger(__name__)

PORT_GLOBS = ("/dev/cu.usbmodem*", "/dev/ttyACM*", "/dev/ttyUSB*")

_KEY = re.compile(r"^EVT\s+(KEY_\w+)\s+(DOWN|HOLD|UP)$")
_ENCODER = re.compile(r"^EVT\s+ENCODER\s+([+-]?\d+)$")
_HEARTBEAT = re.compile(r"^HB\s+(\d+)$")


def discover_port() -> str | None:
    for pattern in PORT_GLOBS:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


def parse(line: str) -> DeckEvent | None:
    if match := _KEY.match(line):
        return KeyEvent(key=match[1], edge=Edge(match[2]))
    if match := _ENCODER.match(line):
        return EncoderEvent(delta=int(match[1]))
    if match := _HEARTBEAT.match(line):
        return Heartbeat(uptime_ms=int(match[1]))
    return None


class SerialTransport:
    """Background reader publishing `DeckEvent`s onto `events`."""

    def __init__(self, port: str | None = None, reconnect_delay: float = 1.0) -> None:
        self._port = port
        self._reconnect_delay = reconnect_delay
        self._serial: SerialPort | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()
        self.events: queue.Queue[DeckEvent] = queue.Queue()

    @property
    def connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def start(self) -> None:
        if self._thread is not None:
            raise RuntimeError("transport already started")
        self._thread = threading.Thread(target=self._run, name="deck-serial", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def send(self, line: str) -> bool:
        with self._write_lock:
            if not self.connected:
                return False
            try:
                self._serial.write_line(line)
                return True
            except OSError:
                return False

    def _run(self) -> None:
        while not self._stop.is_set():
            port = self._port or discover_port()
            if port is None:
                time.sleep(self._reconnect_delay)
                continue
            try:
                self._read_forever(port)
            except OSError as exc:
                log.warning("serial error on %s: %s", port, exc)
            finally:
                self._serial = None
                self.events.put(Disconnected())
                if not self._stop.is_set():
                    time.sleep(self._reconnect_delay)

    def _read_forever(self, port: str) -> None:
        with SerialPort(port, BAUD) as conn:
            self._serial = conn
            log.info("connected to %s", port)
            self.events.put(Connected(port=port))
            while not self._stop.is_set():
                raw = conn.readline(timeout=0.4)
                if not raw:
                    continue
                line = raw.decode(errors="replace").strip()
                if event := parse(line):
                    self.events.put(event)
                elif line:
                    log.debug("device: %s", line)
