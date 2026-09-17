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
        action(self._context)
        self._announce(binding.action, binding.args)
        # Acting changes the fleet, so repaint the strip now rather than
        # leaving it stale until the next refresh tick.
        self._slots.refresh()
        self._face.show_slots(self._slots.strip())

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
        count = title = None
        slot = SLOT_KEYS.index(key) if key in SLOT_KEYS else None
        if slot is not None and self._slots.exists(slot):
            live = self._tmux.panes(self._slots.session_for(slot))
            count = len(live)
            title = harness.session_title(live)
        lines = peek.lines_for(key, self._slots, self._config.launch_command,
                               count, title)
        self._peeking = True
        self._face.show_peek(peek.payload(lines))

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
        actions.cycle_pane(delta)(self._context)
        self._push_pane_list()

    def _handle(self, event: object, now: float) -> None:
        if isinstance(event, KeyEvent):
            # Peek tracks the finger rather than the gesture: shown once the
            # hold registers, taken down the moment the key comes up.
            if event.edge is Edge.HOLD:
                self._show_peek(event.key)
            elif event.edge is Edge.UP and self._peeking:
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

            if now - last_refresh >= REFRESH_INTERVAL:
                self._slots.refresh()
                self._announce_presence(self._presence.evaluate(now))
                self._face.show_slots(self._slots.strip())
                self._face.keepalive()
                last_refresh = now

    def stop(self) -> None:
        self._running = False
        if self._hooks is not None:
            self._hooks.stop()
            self._hooks = None
