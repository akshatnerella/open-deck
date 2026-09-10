import unittest

from opendeck.events import Edge, EncoderEvent, Heartbeat, KeyEvent
from opendeck.transport import parse


class TestParse(unittest.TestCase):
    def test_key_events(self):
        for edge in ("DOWN", "HOLD", "UP"):
            with self.subTest(edge=edge):
                self.assertEqual(
                    parse(f"EVT KEY_AGENT1 {edge}"), KeyEvent("KEY_AGENT1", Edge(edge))
                )

    def test_encoder_directions(self):
        self.assertEqual(parse("EVT ENCODER +1"), EncoderEvent(1))
        self.assertEqual(parse("EVT ENCODER -1"), EncoderEvent(-1))

    def test_heartbeat(self):
        self.assertEqual(parse("HB 12345"), Heartbeat(12345))

    def test_unknown_lines_are_ignored(self):
        for line in ("", "garbage", "EVT", "EVT KEY_X SIDEWAYS", "Open Deck ready"):
            with self.subTest(line=line):
                self.assertIsNone(parse(line))


if __name__ == "__main__":
    unittest.main()
