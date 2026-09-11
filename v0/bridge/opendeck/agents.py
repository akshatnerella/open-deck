"""Agent state fed by harness lifecycle hooks.

tmux can only tell us "a non-shell process is running". Hooks tell us *which*
agent, whether it is thinking or blocked on a decision, when it finished, and
how full its context is. This module owns that knowledge; tmux stays the
fallback for panes no hook has ever reported.

Entries are keyed by tmux target (``session:window.pane``) so a pane's agent
state can be matched to the pane list and to key presses.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from enum import StrEnum

log = logging.getLogger(__name__)

#: An agent that has said nothing for this long is assumed gone. Hooks have no
#: "goodbye" that survives a kill -9, so staleness is the only honest signal.
STALE_AFTER = 900.0

#: Commands worth making the user work harder to approve.
DESTRUCTIVE_PATTERNS = [
    r"\brm\s+-[a-z]*[rf]",
    r"\bgit\s+push\b.*(--force|-f)\b",
    r"\bgit\s+reset\s+--hard\b",
    r"\bgit\s+clean\b.*-[a-z]*f",
    r"\bDROP\s+(TABLE|DATABASE|SCHEMA)\b",
    r"\bTRUNCATE\s+TABLE\b",
    r"\bDELETE\s+FROM\b(?!.*\bWHERE\b)",
    r"\b(curl|wget)\b.*\|\s*(sudo\s+)?(ba)?sh",
    r"\bsudo\b",
    r"\bchmod\s+(-R\s+)?777\b",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r">\s*/dev/sd[a-z]",
    r"\b(shutdown|reboot|halt)\b",
    r"\.ssh/|\.aws/credentials|\.env\b|id_rsa|\.pem\b",
    r"\bnpm\s+publish\b",
    r"\bkill(all)?\s+-9\b",
]
_DESTRUCTIVE = [re.compile(p, re.IGNORECASE) for p in DESTRUCTIVE_PATTERNS]


def is_destructive(text: str) -> bool:
    return any(rx.search(text or "") for rx in _DESTRUCTIVE)


class Status(StrEnum):
    IDLE = "idle"
    WORKING = "working"
    BLOCKED = "blocked"
    DONE = "done"


@dataclass(slots=True)
class Approval:
    """A permission request an agent is stopped on."""

    target: str
    agent: str
    tool: str
    text: str
    created: float = field(default_factory=time.monotonic)

    @property
    def dangerous(self) -> bool:
        return is_destructive(f"{self.tool} {self.text}")


@dataclass(slots=True)
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
    """Everything the harness has told us, plus the approval queue."""

    def __init__(self) -> None:
        self._agents: dict[str, Agent] = {}
        self._approvals: list[Approval] = []

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

    # ---------- approvals ----------
    @property
    def approvals(self) -> list[Approval]:
        return list(self._approvals)

    @property
    def current_approval(self) -> Approval | None:
        return self._approvals[0] if self._approvals else None

    def pop_approval(self) -> Approval | None:
        return self._approvals.pop(0) if self._approvals else None

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
            self._drop_approvals_for(target)
        elif event in ("sessionend", "session_end"):
            self._agents.pop(target, None)
            self._drop_approvals_for(target)

    def _on_notification(self, agent: Agent, payload: dict) -> None:
        # Claude Code fires Notification for plain idle nudges too, so only a
        # permission-shaped message should stop the deck.
        message = (payload.get("message") or "").lower()
        if not any(w in message for w in ("permission", "approve", "waiting for your input")):
            return
        agent.status = Status.BLOCKED
        tool_input = payload.get("tool_input") or {}
        text = (tool_input.get("command") or tool_input.get("file_path")
                or payload.get("message") or "")
        if any(a.target == agent.target for a in self._approvals):
            return
        self._approvals.append(Approval(
            target=agent.target,
            agent=agent.name,
            tool=payload.get("tool_name", "?"),
            text=str(text)[:300],
        ))
        log.info("approval queued: %s on %s", payload.get("tool_name"), agent.target)

    def resolve(self, target: str, approved: bool) -> None:
        """The user answered; the agent is running again either way."""
        self._drop_approvals_for(target)
        agent = self._agents.get(target)
        if agent is not None:
            agent.status = Status.WORKING if approved else Status.IDLE

    def _drop_approvals_for(self, target: str) -> None:
        self._approvals = [a for a in self._approvals if a.target != target]
