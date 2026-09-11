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

    def test_label_strips_newlines(self):
        # The wire protocol is newline-framed: a stray \n in a field would
        # split the line and corrupt the frame.
        self.assertEqual(pane_label(pane(command="a\nb"), None), "a_b")
        self.assertEqual(pane_label(pane(command="a\rb"), None), "a_b")


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

    def test_title_keeps_spaces_but_loses_framing_chars(self):
        payload = build_list("FOX web app|x", [pane(pane_active=True, window_active=True)], [])
        title = payload.split("|")[0]
        self.assertEqual(title, "FOX web app_x")

    def test_title_strips_newlines(self):
        payload = build_list("FOX\nweb\rapp", [pane(pane_active=True, window_active=True)], [])
        self.assertEqual(payload.split("|")[0], "FOX_web_app")

    def test_payload_is_always_a_single_line(self):
        panes = [pane(index=0, command="a\nb", window_active=True, pane_active=True)]
        payload = build_list("t\nitle", panes, [])
        self.assertNotIn("\n", payload)
        self.assertNotIn("\r", payload)

    def test_deliberate_window_name_is_used_as_the_label(self):
        # pane_label's rule 1 (deliberate window name wins) must fire through
        # build_list, not just when pane_label is called directly.
        panes = [pane(window=0, index=0, command="node", window_active=True, pane_active=True)]
        windows = [window(index=0, name="webapp")]
        row = build_list("t", panes, windows).split("|")[1]
        self.assertIn("webapp", row)

    def test_generic_window_name_does_not_win_over_the_running_command(self):
        panes = [pane(window=0, index=0, command="vim", window_active=True, pane_active=True)]
        windows = [window(index=0, name="zsh")]
        row = build_list("t", panes, windows).split("|")[1]
        self.assertIn("vim", row)
        self.assertNotIn("zsh", row)


if __name__ == "__main__":
    unittest.main()
