import unittest

from opendeck import peek
from opendeck.slots import SlotTable

from fakes import FakeTmux


def table(sessions=(), client=True):
    t = SlotTable(FakeTmux(sessions=list(sessions), client=client))
    t.refresh()
    return t


class TestSlotPeek(unittest.TestCase):
    def test_names_the_key_and_its_session(self):
        lines = peek.lines_for("KEY_AGENT1", table(["fox"]))
        self.assertIn("FOX", lines[0])
        self.assertIn("fox", lines[0])

    def test_an_unstarted_slot_says_so_and_says_what_pressing_does(self):
        # The most important thing this panel teaches: an unused key is not a
        # broken key. This is the one screen where guidance is still news.
        lines = peek.lines_for("KEY_AGENT3", table([]))
        body = " ".join(lines).lower()
        self.assertIn("not started", body)
        self.assertIn("press", body)

    def test_a_live_slot_reports_its_state(self):
        t = FakeTmux(sessions=["fox"])
        t._panes = {"fox": [type("P", (), {"command": "grok"})()]}
        slots = SlotTable(t)
        slots.refresh()
        lines = peek.lines_for("KEY_AGENT1", slots)
        self.assertIn("working", " ".join(lines))

    def test_pane_count_is_pluralised(self):
        one = peek.lines_for("KEY_AGENT1", table(["fox"]), panes=1)
        two = peek.lines_for("KEY_AGENT1", table(["fox"]), panes=2)
        self.assertIn("1 pane", " ".join(one))
        self.assertIn("2 panes", " ".join(two))


class TestFunctionKeyPeek(unittest.TestCase):
    def test_term_names_the_gestures_you_would_not_guess(self):
        # Tap is implied by the headline naming the command; the detail row
        # is spent on the two that are not obvious.
        lines = peek.lines_for("KEY_TERM", table(), launch_command="grok")
        body = " ".join(lines)
        for token in ("2x", "split", "hold"):
            self.assertIn(token, body)

    def test_term_names_the_configured_command(self):
        lines = peek.lines_for("KEY_TERM", table(), launch_command="grok")
        self.assertIn("grok", " ".join(lines))

    def test_every_key_produces_something(self):
        for key in ("KEY_MIC", "KEY_CANCEL", "KEY_ENTER", "KEY_TERM"):
            lines = peek.lines_for(key, table())
            self.assertTrue(lines and lines[0])


class TestPanelFits(unittest.TestCase):
    """The panel is 21 characters by 5 rows. Overflow is silently cropped by
    the device, so a too-long line loses information without any error."""

    def test_no_line_exceeds_the_panel_width(self):
        cases = [
            ("KEY_AGENT1", table(["fox"])),
            ("KEY_AGENT2", table([])),
            ("KEY_TERM", table()),
            ("KEY_MIC", table()),
        ]
        for key, slots in cases:
            for line in peek.lines_for(key, slots, launch_command="opencode"):
                self.assertLessEqual(len(line), peek.WIDTH, f"{key}: {line!r}")

    def test_exactly_three_rows(self):
        # bar / headline / detail. The firmware positions each by role, so a
        # fourth row would have nowhere to go.
        for key in ("KEY_AGENT1", "KEY_AGENT2", "KEY_TERM", "KEY_MIC", "KEY_ENTER"):
            self.assertEqual(len(peek.lines_for(key, table(["fox"]))), 3, key)

    def test_a_long_launch_command_is_cropped_not_overflowed(self):
        lines = peek.lines_for("KEY_TERM", table(),
                               launch_command="some-absurdly-long-agent-command")
        for line in lines:
            self.assertLessEqual(len(line), peek.WIDTH)


class TestWireFormat(unittest.TestCase):
    def test_payload_joins_rows_with_bars(self):
        self.assertEqual(peek.payload(["a", "b", "c"]), "a|b|c")

    def test_blank_rows_survive_the_round_trip(self):
        # A blank row is deliberate spacing, so it must not be dropped.
        self.assertEqual(peek.payload(["FOX", "", "tap"]).split("|"),
                         ["FOX", "", "tap"])


if __name__ == "__main__":
    unittest.main()
