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

#: 21 characters at size 1; the headline gets size 2 when it fits in 10.
WIDTH = 21
HEADLINE_BIG = 10
MAX_LINES = 3

_STATE_WORDS = {
    SlotState.EMPTY: "not started",
    SlotState.IDLE: "idle",
    SlotState.WORKING: "working",
    SlotState.ATTENTION: "wants you",
}


def _fit(text: str) -> str:
    return text[:WIDTH]


def _slot_lines(slot: int, slots: SlotTable, panes: int | None,
                title: str | None = None) -> list[str]:
    """Three rows: what this key is, the headline, the detail."""
    session = slots.session_for(slot) or "?"
    state = slots.state_of(slot)
    bar = f"{slots.label(slot)}  {session}"

    if state is SlotState.EMPTY:
        # The one place guidance is still news: an unused key is not a broken
        # key. Everywhere else the instruction is noise after the first week.
        return [_fit(bar), _fit("not started"), _fit("press to open")]

    # The agent's own name for its work is the headline; it beats anything we
    # can infer. Without one, the state takes the big slot instead of leaving
    # the screen's focal point empty.
    headline = title or _STATE_WORDS[state]
    detail = _STATE_WORDS[state] if title else ""
    if panes:
        detail = f"{detail}  {panes} pane" + ("s" if panes != 1 else "") if detail \
            else f"{panes} pane" + ("s" if panes != 1 else "")
    return [_fit(bar), _fit(headline), _fit(detail)]


def _key_lines(key: str, launch_command: str) -> list[str]:
    if key == "KEY_TERM":
        # Tap is implied by the headline naming the command, so the detail
        # row spends its 21 characters on the two gestures you would not
        # guess. Exactly 21: "2x split  hold window".
        return ["TERM", _fit(launch_command), _fit("2x split  hold window")]
    if key == "KEY_MIC":
        return ["MIC", "voice", ""]
    if key == "KEY_CANCEL":
        return ["X", "interrupt", ""]
    if key == "KEY_ENTER":
        return ["ENTER", "send", ""]
    return [key, "", ""]


def lines_for(key: str, slots: SlotTable, launch_command: str = "claude",
              panes: int | None = None, title: str | None = None) -> list[str]:
    """The panel shown while `key` is held."""
    if key in SLOT_KEYS:
        return _slot_lines(SLOT_KEYS.index(key), slots, panes, title)
    return _key_lines(key, launch_command)


def payload(lines: list[str]) -> str:
    """Pack into the one-line wire form the device parses."""
    return "|".join(lines)
