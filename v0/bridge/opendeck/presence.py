"""Derives Pixie's expression from tmux state.

Everything here is inferred from tmux alone - no agent hooks, no scraping.
tmux already tracks per-window activity and bell flags, which is exactly the
"something happened where you aren't looking" signal the face needs.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from enum import StrEnum

from .slots import SlotTable
from .tmux import SHELLS, Tmux

log = logging.getLogger(__name__)

#: Commands that mean an agent is working in a pane.
AGENT_COMMANDS = frozenset({"claude", "cla", "grok", "opencode", "codex", "aider", "node"})

#: Claude Code reports its version string (e.g. "2.1.261") as the pane's
#: current command rather than its binary name, so match that shape too.
_VERSION_LIKE = re.compile(r"^\d+(?:\.\d+)+$")

ACTIVE_LINGER = 4.0
SLEEP_AFTER = 300.0


class State(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    ATTENTION = "attention"
    DONE = "done"
    ACTIVE = "active"
    ASLEEP = "asleep"


@dataclass(frozen=True, slots=True)
class Snapshot:
    state: State
    attention_session: str | None = None


def is_agent(command: str) -> bool:
    if not command or command in SHELLS:
        return False
    return command in AGENT_COMMANDS or bool(_VERSION_LIKE.match(command))


def is_busy(command: str) -> bool:
    """Any running program, agent or not."""
    return bool(command) and command not in SHELLS


class PresenceMonitor:
    """Resolves competing signals into one expression.

    Evaluated in priority order so the face cannot flap between two states
    that are simultaneously true.
    """

    def __init__(self, tmux: Tmux, slots: SlotTable) -> None:
        self._tmux = tmux
        self._slots = slots
        self._last_input = 0.0
        self._agent_seen: set[str] = set()

    def note_input(self, now: float | None = None) -> None:
        self._last_input = now if now is not None else time.monotonic()

    def evaluate(self, now: float | None = None) -> Snapshot:
        now = now if now is not None else time.monotonic()
        current = self._slots.current_session()

        if current is None:
            return Snapshot(State.ASLEEP)

        # 1. Something wants attention in a session you are not looking at.
        for session in self._slots.slots:
            if not session or session == current:
                continue
            if any(w.activity or w.bell for w in self._tmux.windows(session)):
                return Snapshot(State.ATTENTION, attention_session=session)

        panes = self._tmux.panes(current)
        agents_here = {p.target for p in panes if is_agent(p.command)}
        busy_here = any(is_busy(p.command) for p in panes)
        key = f"{current}:"
        previously = {t for t in self._agent_seen if t.startswith(key)}
        currently = {f"{key}{t}" for t in agents_here}

        # 2. An agent that was running here has stopped.
        finished = previously - currently
        self._agent_seen = (self._agent_seen - previously) | currently
        if finished:
            return Snapshot(State.DONE)

        # 3. Something is running here. DONE is tracked only for agents, but
        #    any running program is enough to look busy.
        if agents_here or busy_here:
            return Snapshot(State.WORKING)

        # 4. You just touched the deck.
        if now - self._last_input < ACTIVE_LINGER:
            return Snapshot(State.ACTIVE)

        # 5. Nothing at all for a while.
        if self._last_input and now - self._last_input > SLEEP_AFTER:
            return Snapshot(State.ASLEEP)

        return Snapshot(State.IDLE)
