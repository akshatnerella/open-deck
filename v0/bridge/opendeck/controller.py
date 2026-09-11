"""Routes deck events to actions."""

from __future__ import annotations

import logging
import queue
import time

from . import actions, panes
from .agents import AgentRegistry
from .hookserver import DEFAULT_PORT, HookServer
from .actions import Context
from .config import Config
from .events import Connected, Disconnected, EncoderEvent, Heartbeat, KeyEvent
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
        if gesture == "tap" and key in ("KEY_ENTER", "KEY_CANCEL"):
            # An agent stopped on a permission prompt owns these keys: the
            # deck's whole reason for showing the request is to answer it.
            if self._answer_approval(key == "KEY_ENTER"):
                return

        log.info("%s %s -> %s", key, gesture, binding.action)
        action(self._context)
        self._announce(binding.action, binding.args)

    def _announce(self, action: str, args: dict) -> None:
        match action:
            case "summon":
                session = self._slots.session_for(args.get("slot", 0))
                if session:
                    self._push_pane_list(session)
            case "interrupt":
                slot = args.get("slot", 0)
                if self._slots.session_for(slot):
                    self._face.toast(f"{self._slots.label(slot)} interrupted")
            case "launch_agent":
                where = "split" if args.get("split") else "here"
                self._face.toast(f"{self._config.launch_command} - {where}")
            case "new_window":
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

    def _push_approval(self) -> None:
        approval = self._agents.current_approval
        if approval is None:
            self._transport.send("APPROVE_CLEAR")
            return
        queued = len(self._agents.approvals)
        self._transport.send(f"APPROVE_COUNT {queued}")
        slot = self._slots.slot_of(approval.target.split(":")[0])
        who = self._slots.label(slot) if slot is not None else approval.agent
        self._transport.send(
            f"APPROVE {who} {1 if approval.dangerous else 0} "
            f"{approval.tool} {approval.text}"
        )

    def _answer_approval(self, approved: bool) -> bool:
        """Answer a pending permission request. True if one was pending."""
        approval = self._agents.current_approval
        if approval is None:
            return False
        key = "Enter" if approved else "Escape"
        self._context.tmux.send_keys(approval.target, key)
        log.info("%s %s on %s", "approved" if approved else "denied",
                 approval.tool, approval.target)
        self._agents.resolve(approval.target, approved)
        self._push_approval()
        self._dirty = True
        return True

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
        match event:
            case KeyEvent():
                for key, gesture in self._gestures.feed(event, now):
                    self.dispatch(key, gesture)
            case Connected(port=port):
                log.info("deck connected on %s", port)
                self._slots.refresh()
                self._face.reset()
            case Disconnected():
                log.warning("deck disconnected")
            case Heartbeat():
                pass

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
                self._push_approval()
                self._face.keepalive()
                last_refresh = now

    def stop(self) -> None:
        self._running = False
        if self._hooks is not None:
            self._hooks.stop()
            self._hooks = None
