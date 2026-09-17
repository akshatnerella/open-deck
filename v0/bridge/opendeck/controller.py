"""Routes deck events to actions."""

from __future__ import annotations

import logging
import queue
import time

from . import actions, harness, panes, peek
from .agents import AgentRegistry
from .hookserver import DEFAULT_PORT, HookServer
from .actions import Context
from .config import SLOT_KEYS, Config
from .events import Connected, Disconnected, Edge, EncoderEvent, Heartbeat, KeyEvent
from .face import Face
from .presence import PresenceMonitor, State
from .gestures import GestureRecognizer
from .slots import SlotTable
from .terminal import Terminal
from .tmux import Tmux
from .transport import SerialTransport

log = logging.getLogger(__name__)

REFRESH_INTERVAL = 2.0
POLL_TIMEOUT = 0.05

#: How long a pane list stays up after you stop touching the deck. It is a
#: look-and-go tool, not a mode - walk away mid-browse and the deck goes back
#: to being a face.
BROWSE_TIMEOUT = 2.5


class Controller:
    def __init__(
        self,
        config: Config,
        transport: SerialTransport,
        tmux: Tmux,
        terminal: Terminal,
    ) -> None:
        self._config = config
        self._transport = transport
        self._tmux = tmux
        self._peeking = False
        #: Keys physically down right now, so a gesture can be modified by
        #: another key being held. The only chord: ENTER + double-tap TERM.
        self._down: set[str] = set()
        #: Browsing state. The encoder moves a cursor through a session's
        #: panes without going anywhere; ENTER commits. Looking should not
        #: move you - the same reason holding a key is free.
        self._browse_session: str | None = None
        self._browse_panes: list = []
        self._browse_at = 0
        self._browse_expires = 0.0
        self._slots = SlotTable(tmux, config.sessions)
        self._context = Context(tmux=tmux, terminal=terminal, slots=self._slots, config=config)
        self._gestures = GestureRecognizer(
            config.double_tap_window,
            frozenset(
                key for key, gestures in config.bindings.items() if "double" in gestures
            ),
        )
        self._agents = AgentRegistry()
        self._presence = PresenceMonitor(tmux, self._slots, self._agents)
        # Bound lazily in run(): constructing a Controller must not claim a
        # port, or every test that builds one fights for 8787.
        self._hooks: HookServer | None = None
        self._face = Face(transport)
        self._running = False

    @property
    def slots(self) -> SlotTable:
        return self._slots

    def dispatch(self, key: str, gesture: str) -> None:
        # While a list is up, ENTER means "go to the highlighted pane". Only
        # then - everywhere else it is still a plain Enter.
        if key == "KEY_ENTER" and gesture == "tap" and self._browse_session:
            if self._commit_browse():
                return

        binding = self._config.binding(key, gesture)
        if binding is None:
            log.debug("unbound: %s %s", key, gesture)
            return
        try:
            action = actions.build(binding.action, binding.args)
        except (KeyError, TypeError) as exc:
            log.error("bad binding for %s %s: %s", key, gesture, exc)
            return
        log.info("%s %s -> %s", key, gesture, binding.action)
        args = dict(binding.args)
        # Holding ENTER turns a new pane sideways-into-downwards. Resolved
        # here rather than in the action, so the action stays a plain verb.
        if binding.action == "split_pane" and "KEY_ENTER" in self._down:
            args["below"] = True
            action = actions.build(binding.action, args)

        action(self._context)
        self._announce(binding.action, args)

    def _announce(self, action: str, args: dict) -> None:
        if action == "summon":
            slot = args.get("slot", 0)
            # A key always names a session now, so "does it exist" is the
            # question, not "is it bound".
            if self._slots.exists(slot):
                self._push_pane_list(self._slots.session_for(slot))
        elif action == "interrupt":
            slot = args.get("slot", 0)
            if self._slots.exists(slot):
                self._face.toast(f"{self._slots.label(slot)} interrupted")
        elif action == "launch_agent":
            where = "split" if args.get("split") else "here"
            self._face.toast(f"{self._config.launch_command} - {where}")
        elif action == "new_window":
            self._face.toast("new window")
        elif action == "close_pane":
            session = self._slots.current_session()
            if session and not self._tmux.is_idle_shell(session):
                # Say why nothing happened, or the key looks broken.
                self._face.toast("still running")

    def _announce_presence(self, snapshot) -> None:
        if not self._face.apply(snapshot):
            return
        # Naming the session is the whole point of the alert - "something wants
        # you" is not actionable, "OWL wants you" is.
        if snapshot.state is State.ALERT and snapshot.attention_session:
            slot = self._slots.slot_of(snapshot.attention_session)
            name = self._slots.label(slot) if slot is not None else snapshot.attention_session
            self._face.toast(f"{name} wants you")

    def on_hook(self, event: str, payload: dict) -> None:
        target = payload.get("tmux_target") or ""
        session = target.split(":")[0] if target else ""
        self._agents.record(event, target, session, payload)
        self._dirty = True

    def _show_peek(self, key: str) -> None:
        self._slots.refresh()
        live: list = []
        windows: list = []
        slot = SLOT_KEYS.index(key) if key in SLOT_KEYS else None
        if slot is not None and self._slots.exists(slot):
            session = self._slots.session_for(slot)
            live = self._tmux.panes(session)
            windows = self._tmux.windows(session)
        if slot is not None and live:
            # Hold an animal and the dial browses *that* session, so you can
            # look inside one you are not in and jump straight to a pane.
            self._browse_session = self._slots.session_for(slot)
            self._browse_panes = live
            self._browse_at = next((i for i, p in enumerate(live) if p.active), 0)
            self._browse_expires = time.monotonic() + BROWSE_TIMEOUT

        lines = peek.lines_for(key, self._slots, self._config.launch_command,
                               live, windows)
        self._peeking = True
        cursor = self._browse_at + 1 if self._browse_session else -1
        self._face.show_peek(peek.payload(lines, cursor=cursor))

    def _push_pane_list(self, session: str | None = None) -> None:
        session = session or self._slots.current_session()
        if session is None:
            return
        slot = self._slots.slot_of(session)
        label = self._slots.label(slot) if slot is not None else "--"
        pane_list = self._context.tmux.panes(session)
        position = next((i + 1 for i, p in enumerate(pane_list) if p.active), 0)
        title = f"{label} {session} {position}/{len(pane_list)}"
        by_target = {a.target.split(":", 1)[1]: a
                     for a in self._agents.in_session(session)
                     if ":" in a.target}
        self._face.show_list(
            panes.build_list(title, pane_list,
                             self._context.tmux.windows(session), agents=by_target)
        )

    def handle_encoder(self, delta: int) -> None:
        """Move the cursor. Turning the dial no longer takes you anywhere."""
        session = self._browse_session or self._slots.current_session()
        if session is None:
            return

        if session != self._browse_session or not self._browse_panes:
            self._begin_browse(session)
        if not self._browse_panes:
            return

        self._browse_at = (self._browse_at + delta) % len(self._browse_panes)
        self._browse_expires = time.monotonic() + BROWSE_TIMEOUT

        # Follow along when you are browsing the session you are already in:
        # the Mac is the preview, and without it you are choosing from names
        # on a tiny screen with nothing to look at. Browsing *another*
        # session still waits for ENTER - a dial should never yank you out of
        # what you are reading.
        if session == self._tmux.attached_session():
            self._tmux.select_pane(session, self._browse_panes[self._browse_at])

        self._push_browse()

    def _begin_browse(self, session: str) -> None:
        self._browse_session = session
        self._browse_panes = self._tmux.panes(session)
        # Start where you already are, so a single detent means "the next one"
        # rather than "somewhere arbitrary".
        self._browse_at = next(
            (i for i, p in enumerate(self._browse_panes) if p.active), 0
        )

    def _push_browse(self) -> None:
        session = self._browse_session
        if session is None:
            return
        slot = self._slots.slot_of(session)
        label = self._slots.label(slot) if slot is not None else "--"
        windows = self._tmux.windows(session)
        lines = peek.lines_for(SLOT_KEYS[slot] if slot is not None else "KEY_AGENT1",
                               self._slots, self._config.launch_command,
                               self._browse_panes, windows)
        self._peeking = True
        self._face.show_peek(peek.payload(lines, cursor=self._browse_at + 1))

    def _commit_browse(self) -> bool:
        """Go to the pane under the cursor. True if there was one."""
        if self._browse_session is None or not self._browse_panes:
            return False
        session = self._browse_session
        pane = self._browse_panes[self._browse_at]

        if session != self._tmux.attached_session():
            self._tmux.switch(session)
            self._context.terminal.focus()
        self._tmux.select_pane(session, pane)
        log.info("go to %s:%s", session, pane.target)

        self._end_browse()
        return True

    def _end_browse(self) -> None:
        self._browse_session = None
        self._browse_panes = []
        self._browse_at = 0
        if self._peeking:
            self._peeking = False
            self._face.clear_peek()

    def _handle(self, event: object, now: float) -> None:
        if isinstance(event, KeyEvent):
            # Peek tracks the finger rather than the gesture: shown once the
            # hold registers, taken down the moment the key comes up.
            if event.edge is Edge.DOWN:
                self._down.add(event.key)
            elif event.edge is Edge.UP:
                self._down.discard(event.key)

            if event.edge is Edge.HOLD:
                self._show_peek(event.key)
            elif event.edge is Edge.UP and self._peeking and not self._browse_session:
                self._peeking = False
                self._face.clear_peek()
            for key, gesture in self._gestures.feed(event, now):
                self.dispatch(key, gesture)
        elif isinstance(event, Connected):
            log.info("deck connected on %s", event.port)
            self._slots.refresh()
            self._face.reset()
        elif isinstance(event, Disconnected):
            log.warning("deck disconnected")

    def _drain(self, first: object | None) -> tuple[list[object], int]:
        """Collect everything queued, summing encoder deltas.

        Each detent otherwise costs three tmux round-trips, so a fast spin
        backlogs and every queued step recomputes "next pane" from state the
        previous step has already changed - landing unpredictably. Summing the
        deltas turns a spin into one correctly-sized jump.
        """
        events: list[object] = []
        delta = 0
        pending = [first] if first is not None else []
        while True:
            for event in pending:
                if isinstance(event, EncoderEvent):
                    delta += event.delta
                else:
                    events.append(event)
            try:
                pending = [self._transport.events.get_nowait()]
            except queue.Empty:
                return events, delta

    def run(self) -> None:
        self._running = True
        if self._hooks is None:
            self._hooks = HookServer(self.on_hook, DEFAULT_PORT)
            self._hooks.start()
        self._slots.refresh()
        last_refresh = time.monotonic()

        while self._running:
            now = time.monotonic()
            try:
                first = self._transport.events.get(timeout=POLL_TIMEOUT)
            except queue.Empty:
                first = None

            events, delta = self._drain(first)
            for event in events:
                self._handle(event, now)

            if delta:
                log.debug("encoder %+d", delta)
                self.handle_encoder(delta)

            for key, gesture in self._gestures.tick(time.monotonic()):
                self.dispatch(key, gesture)

            # A held key keeps its own panel up, so only start the countdown
            # once nothing is being pressed.
            if (self._browse_session and not self._down
                    and now > self._browse_expires):
                self._end_browse()

            if now - last_refresh >= REFRESH_INTERVAL:
                self._slots.refresh()
                self._announce_presence(self._presence.evaluate(now))
                self._face.keepalive()
                last_refresh = now

    def stop(self) -> None:
        self._running = False
        if self._hooks is not None:
            self._hooks.stop()
            self._hooks = None
