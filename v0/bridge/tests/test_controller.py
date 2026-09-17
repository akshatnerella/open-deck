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
    tmux = FakeTmux(sessions=["fox"])
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

    def test_a_burst_moves_the_cursor_once(self):
        # Coalescing still matters: six detents are one redraw, not six.
        ctrl, transport, tmux = controller()
        for _ in range(6):
            transport.events.put(EncoderEvent(1))
        _, delta = ctrl._drain(None)
        self.assertEqual(delta, 6)
        ctrl.handle_encoder(delta)
        self.assertEqual([c for c in tmux.calls if c[0] == "select_pane"], [])


if __name__ == "__main__":
    unittest.main()


class TestAttentionAnnounce(unittest.TestCase):
    def _controller(self):
        tmux = FakeTmux(sessions=["fox", "owl"])
        transport = FakeTransport()
        ctrl = Controller(Config(), transport, tmux, FakeTerminal())
        ctrl.slots.refresh()
        return ctrl, transport

    def test_names_the_session_that_wants_attention(self):
        from opendeck.presence import Snapshot, State

        ctrl, transport = self._controller()
        ctrl._announce_presence(Snapshot(State.ALERT, attention_session="owl"))
        self.assertIn("TOAST OWL wants you", transport.sent)

    def test_toasts_only_on_the_transition(self):
        from opendeck.presence import Snapshot, State

        ctrl, transport = self._controller()
        snap = Snapshot(State.ALERT, attention_session="owl")
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
        # Waiting costs every tap on that key the double-tap window, so the
        # set must stay exactly the keys that have a double binding.
        ctrl, _, _ = controller()
        keys = ctrl._gestures.double_tap_keys
        self.assertEqual(keys, frozenset({"KEY_TERM", "KEY_CANCEL"}))

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
            sessions=["fox"],
            panes={"fox": [
                pane(index=0, command="claude", window_active=True, pane_active=True),
                pane(index=1, command="nvim"),
            ]},
        )
        transport = FakeTransport()
        ctrl = Controller(Config(), transport, tmux, FakeTerminal())
        ctrl.slots.refresh()
        return ctrl, transport

    def test_the_encoder_pushes_a_list_with_a_cursor(self):
        ctrl, transport = self._controller()
        ctrl.handle_encoder(1)
        peeks = [m for m in transport.sent if m.startswith("PEEK ")]
        self.assertEqual(len(peeks), 1)
        cursor = int(peeks[0][len("PEEK "):].split("|")[0])
        self.assertGreater(cursor, 0)

    def test_the_list_title_names_the_slot_and_session(self):
        ctrl, transport = self._controller()
        ctrl.handle_encoder(1)
        body = next(m for m in transport.sent if m.startswith("PEEK "))
        title = body[len("PEEK "):].split("|")[1]
        self.assertIn("FOX", title)
        self.assertIn("fox", title)

    def test_the_dial_follows_along_in_the_session_you_are_in(self):
        # Your Mac is the preview. Without it you are choosing from names on
        # a tiny screen with nothing to look at.
        ctrl, transport = self._controller()
        tmux = ctrl._tmux
        ctrl.handle_encoder(1)
        self.assertTrue([c for c in tmux.calls if c[0] == "select_pane"])

    def test_the_dial_never_pulls_you_into_another_session(self):
        # Browsing a session you are not in waits for ENTER: a dial should
        # not yank you out of what you are reading.
        ctrl, transport = self._controller()
        tmux = ctrl._tmux
        ctrl._browse_session = "owl"
        ctrl._browse_panes = tmux.panes("fox")
        ctrl.handle_encoder(1)
        self.assertEqual([c for c in tmux.calls if c[0] in ("select_pane", "switch")], [])

    def test_the_list_gives_up_and_goes_back_to_pixie(self):
        # A look-and-go tool, not a mode.
        ctrl, transport = self._controller()
        ctrl.handle_encoder(1)
        ctrl._browse_expires = 0.0          # pretend the timeout elapsed
        ctrl._end_browse()
        self.assertEqual(transport.sent[-1], "PEEK")
        self.assertIsNone(ctrl._browse_session)

    def test_enter_goes_to_the_highlighted_pane(self):
        ctrl, transport = self._controller()
        tmux = ctrl._tmux
        ctrl.handle_encoder(1)
        ctrl.dispatch("KEY_ENTER", "tap")
        self.assertTrue([c for c in tmux.calls if c[0] == "select_pane"])

    def test_enter_is_a_plain_enter_when_nothing_is_listed(self):
        ctrl, transport = self._controller()
        tmux = ctrl._tmux
        ctrl.dispatch("KEY_ENTER", "tap")
        self.assertNotIn("select_pane", [c[0] for c in tmux.calls])
        self.assertTrue([c for c in tmux.calls if c[0] == "send_keys"])

    def test_committing_takes_the_list_down(self):
        ctrl, transport = self._controller()
        ctrl.handle_encoder(1)
        ctrl.dispatch("KEY_ENTER", "tap")
        self.assertEqual(transport.sent[-1], "PEEK")

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
            sessions=["fox", "owl"],
            panes={
                "fox": [pane(index=0, command="claude", window_active=True, pane_active=True)],
                "owl": [pane(index=0, command="pytest", window_active=True, pane_active=True)],
            },
            client=False,
        )
        transport = FakeTransport()
        ctrl = Controller(Config(), transport, tmux, FakeTerminal())
        ctrl.slots.refresh()
        ctrl._announce("summon", {"slot": 1})
        payload = next(m for m in transport.sent if m.startswith("LIST "))
        self.assertIn("owl", payload)
        self.assertIn("pytest", payload)
        self.assertNotIn("claude", payload)

    def test_summon_of_an_empty_slot_pushes_nothing(self):
        ctrl, transport = self._controller()
        ctrl._announce("summon", {"slot": 3})
        self.assertEqual([m for m in transport.sent if m.startswith("LIST ")], [])


class TestPeek(unittest.TestCase):
    """Holding a key shows what it does; releasing takes it down."""

    def _controller(self):
        tmux = FakeTmux(sessions=["fox", "owl"])
        transport = FakeTransport()
        ctrl = Controller(Config(), transport, tmux, FakeTerminal())
        ctrl.slots.refresh()
        return ctrl, transport

    def _peeks(self, transport):
        return [m for m in transport.sent if m.startswith("PEEK")]

    def test_holding_a_key_shows_the_panel(self):
        ctrl, transport = self._controller()
        ctrl._handle(KeyEvent(key="KEY_AGENT1", edge=Edge.HOLD), 0.0)
        sent = self._peeks(transport)
        self.assertTrue(sent)
        self.assertIn("FOX", sent[0])

    def test_releasing_clears_the_panel(self):
        ctrl, transport = self._controller()
        ctrl._handle(KeyEvent(key="KEY_AGENT1", edge=Edge.HOLD), 0.0)
        ctrl._handle(KeyEvent(key="KEY_AGENT1", edge=Edge.UP), 0.1)
        self.assertEqual(self._peeks(transport)[-1], "PEEK")

    def test_a_release_without_a_hold_clears_nothing(self):
        # Every tap ends in an UP. Sending a clear for taps would put a
        # pointless message on the wire for the commonest gesture there is.
        ctrl, transport = self._controller()
        ctrl._handle(KeyEvent(key="KEY_AGENT1", edge=Edge.UP), 0.0)
        self.assertEqual(self._peeks(transport), [])

    def test_holding_does_not_interrupt_the_session(self):
        # Peeking has to be free, or nobody explores the device.
        ctrl, transport = self._controller()
        tmux = ctrl._tmux
        ctrl._handle(KeyEvent(key="KEY_AGENT1", edge=Edge.HOLD), 0.0)
        ctrl._handle(KeyEvent(key="KEY_AGENT1", edge=Edge.UP), 0.1)
        self.assertNotIn(("send_keys", "fox", "Escape"), tmux.calls)
