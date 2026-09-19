"""Derives Pixie's expression from tmux state.

Everything here is inferred from tmux alone - no agent hooks, no scraping.
tmux already tracks per-window activity and bell flags, which is exactly the
"something happened where you aren't looking" signal the face needs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from .compat import StrEnum

from . import harness
from .slots import SlotTable
from .tmux import SHELLS, Tmux

log = logging.getLogger(__name__)

class State(StrEnum):
    ALERT = "alert"
    BUSY = "busy"
    DONE = "done"
    CALM = "calm"


@dataclass(frozen=True)
class Snapshot:
    state: State
    attention_session: str | None = None


def is_agent(command: str) -> bool:
    """Kept as the module's public name; the patterns live in harness.py."""
    return harness.is_agent_command(command)


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
        self._agent_seen: set[str] = set()

    def evaluate(self, now: float | None = None) -> Snapshot:
        current = self._slots.current_session()
        if current is None:
            return Snapshot(State.CALM)

        # 1. Something wants attention in a session you are not looking at.
        for session in self._slots.slots:
            if not session or session == current:
                continue
            if any(w.activity or w.bell for w in self._tmux.windows(session)):
                return Snapshot(State.ALERT, attention_session=session)

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

        # 3. Anything running here is enough to look busy; DONE is tracked
        #    only for agents so quitting an editor does not celebrate.
        if agents_here or busy_here:
            return Snapshot(State.BUSY)

        return Snapshot(State.CALM)
