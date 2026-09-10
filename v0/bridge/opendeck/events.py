"""Wire events emitted by the deck firmware."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Edge(StrEnum):
    DOWN = "DOWN"
    HOLD = "HOLD"
    UP = "UP"


class Gesture(StrEnum):
    TAP = "tap"
    DOUBLE_TAP = "double"
    HOLD = "hold"


@dataclass(frozen=True, slots=True)
class KeyEvent:
    key: str
    edge: Edge


@dataclass(frozen=True, slots=True)
class EncoderEvent:
    delta: int


@dataclass(frozen=True, slots=True)
class Heartbeat:
    uptime_ms: int


@dataclass(frozen=True, slots=True)
class Connected:
    port: str


@dataclass(frozen=True, slots=True)
class Disconnected:
    pass


DeckEvent = KeyEvent | EncoderEvent | Heartbeat | Connected | Disconnected
