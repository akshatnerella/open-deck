"""Serial link to the Open Deck hardware.

Owns the port, reconnects on drop (this board disconnects often), parses
device->host events and queues them, and pushes host->device display state.
"""

from __future__ import annotations

import glob
import logging
import queue
import re
import threading
import time

import serial

log = logging.getLogger("opendeck.device")

EVT_KEY_RE = re.compile(r"^EVT\s+(KEY_\w+)\s+(DOWN|HOLD|UP)\s*$")
EVT_ENC_RE = re.compile(r"^EVT\s+ENCODER\s+([+-]\d+)\s*$")
HB_RE = re.compile(r"^HB\s+(\d+)\s*$")


def find_port() -> str | None:
    for pattern in ("/dev/cu.usbmodem*", "/dev/ttyACM*", "/dev/ttyUSB*"):
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[0]
    return None


class Device(threading.Thread):
    """Background serial reader/writer.

    Events are pushed onto `events` as ("key", name, edge) / ("encoder", delta)
    / ("heartbeat", uptime_ms) / ("connected", port) / ("disconnected", None).
    """

    def __init__(self, port: str | None = None):
        super().__init__(daemon=True)
        self.port = port
        self.events: queue.Queue = queue.Queue()
        self.running = True
        self._ser: serial.Serial | None = None
        self._write_lock = threading.Lock()
        self.last_heartbeat = 0.0

    @property
    def connected(self) -> bool:
        return self._ser is not None and self._ser.is_open

    def send(self, line: str) -> None:
        """Push one protocol line to the device. Silently no-ops when offline."""
        with self._write_lock:
            if not self.connected:
                return
            try:
                self._ser.write((line + "\n").encode())
            except (serial.SerialException, OSError):
                pass  # the read loop will notice and reconnect

    def run(self) -> None:
        while self.running:
            port = self.port or find_port()
            if not port:
                time.sleep(1.0)
                continue
            try:
                with serial.Serial(port, 115200, timeout=0.4) as ser:
                    self._ser = ser
                    time.sleep(0.3)  # let the CDC link settle before first write
                    log.info("connected to %s", port)
                    self.events.put(("connected", port, None))
                    while self.running:
                        raw = ser.readline()
                        if not raw:
                            continue
                        self._parse(raw.decode(errors="replace").strip())
            except (serial.SerialException, OSError) as e:
                log.warning("serial error (%s); retrying", e)
            finally:
                self._ser = None
                self.events.put(("disconnected", None, None))
                time.sleep(1.0)

    def _parse(self, line: str) -> None:
        if not line:
            return
        m = EVT_KEY_RE.match(line)
        if m:
            self.events.put(("key", m.group(1), m.group(2)))
            return
        m = EVT_ENC_RE.match(line)
        if m:
            self.events.put(("encoder", int(m.group(1)), None))
            return
        m = HB_RE.match(line)
        if m:
            self.last_heartbeat = time.time()
            self.events.put(("heartbeat", int(m.group(1)), None))
            return
        log.debug("device: %s", line)
