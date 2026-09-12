"""Agent state fed by harness lifecycle hooks.

tmux can only tell us "a non-shell process is running". Hooks tell us *which*
agent it is, whether it is thinking or waiting on you, when it finished, and
how full its context is. This module owns that knowledge; tmux stays the
fallback for panes no hook has ever reported.

Entries are keyed by tmux target (``session:window.pane``) so a pane's agent
state can be matched to the pane list.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from .compat import StrEnum

log = logging.getLogger(__name__)

#: An agent that has said nothing for this long is assumed gone. Hooks have no
#: "goodbye" that survives a kill -9, so staleness is the only honest signal.
STALE_AFTER = 900.0


class Status(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    DONE = "done"


@dataclass
class Agent:
    target: str
    session: str
    name: str = "agent"
    status: Status = Status.IDLE
    tool: str = ""
    context_pct: int = 0
    updated: float = field(default_factory=time.monotonic)

    @property
    def window(self) -> int:
        try:
            return int(self.target.split(":")[1].split(".")[0])
        except (IndexError, ValueError):
            return -1

    @property
    def pane(self) -> int:
        try:
            return int(self.target.split(".")[-1])
        except ValueError:
            return -1


class AgentRegistry:
    """Everything the harness has told us about running agents."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}

    # ---------- queries ----------
    def all(self, now: float | None = None) -> list[Agent]:
        now = now if now is not None else time.monotonic()
        return [a for a in self._agents.values() if now - a.updated < STALE_AFTER]

    def for_target(self, target: str, now: float | None = None) -> Agent | None:
        agent = self._agents.get(target)
        if agent is None:
            return None
        now = now if now is not None else time.monotonic()
        return agent if now - agent.updated < STALE_AFTER else None

    def in_session(self, session: str, now: float | None = None) -> list[Agent]:
        return [a for a in self.all(now) if a.session == session]

    def blocked(self, now: float | None = None) -> list[Agent]:
        return [a for a in self.all(now) if a.status is Status.BLOCKED]

    # ---------- hook ingestion ----------
    def record(self, event: str, target: str, session: str, payload: dict,
               now: float | None = None) -> None:
        """Fold one hook event into the registry."""
        if not target:
            return
        now = now if now is not None else time.monotonic()

        agent = self._agents.get(target)
        if agent is None:
            agent = Agent(target=target, session=session)
            self._agents[target] = agent
        agent.session = session or agent.session
        agent.updated = now

        ctx = payload.get("context_percent", payload.get("ctx_pct"))
        if ctx is not None:
            try:
                agent.context_pct = max(0, min(100, int(float(ctx))))
            except (TypeError, ValueError):
                pass

        event = event.lower()
        if event in ("sessionstart", "session_start"):
            agent.status = Status.IDLE
        elif event in ("userpromptsubmit", "user_prompt_submit"):
            agent.status = Status.WORKING
        elif event in ("pretooluse", "pre_tool_use"):
            agent.status = Status.WORKING
            agent.tool = payload.get("tool_name", "")
        elif event == "notification":
            self._on_notification(agent, payload)
        elif event == "stop":
            agent.status = Status.DONE
        elif event in ("sessionend", "session_end"):
            self._agents.pop(target, None)

    def _on_notification(self, agent: Agent, payload: dict) -> None:
        # Claude Code fires Notification for plain idle nudges too, so only a
        # message that is actually asking for something should raise an alert.
        # Sessions launched with --dangerously-skip-permissions never ask, so
        # this stays dormant there by design.
        message = (payload.get("message") or "").lower()
        if any(w in message for w in ("permission", "approve", "waiting for your input")):
            agent.status = Status.BLOCKED
