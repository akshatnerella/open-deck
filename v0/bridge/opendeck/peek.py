"""What is inside a session, shown while you hold its key.

A deck with gestures nobody can discover is a party trick. Holding a key shows
what it does, so the device explains itself and there is no manual to lose.

Peeking must stay free: holding a key shows and changes nothing, which is what
makes it safe to explore. Hold used to interrupt the slot's session - a
destructive action on the same gesture would teach people not to explore,
which defeats the point.
"""

from __future__ import annotations

from . import harness
from .config import SLOT_KEYS
from .panes import _is_deliberate, pane_label
from .slots import SlotState, SlotTable

#: 21 characters at size 1, 10 at size 2.
WIDTH = 21
HEADLINE_BIG = 10
#: Rows below the title bar. Four fits comfortably; more would need a
#: scrollbar, and a panel you have to scroll is not a glance.
MAX_ROWS = 4

_STATE_WORDS = {
    SlotState.EMPTY: "not started",
    SlotState.IDLE: "idle",
    SlotState.WORKING: "working",
    SlotState.ATTENTION: "wants you",
}


def _fit(text: str) -> str:
    return text[:WIDTH]


def pane_row(pane, window=None) -> str:
    """One pane: a status mark, then whatever it is best called.

    A plain terminal says "zsh" rather than being hidden - an empty pane is
    part of the shape of the session, and leaving it out would make the count
    on screen disagree with the count on your screen.
    """
    label = pane_label(pane, window)
    running = harness.for_command(pane.command)
    mark = "." if running is harness.SHELL else "*"
    here = ">" if getattr(pane, "active", False) else " "
    return _fit(f"{here}{mark} {label}")


def _slot_lines(slot: int, slots: SlotTable, panes=(), windows=()) -> list[str]:
    """Title bar, then one row per pane."""
    session = slots.session_for(slot) or "?"
    bar = _fit(f"{slots.label(slot)}  {session}")

    if slots.state_of(slot) is SlotState.EMPTY:
        # The one screen where guidance is still news: an unused key is not a
        # broken key.
        return [bar, _fit("not started"), _fit("press to open")]

    by_index = {w.index: w for w in windows}
    # tmux renames a window after whatever runs in it, so only a name a human
    # typed is worth showing - otherwise the row just repeats the process.
    commands: dict[int, set] = {}
    for p in panes:
        commands.setdefault(p.window, set()).add(p.command)

    rows = []
    for p in panes[:MAX_ROWS]:
        window = by_index.get(p.window)
        named = window if _is_deliberate(window, commands.get(p.window, set())) else None
        rows.append(pane_row(p, named))
    return [bar, *rows] if rows else [bar, _fit("(empty)")]


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
              panes=(), windows=()) -> list[str]:
    """The panel shown while `key` is held."""
    if key in SLOT_KEYS:
        return _slot_lines(SLOT_KEYS.index(key), slots, panes, windows)
    return _key_lines(key, launch_command)


def payload(lines: list[str], cursor: int = -1) -> str:
    """Pack into the one-line wire form the device parses.

    `cursor` is the row the device draws inverted - where pressing ENTER would
    take you. -1 means no selection is in progress.
    """
    return "|".join([str(cursor), *lines])
