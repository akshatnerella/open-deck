"""Which agent CLI you run, and how to recognise it in a tmux pane.

Everything harness-specific lives here, because the differences are small and
awkward, and were previously scattered:

    Claude Code      process "2.1.268"        title "* open deck"
    Grok CLI         process "grok-1.0.30-mac"  title "grok"

Both were measured, not assumed, and both broke a guess. Claude reports its
*version* as the process name, so matching "claude" finds nothing. Grok appends
its version and platform, so matching "grok" finds nothing either.

Detection stays deliberately permissive: a deck configured for Grok still
reports a Claude pane as working. The setting picks what a key *launches*; it
must not make the display lie about what is actually running.
"""

from __future__ import annotations

import re
import socket
from dataclasses import dataclass, field

from .tmux import SHELLS


@dataclass(frozen=True)
class Harness:
    key: str
    label: str
    command: str
    #: Matched against tmux's pane_current_command.
    patterns: tuple[re.Pattern, ...] = field(default_factory=tuple)

    def matches(self, command: str) -> bool:
        return any(p.match(command) for p in self.patterns)


HARNESSES: dict[str, Harness] = {
    "claude": Harness(
        key="claude",
        label="Claude Code",
        command="claude",
        # Claude Code reports its version string as the process name.
        patterns=(re.compile(r"^claude$"), re.compile(r"^\d+(?:\.\d+)+$")),
    ),
    "grok": Harness(
        key="grok",
        label="Grok CLI",
        command="grok",
        # Observed as "grok-1.0.30-mac": name, version, platform.
        patterns=(re.compile(r"^grok(?:-.*)?$"),),
    ),
    "opencode": Harness(
        key="opencode",
        label="OpenCode",
        command="opencode",
        patterns=(re.compile(r"^opencode(?:-.*)?$"),),
    ),
    "codex": Harness(
        key="codex",
        label="Codex",
        command="codex",
        patterns=(re.compile(r"^codex(?:-.*)?$"),),
    ),
    "aider": Harness(
        key="aider",
        label="Aider",
        command="aider",
        patterns=(re.compile(r"^aider(?:-.*)?$"),),
    ),
}

DEFAULT_HARNESS = "claude"


def get(key: str | None) -> Harness:
    return HARNESSES.get((key or "").lower(), HARNESSES[DEFAULT_HARNESS])


def is_agent_command(command: str) -> bool:
    """Is this pane running some agent CLI - any of them?"""
    if not command or command in SHELLS:
        return False
    return any(h.matches(command) for h in HARNESSES.values())


# ---------------------------------------------------------------------------
# Session titles
# ---------------------------------------------------------------------------

def _hostnames() -> set[str]:
    name = socket.gethostname()
    forms = {name, name.split(".")[0]}
    return {f.lower() for f in forms if f}


def clean_title(title: str, command: str = "") -> str | None:
    """The agent's own name for what it is working on, or None.

    Terminal titles are mostly noise - a hostname, the program's own name, or
    nothing. Only a title that says something the pane does not already say is
    worth the space on a 21-column panel.
    """
    if not title:
        return None

    # The device's font is ASCII-only, so decoration like Claude's leading
    # asterisk glyph would render as garbage rather than be ignored.
    text = "".join(ch for ch in title if 32 <= ord(ch) < 127).strip()
    text = text.strip("*-_~ \t")
    if not text:
        return None

    low = text.lower()
    if low in _hostnames() or low in SHELLS:
        return None

    # "grok" against a process of "grok-1.0.30-mac" tells you nothing you
    # cannot already see; a real session name does.
    cmd = (command or "").lower()
    if cmd and (low == cmd or cmd.startswith(low) or low.startswith(cmd)):
        return None

    return text


def session_title(panes) -> str | None:
    """The first meaningful title among a session's panes."""
    for pane in panes:
        cleaned = clean_title(getattr(pane, "title", "") or "",
                              getattr(pane, "command", "") or "")
        if cleaned:
            return cleaned
    return None
