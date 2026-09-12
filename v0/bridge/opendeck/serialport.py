"""A line-oriented serial port built on termios.

This exists so the bridge has no third-party dependencies. That is not
minimalism for its own sake: pyserial was the only thing standing between this
project and "copy the folder to any Mac and run it". Requiring pip meant
requiring a venv, which meant an install step, which is what pushed an earlier
design toward making the deck a USB keyboard - a device that types into
whatever happens to have focus. Deleting one dependency deleted that pressure.

Only what the deck needs: 8N1, raw mode, read lines, write lines.
"""

from __future__ import annotations

import os
import select
import termios

BAUD = 115200


class SerialPort:
    """A raw 8N1 serial port. Use as a context manager."""

    def __init__(self, path: str, baud: int = BAUD) -> None:
        self.path = path
        self._baud = baud
        self._fd: int | None = None
        self._buf = b""

    # ---------- lifecycle ----------
    def open(self) -> None:
        # O_NONBLOCK matters at open() as well as after: without it, opening a
        # tty can block waiting for carrier.
        fd = os.open(self.path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        try:
            self._configure(fd)
        except Exception:
            os.close(fd)
            raise
        self._fd = fd

    def _configure(self, fd: int) -> None:
        iflag, oflag, cflag, lflag, _, _, cc = termios.tcgetattr(fd)

        iflag &= ~(termios.IGNBRK | termios.BRKINT | termios.PARMRK | termios.ISTRIP
                   | termios.INLCR | termios.IGNCR | termios.ICRNL | termios.IXON)
        oflag &= ~termios.OPOST
        lflag &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG
                   | termios.IEXTEN)
        cflag &= ~(termios.CSIZE | termios.PARENB | termios.CSTOPB)
        # CLOCAL: ignore modem control lines. USB CDC has none, and without this
        # the port waits forever for a carrier that never arrives.
        cflag |= termios.CS8 | termios.CREAD | termios.CLOCAL

        speed = getattr(termios, f"B{self._baud}")
        termios.tcsetattr(fd, termios.TCSANOW,
                          [iflag, oflag, cflag, lflag, speed, speed, cc])
        termios.tcflush(fd, termios.TCIOFLUSH)

    def close(self) -> None:
        if self._fd is not None:
            try:
                os.close(self._fd)
            finally:
                self._fd = None
                self._buf = b""

    @property
    def is_open(self) -> bool:
        return self._fd is not None

    def __enter__(self) -> SerialPort:
        self.open()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---------- io ----------
    def readline(self, timeout: float = 0.4) -> bytes:
        """One line without its terminator, or b"" if none arrived in time.

        Raises OSError when the device goes away - which is how unplugging is
        detected, so callers must let it propagate.
        """
        if self._fd is None:
            raise OSError("port is closed")

        while True:
            if (nl := self._buf.find(b"\n")) >= 0:
                line, self._buf = self._buf[:nl], self._buf[nl + 1:]
                return line.rstrip(b"\r")

            if not select.select([self._fd], [], [], timeout)[0]:
                return b""

            chunk = os.read(self._fd, 4096)
            if not chunk:
                # readable but empty: the far end is gone.
                raise OSError(f"{self.path} closed by device")
            self._buf += chunk

    def write_line(self, line: str) -> None:
        if self._fd is None:
            raise OSError("port is closed")
        data = f"{line}\n".encode()
        while data:
            data = data[os.write(self._fd, data):]
