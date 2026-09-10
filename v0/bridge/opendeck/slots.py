"""Maps the four agent keys onto tmux sessions.

Assignment is sticky for the lifetime of the process: physical keys are only
useful if they keep meaning the same thing, so a session keeps its slot even
while detached. A slot is released only when its session disappears.
"""

from __future__ import annotations

import logging

from .config import SLOT_LABELS
from .tmux import Tmux

log = logging.getLogger(__name__)

SLOT_COUNT = 4


class SlotTable:
    def __init__(self, tmux: Tmux, pinned: tuple[str | None, ...] = ()) -> None:
        self._tmux = tmux
        self._slots: list[str | None] = list(pinned)[:SLOT_COUNT]
        self._slots += [None] * (SLOT_COUNT - len(self._slots))
        self._pinned = {name for name in self._slots if name}

    @property
    def slots(self) -> tuple[str | None, ...]:
        return tuple(self._slots)

    def session_for(self, slot: int) -> str | None:
        if 0 <= slot < SLOT_COUNT:
            return self._slots[slot]
        return None

    def slot_of(self, session: str | None) -> int | None:
        if session is None:
            return None
        try:
            return self._slots.index(session)
        except ValueError:
            return None

    def label(self, slot: int) -> str:
        return SLOT_LABELS[slot] if 0 <= slot < SLOT_COUNT else "--"

    def refresh(self) -> None:
        live = {session.name for session in self._tmux.sessions()}

        for index, name in enumerate(self._slots):
            if name and name not in live and name not in self._pinned:
                log.info("slot %s released (session %s gone)", self.label(index), name)
                self._slots[index] = None

        assigned = {name for name in self._slots if name}
        for session in self._tmux.sessions():
            if session.name in assigned:
                continue
            for index in range(SLOT_COUNT):
                if self._slots[index] is None:
                    self._slots[index] = session.name
                    assigned.add(session.name)
                    log.info("slot %s -> %s", self.label(index), session.name)
                    break

    def create_for(self, slot: int) -> str | None:
        """Create a session for an empty slot, named after its key.

        The name is pinned so a later refresh cannot reshuffle it onto a
        different key.
        """
        if not 0 <= slot < SLOT_COUNT or self._slots[slot] is not None:
            return self._slots[slot] if 0 <= slot < SLOT_COUNT else None

        base = self.label(slot).lower()
        taken = {session.name for session in self._tmux.sessions()}
        name = base
        suffix = 2
        while name in taken:
            name = f"{base}{suffix}"
            suffix += 1

        if not self._tmux.new_session(name):
            log.error("could not create session %s", name)
            return None

        self._slots[slot] = name
        self._pinned.add(name)
        log.info("created session %s for slot %s", name, self.label(slot))
        return name

    def current_session(self) -> str | None:
        attached = self._tmux.attached_session()
        if attached:
            return attached
        return next((name for name in self._slots if name), None)
