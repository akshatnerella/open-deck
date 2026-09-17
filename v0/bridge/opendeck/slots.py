"""Maps the four animal keys onto tmux sessions.

A key means one session, permanently: FOX is ``fox``, and pressing it goes
there whether or not it already exists. Nothing is discovered, nothing is
reshuffled, nothing has to be configured.

That is a deliberate reversal. Slots used to be filled by whatever sessions
happened to exist, in discovery order, which meant a key's meaning depended on
the order you had started things that morning. A physical button whose meaning
moves is worse than no button - so the mapping is now fixed, and creating the
session is the deck's job rather than yours.
"""

from __future__ import annotations

import logging

from .compat import StrEnum
from .config import SLOT_LABELS
from .tmux import Tmux

log = logging.getLogger(__name__)

SLOT_COUNT = 4

#: Default session name per slot - the label, lowercased.
DEFAULT_SESSIONS = tuple(label.lower() for label in SLOT_LABELS)


class SlotState(StrEnum):
    """What the strip on the deck shows for one slot."""

    EMPTY = " "      # no session yet; pressing the key creates one
    IDLE = "."       # a shell, nothing running
    WORKING = "@"    # something is running
    ATTENTION = "!"  # activity or a bell where you are not looking


class SlotTable:
    def __init__(self, tmux: Tmux, pinned: tuple[str | None, ...] = ()) -> None:
        self._tmux = tmux
        # A configured name overrides the default, so someone who wants FOX to
        # mean "webapp" can say so - but the binding is still fixed.
        names = list(pinned)[:SLOT_COUNT] + [None] * max(0, SLOT_COUNT - len(pinned))
        self._names = tuple(
            name or DEFAULT_SESSIONS[i] for i, name in enumerate(names)
        )
        self._live: set[str] = set()

    @property
    def slots(self) -> tuple[str, ...]:
        return self._names

    def session_for(self, slot: int) -> str | None:
        """The session this key means - whether or not it exists yet."""
        if 0 <= slot < SLOT_COUNT:
            return self._names[slot]
        return None

    def slot_of(self, session: str | None) -> int | None:
        if session is None:
            return None
        try:
            return self._names.index(session)
        except ValueError:
            return None

    def label(self, slot: int) -> str:
        return SLOT_LABELS[slot] if 0 <= slot < SLOT_COUNT else "--"

    def refresh(self) -> None:
        self._live = {session.name for session in self._tmux.sessions()}

    def exists(self, slot: int) -> bool:
        name = self.session_for(slot)
        return bool(name) and name in self._live

    def create_for(self, slot: int) -> str | None:
        """Make this slot's session exist, and return its name."""
        name = self.session_for(slot)
        if name is None:
            return None
        if name in self._live:
            return name
        if not self._tmux.new_session(name):
            log.error("could not create session %s", name)
            return None
        self._live.add(name)
        log.info("created session %s for %s", name, self.label(slot))
        return name

    def state_of(self, slot: int) -> SlotState:
        """What the deck should show for this slot."""
        name = self.session_for(slot)
        if name is None or name not in self._live:
            return SlotState.EMPTY

        # A bell or unseen activity is the "something happened where you are
        # not looking" signal, so it outranks merely being busy.
        attached = self._tmux.attached_session()
        for window in self._tmux.windows(name):
            if window.bell or (window.activity and name != attached):
                return SlotState.ATTENTION

        from .presence import is_busy  # local: presence imports this module

        if any(is_busy(p.command) for p in self._tmux.panes(name)):
            return SlotState.WORKING
        return SlotState.IDLE

    def current_session(self) -> str | None:
        attached = self._tmux.attached_session()
        if attached:
            return attached
        return next((name for name in self._names if name in self._live), None)
