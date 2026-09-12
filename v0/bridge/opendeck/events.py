"""Wire events emitted by the deck firmware."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Union

from .compat import StrEnum


class Edge(StrEnum):
    DOWN = "DOWN"
    HOLD = "HOLD"
    UP = "UP"


class Gesture(StrEnum):
    TAP = "tap"
    DOUBLE_TAP = "double"
    HOLD = "hold"


@dataclass(frozen=True)
class KeyEvent:
    key: str
    edge: Edge


@dataclass(frozen=True)
class EncoderEvent:
    delta: int


@dataclass(frozen=True)
class Heartbeat:
    uptime_ms: int


@dataclass(frozen=True)
class Connected:
    port: str


@dataclass(frozen=True)
class Disconnected:
    pass


DeckEvent = Union[KeyEvent, EncoderEvent, Heartbeat, Connected, Disconnected]
