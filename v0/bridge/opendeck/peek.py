"""What a key will do, shown while you hold it.

A deck with gestures nobody can discover is a party trick. Holding a key shows
what it does, so the device explains itself and there is no manual to lose.

Peeking must stay free: holding a key shows and changes nothing, which is what
makes it safe to explore. Hold used to interrupt the slot's session - a
destructive action on the same gesture would teach people not to explore,
which defeats the point.
"""

from __future__ import annotations

from .config import SLOT_KEYS
from .slots import SlotState, SlotTable

#: The panel is 21 characters wide at text size 1.
WIDTH = 21
MAX_LINES = 5

_STATE_WORDS = {
    SlotState.EMPTY: "not started",
    SlotState.IDLE: "idle",
    SlotState.WORKING: "working",
    SlotState.ATTENTION: "wants you",
}


def _fit(text: str) -> str:
    return text[:WIDTH]


def _slot_lines(slot: int, slots: SlotTable, panes: int | None) -> list[str]:
    session = slots.session_for(slot) or "?"
    state = slots.state_of(slot)

    lines = [_fit(f"{slots.label(slot)}  {session}")]

    if state is SlotState.EMPTY:
        # The most important thing a beginner can learn from this device: an
        # unused key is not a broken key.
        lines.append(_fit("not started yet"))
        lines.append("")
        lines.append(_fit("tap  create + open"))
    else:
        detail = _STATE_WORDS[state]
        if panes:
            detail += f"  {panes} pane" + ("s" if panes != 1 else "")
        lines.append(_fit(detail))
        lines.append("")
        lines.append(_fit("tap  go there"))
    return lines


def _key_lines(key: str, launch_command: str) -> list[str]:
    if key == "KEY_TERM":
        return [
            "TERM",
            _fit(f"tap  {launch_command} here"),
            _fit(f"2x   {launch_command} in a split"),
            _fit("hold new window"),
        ]
    if key == "KEY_MIC":
        return ["MIC", "", _fit("tap  voice on/off")]
    if key == "KEY_CANCEL":
        return ["X", "", _fit("tap  interrupt here")]
    if key == "KEY_ENTER":
        return ["ENTER", "", _fit("tap  send Enter")]
    return [key]


def lines_for(key: str, slots: SlotTable, launch_command: str = "claude",
              panes: int | None = None) -> list[str]:
    """The panel shown while `key` is held."""
    if key in SLOT_KEYS:
        return _slot_lines(SLOT_KEYS.index(key), slots, panes)[:MAX_LINES]
    return _key_lines(key, launch_command)[:MAX_LINES]


def payload(lines: list[str]) -> str:
    """Pack into the one-line wire form the device parses."""
    return "|".join(lines)
