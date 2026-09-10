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
