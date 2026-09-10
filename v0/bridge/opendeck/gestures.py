"""Turn raw key edges into tap / double-tap / hold gestures.

Deliberately free of wall-clock and I/O: callers pass `now`, which makes the
timing rules exhaustively testable without sleeping.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .events import Edge, Gesture, KeyEvent

DEFAULT_DOUBLE_TAP_WINDOW = 0.35


@dataclass
class GestureRecognizer:
    double_tap_window: float = DEFAULT_DOUBLE_TAP_WINDOW
    _held: set[str] = field(default_factory=set, init=False)
    _pending: dict[str, float] = field(default_factory=dict, init=False)

    def feed(self, event: KeyEvent, now: float) -> list[tuple[str, Gesture]]:
        key = event.key

        if event.edge is Edge.DOWN:
            self._held.discard(key)
            return []

        if event.edge is Edge.HOLD:
            self._held.add(key)
            self._pending.pop(key, None)
            return [(key, Gesture.HOLD)]

        if event.edge is Edge.UP:
            if key in self._held:
                self._held.discard(key)
                return []
            deadline = self._pending.pop(key, None)
            if deadline is not None and now < deadline:
                return [(key, Gesture.DOUBLE_TAP)]
            self._pending[key] = now + self.double_tap_window
            return []

        return []

    def tick(self, now: float) -> list[tuple[str, Gesture]]:
        """Emit taps whose double-tap window has elapsed."""
        expired = [key for key, deadline in self._pending.items() if now >= deadline]
        for key in expired:
            del self._pending[key]
        return [(key, Gesture.TAP) for key in expired]

    @property
    def next_deadline(self) -> float | None:
        return min(self._pending.values(), default=None)
