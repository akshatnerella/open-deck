import unittest

from fakes import pane, window
from opendeck.panes import LABEL_WIDTH, build_list, pane_label
from opendeck.tmux import Pane, Window


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


class TestAutoRenamedWindows(unittest.TestCase):
    """tmux renames a window after whatever is running in it.

    An auto-derived name tells us nothing the command does not, and for a
    Claude Code pane it is actively worse - tmux reports the version string
    ("2.1.268") as the process name, so the window inherits that too.
    """

    def test_auto_renamed_window_does_not_mask_the_agent(self):
        panes = [pane(window=0, index=0, command="2.1.268",
                      window_active=True, pane_active=True)]
        windows = [window(index=0, name="2.1.268")]
        row = build_list("t", panes, windows).split("|")[1]
        self.assertIn("claude", row)
        self.assertNotIn("2.1.268", row)

    def test_auto_renamed_window_does_not_mask_a_plain_command(self):
        panes = [pane(window=0, index=0, command="vim",
                      window_active=True, pane_active=True)]
        windows = [window(index=0, name="vim")]
        row = build_list("t", panes, windows).split("|")[1]
        self.assertIn("vim", row)

    def test_a_human_chosen_name_still_wins(self):
        panes = [pane(window=0, index=0, command="vim",
                      window_active=True, pane_active=True)]
        windows = [window(index=0, name="deploy")]
        row = build_list("t", panes, windows).split("|")[1]
        self.assertIn("deploy", row)

    def test_split_window_name_derived_from_one_pane_is_not_deliberate(self):
        # tmux names the window after its ACTIVE pane, so in a split the name
        # would otherwise be stamped onto the sibling pane too.
        panes = [
            pane(window=0, index=0, command="2.1.268", window_active=True, pane_active=True),
            pane(window=0, index=1, command="vim", window_active=True),
        ]
        windows = [window(index=0, name="2.1.268")]
        rows = build_list("t", panes, windows).split("|")[1:]
        self.assertIn("claude", rows[0])
        self.assertIn("vim", rows[1])
        self.assertNotIn("2.1.268", rows[1])

    def test_human_name_applies_across_a_split(self):
        panes = [
            pane(window=0, index=0, command="2.1.268", window_active=True, pane_active=True),
            pane(window=0, index=1, command="vim", window_active=True),
        ]
        windows = [window(index=0, name="deploy")]
        rows = build_list("t", panes, windows).split("|")[1:]
        self.assertIn("deploy", rows[0])
        self.assertIn("deploy", rows[1])


class TestAgentSessionTitleAsLabel(unittest.TestCase):
    """An agent that names its own work should say so in the list."""

    def _pane(self, command="2.1.268", title="", index=1):
        return Pane(window=1, index=index, command=command,
                    window_active=True, pane_active=True, title=title)

    def test_the_session_title_beats_the_generic_label(self):
        label = pane_label(self._pane(title="✳ open deck"), None)
        self.assertEqual(label, "open_deck")

    def test_falls_back_when_the_title_is_noise(self):
        # grok titles its pane "grok" while running "grok-1.0.30-mac".
        label = pane_label(self._pane(command="grok-1.0.30-mac", title="grok"), None)
        self.assertNotEqual(label, "grok-1.0.30-m")
        self.assertTrue(label)

    def test_no_title_still_gives_the_generic_agent_label(self):
        self.assertEqual(pane_label(self._pane(title=""), None), "claude")

    def test_a_human_named_window_still_wins(self):
        # Someone typed that name; it outranks anything we infer.
        window = Window(index=1, name="deploy", command="2.1.268",
                        active=True, activity=False, bell=False)
        self.assertEqual(pane_label(self._pane(title="✳ open deck"), window), "deploy")

    def test_a_shell_pane_is_unaffected(self):
        self.assertEqual(pane_label(self._pane(command="zsh", title="whatever"), None), "zsh")

    def test_long_titles_are_cropped_to_the_column(self):
        label = pane_label(self._pane(title="✳ an extremely long session name"), None)
        self.assertLessEqual(len(label), LABEL_WIDTH)


class TestAgentFallbackLabel(unittest.TestCase):
    """With no session title, the label must say which agent it actually is."""

    def _pane(self, command):
        return Pane(window=1, index=1, command=command, window_active=True,
                    pane_active=True, title="")

    def test_a_grok_pane_is_not_labelled_claude(self):
        self.assertEqual(pane_label(self._pane("grok-1.0.30-mac"), None), "grok")

    def test_a_claude_pane_says_claude(self):
        self.assertEqual(pane_label(self._pane("2.1.268"), None), "claude")

    def test_the_raw_versioned_process_never_reaches_the_screen(self):
        # "grok-1.0.30-mac" is noise on a 21-column panel.
        for cmd in ("grok-1.0.30-mac", "2.1.268", "opencode-2.0"):
            self.assertNotIn("-", pane_label(self._pane(cmd), None))
