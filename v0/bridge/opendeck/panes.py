"""Formats the pane list the deck displays.

The host owns every formatting rule - windowing, markers, flags, truncation -
so the firmware stays a dumb renderer and all of this stays testable here.
"""

from __future__ import annotations

from .presence import is_agent
from .tmux import SHELLS, Pane, Window

DISPLAY_WIDTH = 21
MAX_ROWS = 5
LABEL_WIDTH = 13
EMPTY_ROW = "(empty)"

_GENERIC_NAMES = frozenset({"zsh", "bash", "sh", "fish"})
_AGENT_LABEL = "claude"


def _sanitise_field(text: str) -> str:
    """A label is one token inside a row - strip whitespace so columns stay aligned."""
    return "".join("_" if ch in "| \t\r\n" else ch for ch in text)


def _sanitise_line(text: str) -> str:
    """A title is a display line - spaces are layout. Only framing chars are stripped."""
    return "".join("_" if ch in "|\r\n" else ch for ch in text)


def pane_label(pane: Pane, window: Window | None) -> str:
    if window is not None and window.name and window.name not in _GENERIC_NAMES:
        label = window.name
    elif is_agent(pane.command) and pane.command not in SHELLS:
        # Claude Code reports its version string as the process name, so the
        # raw command is useless as a label even though it is a real agent.
        label = pane.command if pane.command.isalpha() else _AGENT_LABEL
    else:
        label = pane.command or "?"
    return _sanitise_field(label)[:LABEL_WIDTH]


def _flag(pane: Pane, windows: list[Window]) -> str:
    for w in windows:
        if w.index == pane.window:
            return w.flag.strip()
    return ""


def _window_rows(panes: list[Pane], max_rows: int) -> list[Pane]:
    """Slice the list so the active pane is always visible."""
    if len(panes) <= max_rows:
        return panes
    active = next((i for i, p in enumerate(panes) if p.active), 0)
    first = max(0, min(active - max_rows // 2, len(panes) - max_rows))
    return panes[first : first + max_rows]


def build_list(
    title: str,
    panes: list[Pane],
    windows: list[Window],
    max_rows: int = MAX_ROWS,
) -> str:
    rows = []
    for pane in _window_rows(panes, max_rows):
        marker = ">" if pane.active else " "
        flag = _flag(pane, windows)
        row = f"{marker}{pane.index:<2}{pane_label(pane, None)}"
        if flag:
            row = f"{row} {flag}"
        rows.append(row[:DISPLAY_WIDTH])
    if not rows:
        rows = [EMPTY_ROW]
    return "|".join([_sanitise_line(title)[:DISPLAY_WIDTH], *rows])
