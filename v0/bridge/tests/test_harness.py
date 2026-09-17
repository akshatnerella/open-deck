import socket
import unittest

from opendeck import harness
from opendeck.config import Config
from opendeck.tmux import Pane


def pane(command="zsh", title=""):
    return Pane(window=1, index=1, command=command, window_active=True,
                pane_active=True, title=title)


class TestDetection(unittest.TestCase):
    """The observed process names, not the ones you would guess."""

    def test_claude_reports_its_version_as_the_process_name(self):
        # Measured: "2.1.268". Matching "claude" finds nothing.
        self.assertTrue(harness.is_agent_command("2.1.268"))

    def test_grok_appends_version_and_platform(self):
        # Measured: "grok-1.0.30-mac". This is why a plain "grok" entry in the
        # old command set never matched anything.
        self.assertTrue(harness.is_agent_command("grok-1.0.30-mac"))

    def test_plain_names_still_match(self):
        for cmd in ("claude", "grok", "opencode", "codex", "aider"):
            self.assertTrue(harness.is_agent_command(cmd), cmd)

    def test_shells_are_not_agents(self):
        for cmd in ("zsh", "bash", "fish", "-zsh"):
            self.assertFalse(harness.is_agent_command(cmd), cmd)

    def test_ordinary_programs_are_not_agents(self):
        for cmd in ("vim", "npm", "htop", "ssh", ""):
            self.assertFalse(harness.is_agent_command(cmd), cmd)

    def test_detection_ignores_the_configured_harness(self):
        # A deck set to grok must still show a claude pane as working, or the
        # display lies about what is actually running.
        self.assertTrue(harness.is_agent_command("2.1.268"))
        self.assertTrue(harness.is_agent_command("grok-1.0.30-mac"))


class TestSelection(unittest.TestCase):
    def test_harness_picks_the_launch_command(self):
        self.assertEqual(Config(harness="grok").launch_command, "grok")
        self.assertEqual(Config(harness="claude").launch_command, "claude")

    def test_an_explicit_command_still_wins(self):
        # Someone wrapping the CLI in a shell alias needs to override it.
        self.assertEqual(Config(harness="claude", launch_command="cla").launch_command, "cla")

    def test_unknown_harness_falls_back_rather_than_crashing(self):
        self.assertEqual(harness.get("nonsense").key, harness.DEFAULT_HARNESS)
        self.assertEqual(harness.get(None).key, harness.DEFAULT_HARNESS)

    def test_config_round_trips_the_setting(self):
        self.assertEqual(Config.from_dict({"harness": "grok"}).launch_command, "grok")


class TestTitleCleaning(unittest.TestCase):
    def test_claude_session_name_survives_its_decoration(self):
        # Measured title: "✳ open deck" - a non-ASCII glyph the device's
        # font cannot render, so it must be stripped rather than passed on.
        self.assertEqual(harness.clean_title("✳ open deck", "2.1.268"), "open deck")

    def test_non_ascii_is_removed_entirely(self):
        self.assertEqual(harness.clean_title("✳✳ build · now", "2.1.268"),
                         "build  now")

    def test_the_hostname_is_not_a_session_name(self):
        host = socket.gethostname()
        self.assertIsNone(harness.clean_title(host, "2.1.269"))
        self.assertIsNone(harness.clean_title(host.split(".")[0], "2.1.269"))

    def test_a_title_that_merely_repeats_the_command_is_dropped(self):
        # Measured: grok sets its title to "grok" while running
        # "grok-1.0.30-mac". That tells you nothing the pane does not already.
        self.assertIsNone(harness.clean_title("grok", "grok-1.0.30-mac"))

    def test_empty_and_whitespace_titles_are_dropped(self):
        for raw in ("", "   ", "✳", "***"):
            self.assertIsNone(harness.clean_title(raw, "2.1.268"))

    def test_a_shell_name_is_not_a_session_name(self):
        self.assertIsNone(harness.clean_title("zsh", "zsh"))

    def test_a_real_name_is_kept_even_when_it_contains_the_command(self):
        self.assertEqual(harness.clean_title("grok deck refactor", "grok-1.0.30-mac"),
                         "grok deck refactor")


class TestSessionTitle(unittest.TestCase):
    def test_picks_the_first_meaningful_title(self):
        panes = [pane("zsh", ""), pane("2.1.268", "✳ open deck")]
        self.assertEqual(harness.session_title(panes), "open deck")

    def test_none_when_every_title_is_noise(self):
        panes = [pane("zsh", ""), pane("grok-1.0.30-mac", "grok")]
        self.assertIsNone(harness.session_title(panes))

    def test_empty_session_has_no_title(self):
        self.assertIsNone(harness.session_title([]))


if __name__ == "__main__":
    unittest.main()
