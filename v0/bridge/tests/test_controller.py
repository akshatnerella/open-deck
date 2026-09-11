import queue
import unittest

from fakes import FakeTerminal, FakeTmux
from opendeck.config import Config
from opendeck.controller import Controller
from opendeck.events import Edge, EncoderEvent, KeyEvent
from opendeck.tmux import Tmux


class FakeTransport:
    def __init__(self):
        self.events = queue.Queue()
        self.sent = []

    def send(self, line):
        self.sent.append(line)
        return True

    @property
    def connected(self):
        return True


def controller(**kwargs):
    tmux = FakeTmux(sessions=["webapp"])
    transport = FakeTransport()
    return Controller(Config(**kwargs), transport, tmux, FakeTerminal()), transport, tmux


class TestEncoderCoalescing(unittest.TestCase):
    """A fast spin must become one correctly-sized jump, not N racing steps."""

    def test_sums_a_burst_of_detents(self):
        ctrl, transport, tmux = controller()
        for _ in range(5):
            transport.events.put(EncoderEvent(1))
        events, delta = ctrl._drain(None)
        self.assertEqual(delta, 5)
        self.assertEqual(events, [])

    def test_opposing_turns_cancel_out(self):
        ctrl, transport, _ = controller()
        for d in (1, 1, -1, -1, 1):
            transport.events.put(EncoderEvent(d))
        _, delta = ctrl._drain(None)
        self.assertEqual(delta, 1)

    def test_key_events_survive_the_drain(self):
        ctrl, transport, _ = controller()
        transport.events.put(EncoderEvent(1))
        transport.events.put(KeyEvent("KEY_TERM", Edge.DOWN))
        transport.events.put(EncoderEvent(1))
        events, delta = ctrl._drain(None)
        self.assertEqual(delta, 2)
        self.assertEqual(len(events), 1)
        self.assertIsInstance(events[0], KeyEvent)

    def test_includes_the_blocking_first_event(self):
        ctrl, transport, _ = controller()
        transport.events.put(EncoderEvent(1))
        _, delta = ctrl._drain(EncoderEvent(1))
        self.assertEqual(delta, 2)

    def test_empty_queue_yields_nothing(self):
        ctrl, _, _ = controller()
        events, delta = ctrl._drain(None)
        self.assertEqual((events, delta), ([], 0))

    def test_one_tmux_call_per_burst(self):
        ctrl, transport, tmux = controller()
        for _ in range(6):
            transport.events.put(EncoderEvent(1))
        _, delta = ctrl._drain(None)
        ctrl.handle_encoder(delta)
        cycles = [c for c in tmux.calls if c[0] == "cycle_pane"]
        self.assertEqual(len(cycles), 1)
        self.assertEqual(cycles[0][2], 6)


if __name__ == "__main__":
    unittest.main()


class TestAttentionAnnounce(unittest.TestCase):
    def _controller(self):
        tmux = FakeTmux(sessions=["webapp", "api"])
        transport = FakeTransport()
        ctrl = Controller(Config(), transport, tmux, FakeTerminal())
        ctrl.slots.refresh()
        return ctrl, transport

    def test_names_the_session_that_wants_attention(self):
        from opendeck.presence import Snapshot, State

        ctrl, transport = self._controller()
        ctrl._announce_presence(Snapshot(State.ALERT, attention_session="api"))
        self.assertIn("TOAST OWL wants you", transport.sent)

    def test_toasts_only_on_the_transition(self):
        from opendeck.presence import Snapshot, State

        ctrl, transport = self._controller()
        snap = Snapshot(State.ALERT, attention_session="api")
        ctrl._announce_presence(snap)
        transport.sent.clear()
        ctrl._announce_presence(snap)
        self.assertEqual([m for m in transport.sent if m.startswith("TOAST")], [])

    def test_other_states_do_not_toast(self):
        from opendeck.presence import Snapshot, State

        ctrl, transport = self._controller()
        ctrl._announce_presence(Snapshot(State.BUSY))
        self.assertEqual([m for m in transport.sent if m.startswith("TOAST")], [])
        self.assertIn("FACE busy", transport.sent)

    def test_unmapped_session_falls_back_to_its_name(self):
        from opendeck.presence import Snapshot, State

        ctrl, transport = self._controller()
        ctrl._announce_presence(Snapshot(State.ALERT, attention_session="ghost"))
        self.assertIn("TOAST ghost wants you", transport.sent)


class TestGestureScoping(unittest.TestCase):
    def test_only_keys_with_a_double_binding_wait(self):
        ctrl, _, _ = controller()
        keys = ctrl._gestures.double_tap_keys
        self.assertEqual(keys, frozenset({"KEY_TERM"}))

    def test_agent_key_taps_are_not_delayed(self):
        from opendeck.events import Edge, KeyEvent
        from opendeck.events import Gesture

        ctrl, _, _ = controller()
        ctrl._gestures.feed(KeyEvent("KEY_AGENT1", Edge.DOWN), 0.0)
        emitted = ctrl._gestures.feed(KeyEvent("KEY_AGENT1", Edge.UP), 0.05)
        self.assertEqual(emitted, [("KEY_AGENT1", Gesture.TAP)])


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

    def test_summon_shows_the_summoned_session_not_the_attached_one(self):
        from fakes import pane

        tmux = FakeTmux(
            sessions=["webapp", "api"],
            panes={
                "webapp": [pane(index=0, command="claude", window_active=True, pane_active=True)],
                "api": [pane(index=0, command="pytest", window_active=True, pane_active=True)],
            },
            client=False,
        )
        transport = FakeTransport()
        ctrl = Controller(Config(), transport, tmux, FakeTerminal())
        ctrl.slots.refresh()
        ctrl._announce("summon", {"slot": 1})
        payload = next(m for m in transport.sent if m.startswith("LIST "))
        self.assertIn("api", payload)
        self.assertIn("pytest", payload)
        self.assertNotIn("claude", payload)

    def test_summon_of_an_empty_slot_pushes_nothing(self):
        ctrl, transport = self._controller()
        ctrl._announce("summon", {"slot": 3})
        self.assertEqual([m for m in transport.sent if m.startswith("LIST ")], [])
