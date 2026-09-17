import unittest

from opendeck import peek
from opendeck.slots import SlotTable

from fakes import FakeTmux
from opendeck.tmux import Pane, Window


def fpane(index=1, command="zsh", title="", active=False, window=1):
    return Pane(window=window, index=index, command=command,
                window_active=active, pane_active=active, title=title)


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

    def test_one_row_per_pane(self):
        panes = [fpane(1, "2.1.268", "✳ open deck", active=True),
                 fpane(2, "zsh")]
        lines = peek.lines_for("KEY_AGENT1", table(["fox"]), panes=panes)
        self.assertEqual(len(lines), 3)          # bar + two panes

    def test_a_plain_terminal_is_shown_not_hidden(self):
        # An empty pane is part of the shape of the session; omitting it would
        # make the count on the deck disagree with the count on your screen.
        lines = peek.lines_for("KEY_AGENT1", table(["fox"]), panes=[fpane(1, "zsh")])
        self.assertIn("zsh", " ".join(lines))

    def test_an_agent_pane_is_marked_differently_from_a_shell(self):
        rows = [peek.pane_row(fpane(1, "zsh")),
                peek.pane_row(fpane(2, "grok-1.0.30-mac"))]
        self.assertNotEqual(rows[0][1], rows[1][1])

    def test_the_active_pane_is_marked(self):
        self.assertTrue(peek.pane_row(fpane(1, "zsh", active=True)).startswith(">"))
        self.assertFalse(peek.pane_row(fpane(1, "zsh")).startswith(">"))

    def test_an_agent_pane_shows_its_session_name(self):
        row = peek.pane_row(fpane(1, "2.1.268", "✳ open deck"))
        self.assertIn("open_deck", row)

    def test_more_panes_than_fit_are_cropped(self):
        panes = [fpane(i, "zsh") for i in range(1, 9)]
        lines = peek.lines_for("KEY_AGENT1", table(["fox"]), panes=panes)
        self.assertEqual(len(lines), 1 + peek.MAX_ROWS)


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

    def test_never_more_rows_than_the_panel_holds(self):
        panes = [fpane(i, "zsh") for i in range(1, 9)]
        for key in ("KEY_AGENT1", "KEY_AGENT2", "KEY_TERM", "KEY_MIC", "KEY_ENTER"):
            lines = peek.lines_for(key, table(["fox"]), panes=panes)
            self.assertLessEqual(len(lines), 1 + peek.MAX_ROWS, key)

    def test_a_long_launch_command_is_cropped_not_overflowed(self):
        lines = peek.lines_for("KEY_TERM", table(),
                               launch_command="some-absurdly-long-agent-command")
        for line in lines:
            self.assertLessEqual(len(line), peek.WIDTH)


class TestWireFormat(unittest.TestCase):
    def test_payload_leads_with_the_cursor_row(self):
        self.assertEqual(peek.payload(["a", "b", "c"], cursor=2), "2|a|b|c")

    def test_no_selection_is_minus_one(self):
        self.assertEqual(peek.payload(["a"]).split("|")[0], "-1")

    def test_blank_rows_survive_the_round_trip(self):
        # A blank row is deliberate spacing, so it must not be dropped.
        self.assertEqual(peek.payload(["FOX", "", "tap"]).split("|")[1:],
                         ["FOX", "", "tap"])


if __name__ == "__main__":
    unittest.main()
