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
