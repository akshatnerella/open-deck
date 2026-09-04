"""Agent slot state tracking for the Open Deck bridge."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Optional

IDLE = "idle"
RUN = "run"
BLOCKED = "blocked"
DONE = "done"
ERROR = "error"

# Commands worth making the user work harder to approve. Matched case-insensitively
# against the full command text. These are shown inverted with a "!" on the device
# and require a second ENTER press to confirm.
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

_DESTRUCTIVE_RE = [re.compile(p, re.IGNORECASE) for p in DESTRUCTIVE_PATTERNS]


def is_destructive(text: str) -> bool:
    return any(rx.search(text or "") for rx in _DESTRUCTIVE_RE)


@dataclass
class Approval:
    """A pending permission request from an agent."""
    slot: int
    agent: str
    tool: str
    text: str
    created: float = field(default_factory=time.time)

    @property
    def dangerous(self) -> bool:
        return is_destructive(f"{self.tool} {self.text}")


@dataclass
class Slot:
    """One agent slot, mapped to one physical agent key on the deck."""
    index: int
    name: str = "--"
    session_id: Optional[str] = None
    status: str = IDLE
    started: Optional[float] = None
    ctx_pct: int = 0
    last_tool: str = ""
    last_file: str = ""
    target: Optional[str] = None  # tmux window/pane or terminal identifier

    @property
    def elapsed(self) -> int:
        if self.status == RUN and self.started:
            return int(time.time() - self.started)
        return 0

    def to_wire(self) -> str:
        name = (self.name or "--")[:8].replace(" ", "_")
        return f"SLOT {self.index} {name} {self.status} {self.elapsed} {self.ctx_pct}"


class DeckState:
    """Owns the four slots plus the approval queue.

    Slot assignment is by session_id: the first event from an unknown session
    claims a free slot, so agents land on keys in the order you start them.
    """

    def __init__(self, slot_names=("FOX", "OWL", "CAT", "PNDA")):
        self.slots = [Slot(index=i, name=slot_names[i]) for i in range(4)]
        self.default_names = list(slot_names)
        self.approvals: list[Approval] = []
        self.selection = 0

    def slot_for_session(self, session_id: str, cwd: str = "") -> Optional[Slot]:
        for s in self.slots:
            if s.session_id == session_id:
                return s
        for s in self.slots:
            if s.session_id is None:
                s.session_id = session_id
                if cwd:
                    s.name = cwd.rstrip("/").split("/")[-1][:8].upper() or s.name
                return s
        return None  # all four occupied; ignore extra sessions

    def release_session(self, session_id: str) -> None:
        for s in self.slots:
            if s.session_id == session_id:
                idx = s.index
                self.slots[idx] = Slot(index=idx, name=self.default_names[idx])

    def add_approval(self, ap: Approval) -> None:
        self.approvals.append(ap)

    def pop_approval(self) -> Optional[Approval]:
        return self.approvals.pop(0) if self.approvals else None

    @property
    def current_approval(self) -> Optional[Approval]:
        return self.approvals[0] if self.approvals else None
