"""Open Deck bridge daemon - the translation layer.

Device (semantic events) <-> this <-> harness (keystrokes / tmux / shell).

The device knows nothing about Claude Code, Grok or OpenCode; all of that
lives here in swappable JSON profiles. See docs/product-spec.md.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import queue
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import actions
from .device import Device
from .hookserver import DEFAULT_PORT, HookServer
from .state import BLOCKED, DONE, ERROR, IDLE, RUN, Approval, DeckState

log = logging.getLogger("opendeck")

PROFILE_DIR = Path(__file__).resolve().parent.parent / "profiles"

AGENT_KEYS = {"KEY_AGENT1": 0, "KEY_AGENT2": 1, "KEY_AGENT3": 2, "KEY_AGENT4": 3}


class Bridge:
    def __init__(self, profile_name: str, port: str | None, hook_port: int):
        self.profile = self._load_profile(profile_name)
        self.state = DeckState()
        self.device = Device(port)
        self.hooks = HookServer(self.on_hook, hook_port)
        self.mode = "DASHBOARD"
        self._hold_fired: dict[str, bool] = {}
        self._last_push = 0.0
        self._last_approve_line: str | None = None
        self._dirty = True

    # ---------- profile ----------
    def _load_profile(self, name: str) -> dict:
        path = PROFILE_DIR / f"{name}.json"
        if not path.exists():
            log.error("profile not found: %s", path)
            sys.exit(1)
        with open(path) as f:
            profile = json.load(f)
        log.info("loaded profile: %s", profile.get("name", name))
        return profile

    def action_for(self, key: str, layer: str) -> dict:
        return (self.profile.get("actions", {}).get(key, {}) or {}).get(layer, {})

    # ---------- sending keys to an agent ----------
    def send_to_agent(self, slot, keys: str) -> None:
        """Deliver a keystroke to one agent's terminal.

        Prefers `tmux send-keys` when we know the target: it delivers straight
        to that pane without stealing focus or needing Accessibility access.
        Falls back to focus + synthetic keystroke otherwise.
        """
        if slot and slot.target and slot.target.startswith("tmux:"):
            target = shlex.quote(slot.target[5:])
            subprocess.run(f"tmux send-keys -t {target} {keys}",
                           shell=True, capture_output=True, check=False)
            return
        if slot and slot.target:
            actions.focus_target(slot.target)
            time.sleep(0.12)
        actions.keystroke([keys.lower()])

    # ---------- hook events from harnesses ----------
    def on_hook(self, event: str, payload: dict) -> None:
        session = payload.get("session_id") or payload.get("sessionId") or "unknown"
        cwd = payload.get("cwd", "")
        slot = self.state.slot_for_session(session, cwd)
        if slot is None:
            log.debug("no free slot for session %s", session)
            return

        # Remember where this session lives so we can send keys back to it.
        tmux_target = payload.get("tmux_target") or os.environ.get("OPENDECK_TMUX_TARGET")
        if tmux_target:
            slot.target = f"tmux:{tmux_target}"

        event = event.lower()
        if event in ("sessionstart", "session_start"):
            slot.status = IDLE
            slot.started = None
        elif event in ("userpromptsubmit", "user_prompt_submit"):
            slot.status = RUN
            slot.started = time.time()
        elif event in ("pretooluse", "pre_tool_use"):
            slot.status = RUN
            if not slot.started:
                slot.started = time.time()
            slot.last_tool = payload.get("tool_name", "")
            ti = payload.get("tool_input", {}) or {}
            slot.last_file = ti.get("file_path") or ti.get("path") or ""
        elif event == "notification":
            # Claude Code fires Notification both for permission requests and
            # for plain idle nudges; only the former should block the deck.
            msg = (payload.get("message") or "").lower()
            if "permission" in msg or "approve" in msg or "waiting for your input" in msg:
                slot.status = BLOCKED
                ti = payload.get("tool_input", {}) or {}
                text = (ti.get("command") or ti.get("file_path")
                        or payload.get("message") or "")
                self.state.add_approval(Approval(
                    slot=slot.index,
                    agent=slot.name,
                    tool=payload.get("tool_name", "?"),
                    text=str(text)[:300],
                ))
                self.mode = "APPROVE"
        elif event == "stop":
            slot.status = DONE
            slot.started = None
        elif event in ("subagentstop", "subagent_stop"):
            pass
        elif event in ("sessionend", "session_end"):
            self.state.release_session(session)
        elif event == "error":
            slot.status = ERROR

        # Optional: harness-reported context usage, if the hook payload carries it.
        ctx = payload.get("context_percent") or payload.get("ctx_pct")
        if ctx is not None:
            try:
                slot.ctx_pct = max(0, min(100, int(float(ctx))))
            except (TypeError, ValueError):
                pass

        self._dirty = True

    # ---------- device events ----------
    def on_key(self, key: str, edge: str) -> None:
        if edge == "DOWN":
            self._hold_fired[key] = False
            return
        if edge == "HOLD":
            self._hold_fired[key] = True
            self.dispatch(key, "hold")
            return
        if edge == "UP" and not self._hold_fired.get(key):
            self.dispatch(key, "tap")

    def dispatch(self, key: str, layer: str) -> None:
        log.info("%s %s", key, layer)

        # Approval mode intercepts ENTER/CANCEL - they answer the prompt rather
        # than doing their normal job. Both map to the harness's own native keys.
        if self.mode == "APPROVE" and self.state.current_approval:
            ap = self.state.current_approval
            slot = self.state.slots[ap.slot]
            if key == "KEY_ENTER":
                self.send_to_agent(slot, "Enter")
                log.info("approved %s for %s", ap.tool, ap.agent)
                self.state.pop_approval()
                slot.status = RUN
                slot.started = slot.started or time.time()
                self._after_approval()
                return
            if key == "KEY_CANCEL":
                self.send_to_agent(slot, "Escape")
                log.info("denied %s for %s", ap.tool, ap.agent)
                self.state.pop_approval()
                slot.status = RUN
                self._after_approval()
                return

        # Agent keys: tap selects+focuses, hold interrupts that agent in place.
        if key in AGENT_KEYS:
            idx = AGENT_KEYS[key]
            slot = self.state.slots[idx]
            self.state.selection = idx
            if layer == "hold":
                self.send_to_agent(slot, "Escape")
                log.info("interrupted %s", slot.name)
            else:
                actions.focus_target(slot.target or "")
                if slot.status == DONE:
                    slot.status = IDLE
            self._dirty = True
            return

        if key == "KEY_TERM" and layer == "tap":
            slot = self.state.slots[self.state.selection]
            actions.focus_target(slot.target or "")
            self._dirty = True
            return

        actions.run(self.action_for(key, layer),
                    {"slot": self.state.selection + 1,
                     "target": (self.state.slots[self.state.selection].target or "")})

    def _after_approval(self) -> None:
        if self.state.current_approval:
            self.mode = "APPROVE"      # more queued
        else:
            self.mode = "DASHBOARD"
            self.device.send("APPROVE_CLEAR")
        self._dirty = True

    def on_encoder(self, delta: int) -> None:
        if self.mode == "DASHBOARD":
            self.state.selection = (self.state.selection + delta) % 4
        self._dirty = True

    # ---------- display push ----------
    def push_display(self) -> None:
        for slot in self.state.slots:
            self.device.send(slot.to_wire())

        ap = self.state.current_approval
        if ap and self.mode == "APPROVE":
            # Queue depth goes in its own message: baking it into the APPROVE
            # line would make the request look "new" every time another agent
            # blocks, resetting the scroll of the one being read right now.
            self.device.send(f"APPROVE_COUNT {len(self.state.approvals)}")
            line = f"APPROVE {ap.agent} {1 if ap.dangerous else 0} {ap.tool} {ap.text}"
            # Only send when it actually changes: re-sending would restart the
            # alert blink and reset the user's scroll position on every refresh.
            if line != self._last_approve_line:
                self.device.send(line)
                self._last_approve_line = line
        else:
            self._last_approve_line = None
        self.device.send(f"MODE {self.mode}")

    def _idle_check(self) -> None:
        """Drop to the ambient screen when nothing is happening (burn-in)."""
        busy = any(s.status in (RUN, BLOCKED, DONE) for s in self.state.slots)
        if not busy and self.mode == "DASHBOARD":
            if time.time() - self._last_activity > 300:
                self.mode = "AMBIENT"
                self._dirty = True
        elif busy and self.mode == "AMBIENT":
            self.mode = "DASHBOARD"
            self._dirty = True

    # ---------- main loop ----------
    def run(self) -> None:
        self.device.start()
        self.hooks.start()
        self._last_activity = time.time()
        log.info("bridge running - waiting for device and hooks")

        while True:
            try:
                kind, a, b = self.device.events.get(timeout=0.25)
                if kind == "key":
                    self._last_activity = time.time()
                    if self.mode == "AMBIENT":
                        self.mode = "DASHBOARD"
                    self.on_key(a, b)
                elif kind == "encoder":
                    self._last_activity = time.time()
                    if self.mode == "AMBIENT":
                        self.mode = "DASHBOARD"
                    self.on_encoder(a)
                elif kind == "connected":
                    self._dirty = True
                    self.push_display()
            except queue.Empty:
                pass

            self._idle_check()

            # Re-push at 2Hz so elapsed timers tick, plus immediately on change.
            now = time.time()
            if self._dirty or now - self._last_push > 0.5:
                if self.device.connected:
                    self.push_display()
                self._dirty = False
                self._last_push = now


def main() -> None:
    ap = argparse.ArgumentParser(description="Open Deck bridge daemon")
    ap.add_argument("--profile", default="claude-code", help="harness profile name")
    ap.add_argument("--port", default=None, help="serial port (default: autodetect)")
    ap.add_argument("--hook-port", type=int, default=DEFAULT_PORT)
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)-16s %(levelname)-5s %(message)s",
        datefmt="%H:%M:%S",
    )

    bridge = Bridge(args.profile, args.port, args.hook_port)
    try:
        bridge.run()
    except KeyboardInterrupt:
        log.info("shutting down")


if __name__ == "__main__":
    main()
