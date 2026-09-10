"""Routes deck events to actions."""

from __future__ import annotations

import logging
import queue
import time

from . import actions
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
        self._gestures = GestureRecognizer(config.double_tap_window)
        self._presence = PresenceMonitor(tmux, self._slots)
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

    def _announce(self, action: str, args: dict) -> None:
        match action:
            case "summon":
                slot = args.get("slot", 0)
                session = self._slots.session_for(slot)
                if session:
                    self._face.toast(f"{self._slots.label(slot)} - {session}")
            case "interrupt":
                slot = args.get("slot", 0)
                if self._slots.session_for(slot):
                    self._face.toast(f"{self._slots.label(slot)} interrupted")
            case "launch_agent":
                where = "split" if args.get("split") else "here"
                self._face.toast(f"{self._config.launch_command} - {where}")
            case "new_window":
                self._face.toast("new window")

    def handle_encoder(self, delta: int) -> None:
        actions.cycle_pane(delta)(self._context)

    def _handle(self, event: object, now: float) -> None:
        match event:
            case KeyEvent():
                self._presence.note_input(now)
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
                self._presence.note_input(now)
                log.debug("encoder %+d", delta)
                self.handle_encoder(delta)

            for key, gesture in self._gestures.tick(time.monotonic()):
                self.dispatch(key, gesture)

            if now - last_refresh >= REFRESH_INTERVAL:
                self._slots.refresh()
                self._face.apply(self._presence.evaluate(now))
                last_refresh = now

    def stop(self) -> None:
        self._running = False
