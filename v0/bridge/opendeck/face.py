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

    def reset(self) -> None:
        """Forget the pushed state so the next update repaints."""
        self._state = None

    def apply(self, snapshot: Snapshot) -> bool:
        """Push the expression, returning True if it changed."""
        if snapshot.state is self._state:
            return False
        self._state = snapshot.state
        self._transport.send(f"STATE {snapshot.state}")
        log.debug("state -> %s", snapshot.state)
        return True

    def toast(self, text: str) -> None:
        text = text[:TOAST_MAX]
        log.info("toast: %s", text)
        self._transport.send(f"TOAST {text}")
