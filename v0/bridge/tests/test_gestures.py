import unittest

from opendeck.events import Edge, Gesture, KeyEvent
from opendeck.gestures import GestureRecognizer

KEY = "KEY_TERM"


def down(key=KEY):
    return KeyEvent(key, Edge.DOWN)


def up(key=KEY):
    return KeyEvent(key, Edge.UP)


def hold(key=KEY):
    return KeyEvent(key, Edge.HOLD)


class TestGestureRecognizer(unittest.TestCase):
    def setUp(self):
        # KEY_TERM is the only key with a double binding in the defaults.
        self.r = GestureRecognizer(0.35, frozenset({KEY}))

    def test_single_tap_emits_only_after_the_window_closes(self):
        self.assertEqual(self.r.feed(down(), 0.0), [])
        self.assertEqual(self.r.feed(up(), 0.1), [])
        self.assertEqual(self.r.tick(0.2), [])
        self.assertEqual(self.r.tick(0.5), [(KEY, Gesture.TAP)])

    def test_second_press_inside_the_window_is_a_double_tap(self):
        self.r.feed(down(), 0.0)
        self.r.feed(up(), 0.05)
        self.r.feed(down(), 0.1)
        self.assertEqual(self.r.feed(up(), 0.15), [(KEY, Gesture.DOUBLE_TAP)])

    def test_double_tap_cancels_the_pending_single(self):
        self.r.feed(down(), 0.0)
        self.r.feed(up(), 0.05)
        self.r.feed(down(), 0.1)
        self.r.feed(up(), 0.15)
        self.assertEqual(self.r.tick(1.0), [])

    def test_slow_second_press_is_two_separate_taps(self):
        self.r.feed(down(), 0.0)
        self.r.feed(up(), 0.05)
        self.assertEqual(self.r.tick(0.5), [(KEY, Gesture.TAP)])
        self.r.feed(down(), 0.6)
        self.r.feed(up(), 0.65)
        self.assertEqual(self.r.tick(1.1), [(KEY, Gesture.TAP)])

    def test_hold_emits_immediately(self):
        self.r.feed(down(), 0.0)
        self.assertEqual(self.r.feed(hold(), 0.4), [(KEY, Gesture.HOLD)])

    def test_release_after_hold_emits_nothing(self):
        self.r.feed(down(), 0.0)
        self.r.feed(hold(), 0.4)
        self.assertEqual(self.r.feed(up(), 0.9), [])
        self.assertEqual(self.r.tick(2.0), [])

    def test_hold_discards_a_pending_tap_on_the_same_key(self):
        self.r.feed(down(), 0.0)
        self.r.feed(up(), 0.05)
        self.r.feed(down(), 0.1)
        self.r.feed(hold(), 0.5)
        self.assertEqual(self.r.tick(2.0), [])

    def test_keys_without_a_double_binding_fire_immediately(self):
        # Waiting out the double-tap window on a key that has no double
        # binding is pure added latency.
        other = "KEY_MIC"
        self.r.feed(down(other), 0.0)
        self.assertEqual(self.r.feed(up(other), 0.05), [(other, Gesture.TAP)])
        self.assertEqual(self.r.tick(1.0), [])

    def test_immediate_keys_still_honour_hold(self):
        other = "KEY_AGENT1"
        self.r.feed(down(other), 0.0)
        self.assertEqual(self.r.feed(hold(other), 0.4), [(other, Gesture.HOLD)])
        self.assertEqual(self.r.feed(up(other), 0.9), [])

    def test_double_tap_needs_the_same_key(self):
        self.r.feed(down(), 0.0)
        self.r.feed(up(), 0.05)
        self.r.feed(down("KEY_MIC"), 0.1)
        self.assertEqual(self.r.feed(up("KEY_MIC"), 0.15), [("KEY_MIC", Gesture.TAP)])

    def test_next_deadline_reports_pending_work(self):
        self.assertIsNone(self.r.next_deadline)
        self.r.feed(down(), 0.0)
        self.r.feed(up(), 0.0)
        self.assertAlmostEqual(self.r.next_deadline, 0.35)


if __name__ == "__main__":
    unittest.main()
