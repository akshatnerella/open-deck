"""Formats the pane list the deck displays.

The host owns every formatting rule - windowing, markers, flags, truncation -
so the firmware stays a dumb renderer and all of this stays testable here.
"""

from __future__ import annotations

from . import harness
from .presence import is_agent
from .tmux import SHELLS, _GENERIC_WINDOW_NAMES, Pane, Window

DISPLAY_WIDTH = 21
MAX_ROWS = 5
LABEL_WIDTH = 13
EMPTY_ROW = "(empty)"




def _sanitise_field(text: str) -> str:
    """A label is one token inside a row - strip whitespace so columns stay aligned."""
    return "".join("_" if ch in "| \t\r\n" else ch for ch in text)


def _sanitise_line(text: str) -> str:
    """A title is a display line - spaces are layout. Only framing chars are stripped."""
    return "".join("_" if ch in "|\r\n" else ch for ch in text)


def pane_label(pane: Pane, window: Window | None) -> str:
    """The best name available for this pane, in descending order of trust."""
    if window is not None and window.name and window.name not in _GENERIC_WINDOW_NAMES:
        # A name a human typed beats anything we can infer.
        label = window.name
    elif is_agent(pane.command) and pane.command not in SHELLS:
        # The agent's own session title is the next best thing: "open deck"
        # says what this pane is for, where the generic fallback says only
        # that it is an agent. The raw command is useless either way, since
        # Claude Code reports its version string as the process name.
        title = harness.clean_title(pane.title or "", pane.command)
        # Without a session name, fall back to which agent it is rather than
        # the raw process: "grok-1.0.34-mac" is noise, and a fixed "claude"
        # would be a lie in a grok pane.
        label = title or harness.for_command(pane.command).key
    else:
        label = pane.command or "?"
    return _sanitise_field(label)[:LABEL_WIDTH]


def _is_deliberate(window: Window | None, commands: set[str]) -> bool:
    """Whether a human chose this window's name.

    tmux renames a window after whatever is running in it, so a name matching
    any of its panes' commands tells us nothing the command does not - and for
    a Claude Code pane it is worse, since tmux reports the version string
    ("2.1.268") as the process name and the window inherits that. A name
    matching none of its panes was typed by someone.
    """
    return window is not None and bool(window.name) and window.name not in commands


def _flag(window: Window | None) -> str:
    return window.flag.strip() if window is not None else ""


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
    agents: dict[str, object] | None = None,
) -> str:
    """Format the pane list.

    `agents` maps a pane target ("window.pane") to an Agent. Where hooks have
    reported one, its context percentage is appended - the early warning that
    an agent is about to compact and start forgetting your instructions, which
    is invisible from tmux alone.
    """
    agents = agents or {}
    by_index = {w.index: w for w in windows}
    commands_by_window: dict[int, set[str]] = {}
    for p in panes:
        commands_by_window.setdefault(p.window, set()).add(p.command)

    rows = []
    for pane in _window_rows(panes, max_rows):
        window = by_index.get(pane.window)
        # The flag always comes from the real window; only the *name* is
        # suppressed when tmux derived it rather than a human.
        named = window if _is_deliberate(window, commands_by_window.get(pane.window, set())) else None
        # No pane index: you step through these with the encoder, so the
        # number is an implementation detail you never type.
        marker = ">" if pane.active else " "
        flag = _flag(window)
        row = f"{marker} {pane_label(pane, named)}"
        agent = agents.get(pane.target)
        ctx = getattr(agent, "context_pct", 0) if agent else 0
        if ctx >= 70:
            row = f"{row} {ctx}%"
        elif flag:
            row = f"{row} {flag}"
        rows.append(row[:DISPLAY_WIDTH])
    if not rows:
        rows = [EMPTY_ROW]
    return "|".join([_sanitise_line(title)[:DISPLAY_WIDTH], *rows])
