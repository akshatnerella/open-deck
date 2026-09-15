"""Pushes expression and toast notifications to the deck."""

from __future__ import annotations

import logging

from .presence import Snapshot, State
from .transport import SerialTransport

log = logging.getLogger(__name__)

TOAST_MAX = 21


class Face:
    def __init__(self, transport: SerialTransport) -> None:
        self._transport = transport
        self._state: State | None = None
        self._slots: str | None = None

    def reset(self) -> None:
        """Forget the pushed state so the next update repaints."""
        self._state = None
        self._slots = None

    def apply(self, snapshot: Snapshot) -> bool:
        """Push the expression, returning True if it changed."""
        if snapshot.state is self._state:
            return False
        self._state = snapshot.state
        self._transport.send(f"FACE {snapshot.state}")
        log.debug("face -> %s", snapshot.state)
        return True

    def keepalive(self) -> None:
        """Re-send the current face unconditionally.

        The device treats any received command as proof the host is alive and
        falls back to an offline face without one. The firmware early-returns
        on an unchanged state, so this restarts no animation.
        """
        self._transport.send(f"FACE {self._state or State.CALM}")

    def toast(self, text: str) -> None:
        text = text[:TOAST_MAX]
        log.info("toast: %s", text)
        self._transport.send(f"TOAST {text}")

    def show_list(self, payload: str) -> None:
        self._transport.send(f"LIST {payload}")

    def show_slots(self, codes: str) -> bool:
        """Push the four slot status characters, if they changed.

        Sent only on change: the strip is redrawn from the device's own copy
        every frame, so re-sending an identical line buys nothing and costs
        serial bandwidth the key events need.
        """
        if codes == self._slots:
            return False
        self._slots = codes
        self._transport.send(f"SLOTS {codes}")
        log.debug("slots -> %r", codes)
        return True
