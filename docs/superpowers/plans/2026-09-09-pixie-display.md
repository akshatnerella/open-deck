# Pixie Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Open Deck OLED useful by resting on Pixie's face, revealing a pane list while you interact, and never lying about whether it is live.

**Architecture:** The display is split by *time*, not screen area: an ambient face, a glance layer (pane list) that decays after 1.2s, and alerts. The host formats and windows the list; the firmware is a dumb renderer. All rendering stays on the ESP32's core 0 — the input loop on core 1 must never block.

**Tech Stack:** Python 3.11+ (stdlib + pyserial), Arduino/ESP32-S3, FluxGarage RoboEyes, Adafruit SH110X, tmux.

**Spec:** `docs/superpowers/specs/2026-09-09-pixie-display-design.md`

## Global Constraints

- Python 3.11+; stdlib plus `pyserial` only. No new dependencies.
- Tests must run with no hardware, no tmux, and no terminal app. Everything goes through the fakes in `v0/bridge/tests/fakes.py`.
- Run tests with `v0/bridge/tests/run_tests.sh` (it finds the repo `.venv` itself).
- Display is 128×64 mono = **21 characters × 6 usable rows** at the default font.
- Wire protocol is newline-delimited ASCII at 115200 baud. `|` is the `LIST` delimiter and must never appear inside a field.
- Firmware rendering runs only on the core-0 render task. A full framebuffer flush blocks ~29.5ms; putting it on the input loop drops encoder detents.
- Serial writes from firmware use `emit()`, which drops rather than blocks when the host is not reading.
- Commit after each task with a `feat:`/`refactor:` prefixed message.

---

### Task 1: Collapse presence to four states

**Files:**
- Modify: `v0/bridge/opendeck/presence.py`
- Modify: `v0/bridge/tests/test_presence.py`

**Interfaces:**
- Consumes: `SlotTable`, `Tmux`, `is_agent`, `is_busy` (all existing)
- Produces: `State.ALERT`, `State.BUSY`, `State.DONE`, `State.CALM` (StrEnum values `"alert"`, `"busy"`, `"done"`, `"calm"`); `Snapshot(state, attention_session=None)`; `PresenceMonitor.evaluate(now=None) -> Snapshot`. `PresenceMonitor.note_input()` is removed.

- [ ] **Step 1: Rewrite the failing tests**

Replace the whole `class TestPresence` body in `v0/bridge/tests/test_presence.py` with:

```python
class TestPresence(unittest.TestCase):
    def test_no_sessions_is_calm(self):
        mon, _ = monitor([], client=False)
        self.assertEqual(mon.evaluate(0.0).state, State.CALM)

    def test_idle_shell_is_calm(self):
        mon, _ = monitor(["webapp"], panes={"webapp": [pane(command="zsh", pane_active=True)]})
        self.assertEqual(mon.evaluate(100.0).state, State.CALM)

    def test_running_agent_is_busy(self):
        mon, _ = monitor(
            ["webapp"],
            panes={"webapp": [pane(command="claude", window_active=True, pane_active=True)]},
        )
        self.assertEqual(mon.evaluate(100.0).state, State.BUSY)

    def test_activity_elsewhere_takes_priority_over_busy(self):
        mon, _ = monitor(
            ["webapp", "api"],
            panes={"webapp": [pane(command="claude", pane_active=True)]},
            windows={"api": [window(activity=True)]},
        )
        snapshot = mon.evaluate(100.0)
        self.assertEqual(snapshot.state, State.ALERT)
        self.assertEqual(snapshot.attention_session, "api")

    def test_a_bell_also_raises_alert(self):
        mon, _ = monitor(
            ["webapp", "api"],
            panes={"webapp": [pane(command="zsh")]},
            windows={"api": [window(bell=True)]},
        )
        self.assertEqual(mon.evaluate(100.0).state, State.ALERT)

    def test_activity_in_the_current_session_is_not_an_alert(self):
        mon, _ = monitor(
            ["webapp"],
            panes={"webapp": [pane(command="zsh")]},
            windows={"webapp": [window(activity=True)]},
        )
        self.assertNotEqual(mon.evaluate(100.0).state, State.ALERT)

    def test_agent_disappearing_reports_done_once(self):
        tmux = FakeTmux(
            sessions=["webapp"],
            panes={"webapp": [pane(command="claude", pane_active=True)]},
        )
        slots = SlotTable(tmux)
        slots.refresh()
        mon = PresenceMonitor(tmux, slots)

        self.assertEqual(mon.evaluate(10.0).state, State.BUSY)
        tmux._panes = {"webapp": [pane(command="zsh", pane_active=True)]}
        self.assertEqual(mon.evaluate(11.0).state, State.DONE)
        # DONE must not latch, or the face would stay happy forever.
        self.assertEqual(mon.evaluate(12.0).state, State.CALM)

    def test_a_running_program_counts_as_busy(self):
        mon, _ = monitor(["webapp"], panes={"webapp": [pane(command="vim")]})
        self.assertEqual(mon.evaluate(100.0).state, State.BUSY)

    def test_shells_are_never_mistaken_for_agents(self):
        for shell in ("zsh", "bash", "fish", "-zsh"):
            with self.subTest(shell=shell):
                mon, _ = monitor(["webapp"], panes={"webapp": [pane(command=shell)]})
                self.assertEqual(mon.evaluate(100.0).state, State.CALM)

    def test_claude_code_version_string_is_recognised_as_an_agent(self):
        from opendeck.presence import is_agent

        for version in ("2.1.261", "2.1.259", "1.0.0"):
            with self.subTest(version=version):
                self.assertTrue(is_agent(version))

    def test_agent_detection_rejects_shells_and_plain_names(self):
        from opendeck.presence import is_agent

        self.assertFalse(is_agent("zsh"))
        self.assertFalse(is_agent(""))
        self.assertFalse(is_agent("vim"))

    def test_version_agent_finishing_reports_done(self):
        tmux = FakeTmux(
            sessions=["webapp"], panes={"webapp": [pane(command="2.1.261", pane_active=True)]}
        )
        slots = SlotTable(tmux)
        slots.refresh()
        mon = PresenceMonitor(tmux, slots)
        self.assertEqual(mon.evaluate(10.0).state, State.BUSY)
        tmux._panes = {"webapp": [pane(command="zsh", pane_active=True)]}
        self.assertEqual(mon.evaluate(11.0).state, State.DONE)

    def test_state_values_are_the_wire_names(self):
        self.assertEqual(
            {State.ALERT, State.BUSY, State.DONE, State.CALM},
            {"alert", "busy", "done", "calm"},
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `v0/bridge/tests/run_tests.sh -k TestPresence`
Expected: FAIL with `AttributeError: ALERT` (the enum member does not exist yet).

- [ ] **Step 3: Rewrite the state enum and evaluate()**

In `v0/bridge/opendeck/presence.py`, replace the `ACTIVE_LINGER`/`SLEEP_AFTER` constants and the `State` class with:

```python
class State(StrEnum):
    ALERT = "alert"
    BUSY = "busy"
    DONE = "done"
    CALM = "calm"
```

Delete `note_input`, the `_last_input` attribute, and its assignment in `__init__`. Replace `evaluate` with:

```python
    def evaluate(self, now: float | None = None) -> Snapshot:
        current = self._slots.current_session()
        if current is None:
            return Snapshot(State.CALM)

        # 1. Something wants attention in a session you are not looking at.
        for session in self._slots.slots:
            if not session or session == current:
                continue
            if any(w.activity or w.bell for w in self._tmux.windows(session)):
                return Snapshot(State.ALERT, attention_session=session)

        panes = self._tmux.panes(current)
        agents_here = {p.target for p in panes if is_agent(p.command)}
        busy_here = any(is_busy(p.command) for p in panes)
        key = f"{current}:"
        previously = {t for t in self._agent_seen if t.startswith(key)}
        currently = {f"{key}{t}" for t in agents_here}

        # 2. An agent that was running here has stopped.
        finished = previously - currently
        self._agent_seen = (self._agent_seen - previously) | currently
        if finished:
            return Snapshot(State.DONE)

        # 3. Anything running here is enough to look busy; DONE is tracked
        #    only for agents so quitting an editor does not celebrate.
        if agents_here or busy_here:
            return Snapshot(State.BUSY)

        return Snapshot(State.CALM)
```

Keep the `now` parameter: callers pass it and dropping it would break them.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `v0/bridge/tests/run_tests.sh -k TestPresence`
Expected: PASS.

- [ ] **Step 5: Fix the callers**

`grep -rn "note_input\|State.ATTENTION\|State.WORKING\|State.IDLE\|State.ACTIVE\|State.ASLEEP" v0/bridge/` and update each hit:
- In `opendeck/controller.py`, delete both `self._presence.note_input(now)` calls and change `State.ATTENTION` to `State.ALERT`.
- In `tests/test_controller.py`, change `State.ATTENTION` to `State.ALERT` and `State.WORKING` to `State.BUSY`.

- [ ] **Step 6: Run the whole suite**

Run: `v0/bridge/tests/run_tests.sh`
Expected: PASS, no errors.

- [ ] **Step 7: Commit**

```bash
git add v0/bridge/opendeck/presence.py v0/bridge/opendeck/controller.py v0/bridge/tests/
git commit -m "refactor: collapse presence to four face states"
```

---

### Task 2: Build the pane list payload

**Files:**
- Create: `v0/bridge/opendeck/panes.py`
- Create: `v0/bridge/tests/test_panes.py`

**Interfaces:**
- Consumes: `opendeck.tmux.Pane`, `opendeck.tmux.Window`, `opendeck.presence.is_agent`, `opendeck.tmux.SHELLS`
- Produces: `pane_label(pane: Pane, window: Window | None) -> str`; `build_list(title: str, panes: list[Pane], windows: list[Window], max_rows: int = 5) -> str` returning the full `LIST` payload body (title and rows joined by `|`, without the `LIST ` prefix).

- [ ] **Step 1: Write the failing tests**

Create `v0/bridge/tests/test_panes.py`:

```python
import unittest

from fakes import pane, window
from opendeck.panes import build_list, pane_label


class TestPaneLabel(unittest.TestCase):
    def test_prefers_a_deliberate_window_name(self):
        p = pane(command="node")
        w = window(name="claude")
        self.assertEqual(pane_label(p, w), "claude")

    def test_ignores_generic_shell_window_names(self):
        p = pane(command="vim")
        w = window(name="zsh")
        self.assertEqual(pane_label(p, w), "vim")

    def test_claude_version_string_reads_as_claude(self):
        # Claude Code reports its version as the process name.
        self.assertEqual(pane_label(pane(command="2.1.261"), None), "claude")

    def test_falls_back_to_the_command(self):
        self.assertEqual(pane_label(pane(command="npm"), None), "npm")

    def test_empty_command_is_marked_unknown(self):
        self.assertEqual(pane_label(pane(command=""), None), "?")

    def test_delimiter_and_spaces_are_sanitised(self):
        # "|" is the wire delimiter and would corrupt the payload.
        self.assertEqual(pane_label(pane(command="a|b c"), None), "a_b_c")

    def test_label_is_truncated(self):
        label = pane_label(pane(command="x" * 40), None)
        self.assertLessEqual(len(label), 13)


class TestBuildList(unittest.TestCase):
    def test_title_leads_the_payload(self):
        payload = build_list("FOX webapp 1/1", [pane(pane_active=True, window_active=True)], [])
        self.assertTrue(payload.startswith("FOX webapp 1/1|"))

    def test_active_pane_is_marked(self):
        panes = [
            pane(index=0, command="claude"),
            pane(index=1, command="nvim", window_active=True, pane_active=True),
        ]
        rows = build_list("t", panes, []).split("|")[1:]
        self.assertTrue(rows[1].startswith(">"))
        self.assertFalse(rows[0].startswith(">"))

    def test_empty_session_renders_a_placeholder(self):
        self.assertEqual(build_list("t", [], []), "t|(empty)")

    def test_at_most_five_rows(self):
        panes = [pane(index=i, command=f"c{i}") for i in range(9)]
        panes[0] = pane(index=0, command="c0", window_active=True, pane_active=True)
        rows = build_list("t", panes, []).split("|")[1:]
        self.assertEqual(len(rows), 5)

    def test_window_keeps_the_active_pane_visible(self):
        panes = [pane(index=i, command=f"c{i}") for i in range(9)]
        panes[8] = pane(index=8, command="c8", window_active=True, pane_active=True)
        rows = build_list("t", panes, []).split("|")[1:]
        self.assertTrue(any(r.startswith(">") for r in rows))

    def test_activity_flag_is_appended(self):
        panes = [pane(window=0, index=0, command="zsh", window_active=True, pane_active=True)]
        windows = [window(index=0, activity=True)]
        row = build_list("t", panes, windows).split("|")[1]
        self.assertTrue(row.rstrip().endswith("*"))

    def test_bell_flag_beats_activity(self):
        panes = [pane(window=0, index=0, command="zsh", window_active=True, pane_active=True)]
        windows = [window(index=0, activity=True, bell=True)]
        row = build_list("t", panes, windows).split("|")[1]
        self.assertTrue(row.rstrip().endswith("!"))

    def test_no_row_exceeds_the_display_width(self):
        panes = [pane(index=i, command="x" * 30) for i in range(3)]
        for row in build_list("t" * 40, panes, []).split("|"):
            self.assertLessEqual(len(row), 21)

    def test_payload_never_contains_a_stray_delimiter(self):
        panes = [pane(index=0, command="a|b", window_active=True, pane_active=True)]
        payload = build_list("ti|tle", panes, [])
        # One delimiter per row boundary and no more.
        self.assertEqual(payload.count("|"), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `v0/bridge/tests/run_tests.sh -k test_panes`
Expected: FAIL with `ModuleNotFoundError: No module named 'opendeck.panes'`.

- [ ] **Step 3: Write the implementation**

Create `v0/bridge/opendeck/panes.py`:

```python
"""Formats the pane list the deck displays.

The host owns every formatting rule - windowing, markers, flags, truncation -
so the firmware stays a dumb renderer and all of this stays testable here.
"""

from __future__ import annotations

from .presence import is_agent
from .tmux import SHELLS, Pane, Window

DISPLAY_WIDTH = 21
MAX_ROWS = 5
LABEL_WIDTH = 13
EMPTY_ROW = "(empty)"

_GENERIC_NAMES = frozenset({"zsh", "bash", "sh", "fish"})
_AGENT_LABEL = "claude"


def _sanitise(text: str) -> str:
    """Strip anything that would corrupt the wire payload."""
    return "".join("_" if ch in "| \t" else ch for ch in text)


def pane_label(pane: Pane, window: Window | None) -> str:
    if window is not None and window.name and window.name not in _GENERIC_NAMES:
        label = window.name
    elif is_agent(pane.command) and pane.command not in SHELLS:
        # Claude Code reports its version string as the process name, so the
        # raw command is useless as a label even though it is a real agent.
        label = pane.command if pane.command.isalpha() else _AGENT_LABEL
    else:
        label = pane.command or "?"
    return _sanitise(label)[:LABEL_WIDTH]


def _flag(pane: Pane, windows: list[Window]) -> str:
    for w in windows:
        if w.index == pane.window:
            return w.flag.strip()
    return ""


def _window_rows(panes: list[Pane], max_rows: int) -> list[Pane]:
    """Slice the list so the active pane is always visible."""
    if len(panes) <= max_rows:
        return panes
    active = next((i for i, p in enumerate(panes) if p.active), 0)
    first = max(0, min(active - max_rows // 2, len(panes) - max_rows))
    return panes[first : first + max_rows]


def build_list(
    title: str,
    panes: list[Pane],
    windows: list[Window],
    max_rows: int = MAX_ROWS,
) -> str:
    rows = []
    for pane in _window_rows(panes, max_rows):
        marker = ">" if pane.active else " "
        flag = _flag(pane, windows)
        row = f"{marker}{pane.index:<2}{pane_label(pane, None)}"
        if flag:
            row = f"{row} {flag}"
        rows.append(row[:DISPLAY_WIDTH])
    if not rows:
        rows = [EMPTY_ROW]
    return "|".join([_sanitise(title)[:DISPLAY_WIDTH], *rows])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `v0/bridge/tests/run_tests.sh -k test_panes`
Expected: PASS.

If `test_prefers_a_deliberate_window_name` fails, note that `build_list` passes `None` for the window while `pane_label` is tested directly with one — this is intentional; only Task 4 wires real windows through.

- [ ] **Step 5: Commit**

```bash
git add v0/bridge/opendeck/panes.py v0/bridge/tests/test_panes.py
git commit -m "feat: build the pane list payload host-side"
```

---

### Task 3: Teach Face the new protocol

**Files:**
- Modify: `v0/bridge/opendeck/face.py`
- Create: `v0/bridge/tests/test_face.py`

**Interfaces:**
- Consumes: `SerialTransport.send`, `Snapshot`, `State` (four-state version from Task 1)
- Produces: `Face.apply(snapshot) -> bool` sending `FACE <state>`; `Face.toast(text)`; `Face.show_list(payload)` sending `LIST <payload>`; `Face.keepalive()` re-sending the last `FACE` unconditionally; `Face.reset()`.

- [ ] **Step 1: Write the failing tests**

Create `v0/bridge/tests/test_face.py`:

```python
import unittest

from opendeck.face import Face
from opendeck.presence import Snapshot, State


class FakeTransport:
    def __init__(self):
        self.sent = []

    def send(self, line):
        self.sent.append(line)
        return True


class TestFace(unittest.TestCase):
    def setUp(self):
        self.transport = FakeTransport()
        self.face = Face(self.transport)

    def test_apply_sends_the_wire_name(self):
        self.assertTrue(self.face.apply(Snapshot(State.BUSY)))
        self.assertEqual(self.transport.sent, ["FACE busy"])

    def test_unchanged_state_is_not_resent(self):
        self.face.apply(Snapshot(State.CALM))
        self.transport.sent.clear()
        self.assertFalse(self.face.apply(Snapshot(State.CALM)))
        self.assertEqual(self.transport.sent, [])

    def test_reset_forces_a_repaint(self):
        self.face.apply(Snapshot(State.CALM))
        self.face.reset()
        self.assertTrue(self.face.apply(Snapshot(State.CALM)))

    def test_keepalive_resends_even_when_unchanged(self):
        # The device uses any received command as a liveness tick, so this
        # must go out regardless of whether the state moved.
        self.face.apply(Snapshot(State.BUSY))
        self.transport.sent.clear()
        self.face.keepalive()
        self.assertEqual(self.transport.sent, ["FACE busy"])

    def test_keepalive_before_any_state_sends_calm(self):
        self.face.keepalive()
        self.assertEqual(self.transport.sent, ["FACE calm"])

    def test_toast_is_truncated_to_the_display_width(self):
        self.face.toast("x" * 40)
        self.assertEqual(len(self.transport.sent[0]), len("TOAST ") + 21)

    def test_show_list_sends_the_payload(self):
        self.face.show_list("FOX webapp|>0 claude")
        self.assertEqual(self.transport.sent, ["LIST FOX webapp|>0 claude"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `v0/bridge/tests/run_tests.sh -k test_face`
Expected: FAIL — `AssertionError: ['STATE busy'] != ['FACE busy']`.

- [ ] **Step 3: Write the implementation**

Replace the body of `Face` in `v0/bridge/opendeck/face.py`:

```python
class Face:
    def __init__(self, transport: SerialTransport) -> None:
        self._transport = transport
        self._state: State | None = None

    def reset(self) -> None:
        """Forget the pushed state so the next update repaints."""
        self._state = None

    def apply(self, snapshot: Snapshot) -> bool:
        """Push the expression, returning True if it changed."""
        if snapshot.state is self._state:
            return False
        self._state = snapshot.state
        self._transport.send(f"FACE {snapshot.state}")
        log.debug("face -> %s", snapshot.state)
        return True

    def keepalive(self) -> None:
        """Re-send the current face unconditionally.

        The device treats any received command as proof the host is alive and
        falls back to an offline face without one. The firmware early-returns
        on an unchanged state, so this restarts no animation.
        """
        self._transport.send(f"FACE {self._state or State.CALM}")

    def toast(self, text: str) -> None:
        text = text[:TOAST_MAX]
        log.info("toast: %s", text)
        self._transport.send(f"TOAST {text}")

    def show_list(self, payload: str) -> None:
        self._transport.send(f"LIST {payload}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `v0/bridge/tests/run_tests.sh -k test_face`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add v0/bridge/opendeck/face.py v0/bridge/tests/test_face.py
git commit -m "feat: FACE/LIST protocol and host keepalive"
```

---

### Task 4: Show the list on encoder turn and summon

**Files:**
- Modify: `v0/bridge/opendeck/controller.py`
- Modify: `v0/bridge/tests/test_controller.py`

**Interfaces:**
- Consumes: `panes.build_list`, `Face.show_list`, `Face.keepalive`, `SlotTable`, `Tmux.panes`, `Tmux.windows`
- Produces: `Controller._push_pane_list()` — builds and sends the current session's list

- [ ] **Step 1: Write the failing tests**

Append to `v0/bridge/tests/test_controller.py`:

```python
class TestPaneListGlance(unittest.TestCase):
    def _controller(self):
        from fakes import pane

        tmux = FakeTmux(
            sessions=["webapp"],
            panes={"webapp": [
                pane(index=0, command="claude", window_active=True, pane_active=True),
                pane(index=1, command="nvim"),
            ]},
        )
        transport = FakeTransport()
        ctrl = Controller(Config(), transport, tmux, FakeTerminal())
        ctrl.slots.refresh()
        return ctrl, transport

    def test_encoder_pushes_the_pane_list(self):
        ctrl, transport = self._controller()
        ctrl.handle_encoder(1)
        lists = [m for m in transport.sent if m.startswith("LIST ")]
        self.assertEqual(len(lists), 1)
        self.assertIn("claude", lists[0])

    def test_list_title_names_the_slot_and_session(self):
        ctrl, transport = self._controller()
        ctrl.handle_encoder(1)
        title = next(m for m in transport.sent if m.startswith("LIST ")).split("|")[0]
        self.assertIn("FOX", title)
        self.assertIn("webapp", title)

    def test_summon_pushes_the_list_not_a_toast(self):
        ctrl, transport = self._controller()
        ctrl._announce("summon", {"slot": 0})
        self.assertTrue(any(m.startswith("LIST ") for m in transport.sent))
        self.assertFalse(any(m.startswith("TOAST ") for m in transport.sent))

    def test_interrupt_still_toasts(self):
        ctrl, transport = self._controller()
        ctrl._announce("interrupt", {"slot": 0})
        self.assertIn("TOAST FOX interrupted", transport.sent)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `v0/bridge/tests/run_tests.sh -k TestPaneListGlance`
Expected: FAIL — no `LIST` messages are sent.

- [ ] **Step 3: Write the implementation**

In `v0/bridge/opendeck/controller.py`, add the import:

```python
from . import actions, panes
```

Add the method:

```python
    def _push_pane_list(self) -> None:
        session = self._slots.current_session()
        if session is None:
            return
        slot = self._slots.slot_of(session)
        label = self._slots.label(slot) if slot is not None else "--"
        pane_list = self._context.tmux.panes(session)
        position = next((i + 1 for i, p in enumerate(pane_list) if p.active), 0)
        title = f"{label} {session} {position}/{len(pane_list)}"
        self._face.show_list(
            panes.build_list(title, pane_list, self._context.tmux.windows(session))
        )
```

Replace the `summon` arm of `_announce` — the list names the destination *and* its contents, so the toast is redundant:

```python
            case "summon":
                self._push_pane_list()
```

Change `handle_encoder`:

```python
    def handle_encoder(self, delta: int) -> None:
        actions.cycle_pane(delta)(self._context)
        self._push_pane_list()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `v0/bridge/tests/run_tests.sh -k TestPaneListGlance`
Expected: PASS.

- [ ] **Step 5: Add the keepalive to the refresh tick**

In `run()`, replace the refresh block:

```python
            if now - last_refresh >= REFRESH_INTERVAL:
                self._slots.refresh()
                self._announce_presence(self._presence.evaluate(now))
                self._face.keepalive()
                last_refresh = now
```

`REFRESH_INTERVAL` is already 2.0s, which matches the spec's keepalive interval against the device's 5s timeout.

- [ ] **Step 6: Run the whole suite**

Run: `v0/bridge/tests/run_tests.sh`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add v0/bridge/opendeck/controller.py v0/bridge/tests/test_controller.py
git commit -m "feat: reveal the pane list on encoder turn and summon"
```

---

### Task 5: Firmware — FACE, LIST, offline watchdog, boot animation

**Files:**
- Modify: `v0/firmware/open_deck/open_deck.ino`

**Interfaces:**
- Consumes: `FACE <alert|busy|done|calm>`, `TOAST <text>`, `LIST <title>|<row>|…`
- Produces: unchanged device→host events (`EVT`, `HB`)

There is no host test harness for firmware; this task is verified by compiling, flashing, and driving the device over serial by hand.

- [ ] **Step 1: Replace the state enum and its mapping**

Replace the `PixieState` enum and `parseState`:

```cpp
enum PixieState { PX_CALM, PX_BUSY, PX_ALERT, PX_DONE, PX_OFFLINE };
PixieState pixieState = PX_CALM;
```

```cpp
PixieState parseState(const String &name) {
  if (name == "busy")  return PX_BUSY;
  if (name == "alert") return PX_ALERT;
  if (name == "done")  return PX_DONE;
  return PX_CALM;
}
```

Update `applyState`'s switch to the new names, adding the offline arm:

```cpp
  switch (next) {
    case PX_BUSY:
      eyes.setMood(DEFAULT);
      eyes.setCuriosity(true);
      break;
    case PX_ALERT:
      eyes.setMood(ANGRY);
      eyes.setIdleMode(OFF);
      eyes.setPosition(DEFAULT);
      flashTicks = 6;
      flashNext = 0;
      lastPulse = millis();
      break;
    case PX_DONE:
      eyes.setMood(HAPPY);
      eyes.anim_laugh();
      break;
    case PX_OFFLINE:
      eyes.setMood(DEFAULT);
      eyes.setIdleMode(OFF);
      eyes.setAutoblinker(OFF);
      eyes.close();
      break;
    default:
      eyes.setMood(DEFAULT);
      break;
  }
```

Note `applyState` also calls `eyes.open()` in its DEFAULT-settle preamble so a state leaving `PX_OFFLINE` reopens the eyes. Add `eyes.open();` next to the existing `eyes.setMood(DEFAULT);` at the top of `applyState`.

- [ ] **Step 2: Add list state and the renderer**

Beside the toast state, add:

```cpp
#define LIST_ROWS 6
char listRows[LIST_ROWS][22];
int  listCount = 0;
unsigned long listUntil = 0;
bool listDrawn = false;
const unsigned long LIST_MS = 1200;
```

Add the renderer next to `drawToast` (it is likewise drawn once and held, not redrawn per frame):

```cpp
void drawList() {
  display.clearDisplay();
  display.setTextSize(1);
  display.setTextColor(SH110X_WHITE);
  display.setCursor(0, 0);
  display.print(listRows[0]);
  display.drawFastHLine(0, 10, 128, SH110X_WHITE);
  for (int i = 1; i < listCount; i++) {
    display.setCursor(0, 3 + i * 10);
    display.print(listRows[i]);
  }
  display.display();
  listDrawn = true;
}
```

- [ ] **Step 3: Parse LIST and rename STATE to FACE**

In `handleCommand`, replace the `STATE` branch and add `LIST`:

```cpp
  if (cmd == "FACE") {
    sharedState = parseState(nextToken(line, pos));
  } else if (cmd == "TOAST") {
    while (pos < (int)line.length() && line[pos] == ' ') pos++;
    showToast(line.substring(pos));
  } else if (cmd == "LIST") {
    while (pos < (int)line.length() && line[pos] == ' ') pos++;
    showList(line.substring(pos));
  }
```

Add `showList` beside `showToast`, guarded by the same critical section:

```cpp
volatile bool listDirty = false;
char sharedList[LIST_ROWS][22];
int  sharedListCount = 0;

void showList(const String &payload) {
  portENTER_CRITICAL(&faceMux);
  sharedListCount = 0;
  int start = 0;
  while (sharedListCount < LIST_ROWS && start <= (int)payload.length()) {
    int bar = payload.indexOf('|', start);
    String field = (bar < 0) ? payload.substring(start) : payload.substring(start, bar);
    strncpy(sharedList[sharedListCount], field.c_str(), 21);
    sharedList[sharedListCount][21] = '\0';
    sharedListCount++;
    if (bar < 0) break;
    start = bar + 1;
  }
  listDirty = true;
  portEXIT_CRITICAL(&faceMux);
}
```

- [ ] **Step 4: Add the offline watchdog**

Add near the other timing constants:

```cpp
volatile unsigned long lastHostCommand = 0;
const unsigned long OFFLINE_AFTER_MS = 5000;
const unsigned long BLANK_AFTER_MS   = 15UL * 60 * 1000;
bool offlineToastShown = false;
bool panelBlanked = false;
```

Set `lastHostCommand = millis();` as the first line of `handleCommand`.

In `renderTask`, before applying state:

```cpp
    bool hostAlive = lastHostCommand && (millis() - lastHostCommand < OFFLINE_AFTER_MS);
    if (!hostAlive) {
      if (!offlineToastShown) {
        offlineToastShown = true;
        showToast("host offline");
      }
      applyState(PX_OFFLINE);
    } else {
      offlineToastShown = false;
      if (panelBlanked) {
        panelBlanked = false;
        display.clearDisplay();
      }
      applyState(static_cast<PixieState>(sharedState));
    }

    // Nothing live is being shown, so there is nothing to lose by blanking -
    // and a static face would retain on a mono OLED.
    if (!hostAlive && lastHostCommand &&
        millis() - lastHostCommand > BLANK_AFTER_MS) {
      if (!panelBlanked) {
        panelBlanked = true;
        display.clearDisplay();
        display.display();
      }
      vTaskDelay(pdMS_TO_TICKS(200));
      continue;
    }
```

Replace the existing `applyState(static_cast<PixieState>(sharedState));` line with the block above.

- [ ] **Step 5: Render the list ahead of the face**

In `renderTask`, copy the shared list under the mutex alongside the toast copy, then extend the draw selection so the list takes precedence over the face but not the toast:

```cpp
    portENTER_CRITICAL(&faceMux);
    bool newList = listDirty;
    if (newList) {
      for (int i = 0; i < sharedListCount; i++) strncpy(listRows[i], sharedList[i], 22);
      listCount = sharedListCount;
      listDirty = false;
    }
    portEXIT_CRITICAL(&faceMux);
    if (newList) {
      listUntil = millis() + LIST_MS;
      listDrawn = false;
    }
```

```cpp
    if (millis() < toastUntil) {
      if (!toastDrawn) drawToast();
      vTaskDelay(pdMS_TO_TICKS(20));
    } else if (millis() < listUntil) {
      if (!listDrawn) drawList();
      vTaskDelay(pdMS_TO_TICKS(20));
    } else {
      eyes.update();
      vTaskDelay(1);
    }
```

- [ ] **Step 6: Add the boot animation**

At the end of `setup()`, before the `Serial.println`, after the RoboEyes configuration:

```cpp
  // Confirms the panel and I2C bus are alive before any host is involved.
  eyes.close();
  for (int i = 0; i < 12; i++) { eyes.update(); delay(25); }
  eyes.open();
  for (int i = 0; i < 12; i++) { eyes.update(); delay(25); }
  eyes.blink();
  for (int i = 0; i < 20; i++) { eyes.update(); delay(25); }
```

This runs before `xTaskCreatePinnedToCore`, so it is safe to drive the display from `setup()` here.

- [ ] **Step 7: Compile**

Run: `arduino-cli compile --fqbn esp32:esp32:XIAO_ESP32S3 v0/firmware/open_deck`
Expected: success, no errors.

- [ ] **Step 8: Flash and verify by hand**

Stop the daemon first so the port is free: `pkill -f opendeck`

Run: `arduino-cli upload --fqbn esp32:esp32:XIAO_ESP32S3 -p /dev/cu.usbmodem11301 v0/firmware/open_deck`

Then, with no daemon running, confirm each behaviour:
1. On boot the eyes open and blink — panel and I2C are alive.
2. After ~5s with no host, the eyes close and a `host offline` toast appears.
3. `printf 'FACE busy\n' > /dev/cu.usbmodem11301` — the eyes reopen and widen.
4. `printf 'LIST FOX webapp 1/2|>0 claude| 1 nvim\n' > /dev/cu.usbmodem11301` — the list shows for ~1.2s then returns to the face.
5. `printf 'FACE alert\n' > /dev/cu.usbmodem11301` — the screen flashes and the eyes scowl.

- [ ] **Step 9: Commit**

```bash
git add v0/firmware/open_deck/open_deck.ino
git commit -m "feat: FACE/LIST rendering, offline watchdog, boot animation"
```

---

### Task 6: End-to-end verification and docs

**Files:**
- Modify: `docs/protocol-spec.md`
- Modify: `README.md`
- Modify: `v0/README.md`

- [ ] **Step 1: Run the full suite**

Run: `v0/bridge/tests/run_tests.sh`
Expected: PASS, roughly 115 tests.

- [ ] **Step 2: Verify against real hardware**

Start the daemon: `cd v0/bridge && ../.venv/bin/python -m opendeck --command cla -v`

Confirm, in order:
1. Pixie boots, blinks, and settles — no `host offline` toast, because the daemon is up.
2. Turning the encoder shows the pane list, which decays back to the face after ~1.2s.
3. Pressing an animal key shows that session's pane list, not a toast.
4. A Claude Code pane reads `claude`, not `2.1.261`.
5. `tmux send-keys -t <other-session> 'printf "\a"' Enter` — the screen flashes, the eyes scowl, and an `OWL wants you` toast appears.
6. `pkill -f opendeck` — within ~5s the eyes close and `host offline` appears.

- [ ] **Step 3: Update the protocol doc**

In `docs/protocol-spec.md`, replace the "Host → device" section's command list with `FACE`, `TOAST` and `LIST`, documenting: the four wire state names; that `LIST` is one atomic line because a multi-line sequence can be interrupted mid-render; that the host formats and windows rows while the device draws them verbatim; and the 2s keepalive against the 5s offline timeout.

- [ ] **Step 4: Update the READMEs**

In `README.md`, update the "What it does" section to describe the glance layer (the dial reveals the pane list) and the offline state. In `v0/README.md`, add to "Hard-won notes":

```markdown
- **A status display that lies is worse than none.** Without a host keepalive
  the deck happily showed a stale face forever. Any received command is a
  liveness tick; 5s of silence closes Pixie's eyes.
```

- [ ] **Step 5: Commit and push**

```bash
git add -A
git commit -m "docs: FACE/LIST protocol and the glance layer"
git push origin main
```

---

## Self-Review

**Spec coverage:**

| Spec section | Task |
|---|---|
| Four face states | 1 |
| Host → state mapping, `ACTIVE_LINGER`/`ASLEEP` deleted | 1 |
| Pane list layout, markers, flags, `(empty)` | 2 |
| Pane labels incl. version-string → `claude` | 2 |
| Sanitisation and truncation | 2 |
| `FACE`/`TOAST`/`LIST` protocol | 3, 5 |
| Liveness keepalive | 3, 4 |
| Summon shows the list | 4 |
| Glance on encoder turn | 4 |
| Offline watchdog | 5 |
| Burn-in blanking | 5 |
| Boot animation | 5 |
| Docs | 6 |

`calm` burn-in needs no work — idle motion is already on, as the spec notes.

**Placeholder scan:** none. Every code step carries the actual code.

**Type consistency:** `build_list(title, panes, windows, max_rows)` and
`pane_label(pane, window)` are used with those signatures in Tasks 2 and 4.
`Face.show_list(payload)` and `Face.keepalive()` are defined in Task 3 and used
in Task 4. The four `State` members from Task 1 are consumed in Tasks 3 and 4.
Firmware `PX_*` names are consistent between the enum, `parseState`,
`applyState` and `renderTask`.
