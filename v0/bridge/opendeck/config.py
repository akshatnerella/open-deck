"""Configuration: key bindings, session slots, launch command."""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from .gestures import DEFAULT_DOUBLE_TAP_WINDOW

SLOT_KEYS = ("KEY_AGENT1", "KEY_AGENT2", "KEY_AGENT3", "KEY_AGENT4")
SLOT_LABELS = ("FOX", "OWL", "CAT", "PNDA")

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "opendeck" / "config.json"


@dataclass(frozen=True)
class Binding:
    """An action name plus its keyword arguments, resolved by the registry."""

    action: str
    args: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, spec: Any) -> "Binding":
        if isinstance(spec, str):
            return cls(action=spec)
        if isinstance(spec, dict):
            data = dict(spec)
            action = data.pop("action", None)
            if not action:
                raise ValueError(f"binding missing 'action': {spec!r}")
            return cls(action=action, args=data)
        raise ValueError(f"invalid binding: {spec!r}")


def default_bindings() -> dict[str, dict[str, Binding]]:
    bindings: dict[str, dict[str, Binding]] = {
        "KEY_TERM": {
            # Tap fills the pane you are in; double-tap makes a new empty one.
            # So "I want an agent over there" is double-tap then tap.
            "tap": Binding("launch_agent"),
            "double": Binding("split_pane"),
            "hold": Binding("new_window"),
        },
        # These three are one key each but three different keystrokes,
        # depending on what is running in the pane. See harness.py.
        "KEY_MIC": {"tap": Binding("context_key", {"role": "voice"})},
        "KEY_CANCEL": {
            "tap": Binding("context_key", {"role": "cancel"}),
            # Tap interrupts, double-tap closes. So "stop, then get rid of it"
            # is the same key twice.
            "double": Binding("close_pane"),
        },
        "KEY_ENTER": {"tap": Binding("context_key", {"role": "enter"})},
    }
    for slot, key in enumerate(SLOT_KEYS):
        # No "hold" action: holding shows what the key does (see peek.py).
        # Binding a destructive action to the same gesture would teach people
        # not to explore, which is the opposite of what peek is for. Bind
        # "hold" in config.json if you want the old interrupt-in-place.
        bindings[key] = {"tap": Binding("summon", {"slot": slot})}
    return bindings


@dataclass(frozen=True)
class Config:
    #: Which agent CLI the deck launches. Picks the default launch command;
    #: detection stays permissive so a pane running a different one still
    #: reads as working rather than idle.
    harness: str = "claude"
    launch_command: str = ""
    #: tmux session pinned to each slot; None means "auto-assign on discovery".
    sessions: tuple[str | None, ...] = (None, None, None, None)
    serial_port: str | None = None
    terminal: str | None = None
    fullscreen: bool = True
    double_tap_window: float = DEFAULT_DOUBLE_TAP_WINDOW
    bindings: dict[str, dict[str, Binding]] = field(default_factory=default_bindings)

    def __post_init__(self) -> None:
        # Frozen dataclass, so fill the derived default the long way. Setting
        # "harness": "grok" should be enough on its own; naming the command as
        # well stays possible for anyone wrapping it in a shell alias.
        if not self.launch_command:
            from .harness import get
            object.__setattr__(self, "launch_command", get(self.harness).command)

    def binding(self, key: str, gesture: str) -> Binding | None:
        return self.bindings.get(key, {}).get(gesture)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        bindings = default_bindings()
        for key, gestures in (data.get("bindings") or {}).items():
            resolved = {g: Binding.parse(spec) for g, spec in gestures.items()}
            bindings[key] = {**bindings.get(key, {}), **resolved}

        sessions = data.get("sessions")
        if sessions is not None:
            padded = list(sessions)[:4] + [None] * max(0, 4 - len(sessions))
            sessions = tuple(name or None for name in padded)

        known = {
            "harness", "launch_command", "serial_port", "terminal", "fullscreen",
            "double_tap_window",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        if sessions is not None:
            kwargs["sessions"] = sessions
        return cls(bindings=bindings, **kwargs)

    @classmethod
    def load(cls, path: Path | None = None) -> "Config":
        path = path or DEFAULT_CONFIG_PATH
        if not path.exists():
            return cls()
        with path.open() as handle:
            return cls.from_dict(json.load(handle))

    def with_overrides(self, **kwargs: Any) -> "Config":
        return replace(self, **{k: v for k, v in kwargs.items() if v is not None})
