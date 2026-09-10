import unittest

from fakes import FakeTmux, pane, window
from opendeck.presence import PresenceMonitor, State
from opendeck.slots import SlotTable


def monitor(sessions, panes=None, windows=None, client=True):
    tmux = FakeTmux(sessions=sessions, panes=panes or {}, windows=windows or {}, client=client)
    slots = SlotTable(tmux)
    slots.refresh()
    return PresenceMonitor(tmux, slots), tmux


class TestPresence(unittest.TestCase):
    def test_no_sessions_is_asleep(self):
        mon, _ = monitor([], client=False)
        self.assertEqual(mon.evaluate(0.0).state, State.ASLEEP)

    def test_idle_shell_is_idle(self):
        mon, _ = monitor(["webapp"], panes={"webapp": [pane(command="zsh", pane_active=True)]})
        self.assertEqual(mon.evaluate(100.0).state, State.IDLE)

    def test_running_agent_is_working(self):
        mon, _ = monitor(
            ["webapp"], panes={"webapp": [pane(command="claude", window_active=True, pane_active=True)]}
        )
        self.assertEqual(mon.evaluate(100.0).state, State.WORKING)

    def test_activity_elsewhere_takes_priority_over_working(self):
        mon, _ = monitor(
            ["webapp", "api"],
            panes={"webapp": [pane(command="claude", pane_active=True)]},
            windows={"api": [window(activity=True)]},
        )
        snapshot = mon.evaluate(100.0)
        self.assertEqual(snapshot.state, State.ATTENTION)
        self.assertEqual(snapshot.attention_session, "api")

    def test_a_bell_also_raises_attention(self):
        mon, _ = monitor(
            ["webapp", "api"],
            panes={"webapp": [pane(command="zsh")]},
            windows={"api": [window(bell=True)]},
        )
        self.assertEqual(mon.evaluate(100.0).state, State.ATTENTION)

    def test_activity_in_the_current_session_is_not_attention(self):
        # You are already looking at it, so it does not need to shout.
        mon, _ = monitor(
            ["webapp"],
            panes={"webapp": [pane(command="zsh")]},
            windows={"webapp": [window(activity=True)]},
        )
        self.assertNotEqual(mon.evaluate(100.0).state, State.ATTENTION)

    def test_agent_disappearing_reports_done_once(self):
        tmux = FakeTmux(
            sessions=["webapp"],
            panes={"webapp": [pane(command="claude", pane_active=True)]},
        )
        slots = SlotTable(tmux)
        slots.refresh()
        mon = PresenceMonitor(tmux, slots)

        self.assertEqual(mon.evaluate(10.0).state, State.WORKING)
        tmux._panes = {"webapp": [pane(command="zsh", pane_active=True)]}
        self.assertEqual(mon.evaluate(11.0).state, State.DONE)
        # DONE must not latch, or the face would stay happy forever.
        self.assertEqual(mon.evaluate(12.0).state, State.IDLE)

    def test_recent_input_shows_as_active(self):
        mon, _ = monitor(["webapp"], panes={"webapp": [pane(command="zsh")]})
        mon.note_input(100.0)
        self.assertEqual(mon.evaluate(101.0).state, State.ACTIVE)

    def test_active_expires(self):
        mon, _ = monitor(["webapp"], panes={"webapp": [pane(command="zsh")]})
        mon.note_input(100.0)
        self.assertEqual(mon.evaluate(120.0).state, State.IDLE)

    def test_long_silence_falls_asleep(self):
        mon, _ = monitor(["webapp"], panes={"webapp": [pane(command="zsh")]})
        mon.note_input(100.0)
        self.assertEqual(mon.evaluate(500.0).state, State.ASLEEP)

    def test_working_beats_sleep(self):
        mon, _ = monitor(
            ["webapp"], panes={"webapp": [pane(command="claude", pane_active=True)]}
        )
        mon.note_input(1.0)
        self.assertEqual(mon.evaluate(9999.0).state, State.WORKING)

    def test_shells_are_never_mistaken_for_agents(self):
        for shell in ("zsh", "bash", "fish", "-zsh"):
            with self.subTest(shell=shell):
                mon, _ = monitor(["webapp"], panes={"webapp": [pane(command=shell)]})
                self.assertNotEqual(mon.evaluate(100.0).state, State.WORKING)

    def test_a_running_program_counts_as_working(self):
        mon, _ = monitor(["webapp"], panes={"webapp": [pane(command="vim")]})
        self.assertEqual(mon.evaluate(100.0).state, State.WORKING)

    def test_claude_code_version_string_is_recognised_as_an_agent(self):
        # Claude Code reports its version (e.g. "2.1.261") as the pane's
        # current command, not "claude" - found running against real sessions.
        from opendeck.presence import is_agent

        for version in ("2.1.261", "2.1.259", "1.0.0"):
            with self.subTest(version=version):
                self.assertTrue(is_agent(version))

    def test_agent_detection_rejects_shells_and_plain_names(self):
        from opendeck.presence import is_agent

        self.assertFalse(is_agent("zsh"))
        self.assertFalse(is_agent(""))
        self.assertFalse(is_agent("vim"))

    def test_version_agent_finishing_reports_done(self):
        tmux = FakeTmux(
            sessions=["webapp"], panes={"webapp": [pane(command="2.1.261", pane_active=True)]}
        )
        slots = SlotTable(tmux)
        slots.refresh()
        mon = PresenceMonitor(tmux, slots)
        self.assertEqual(mon.evaluate(10.0).state, State.WORKING)
        tmux._panes = {"webapp": [pane(command="zsh", pane_active=True)]}
        self.assertEqual(mon.evaluate(11.0).state, State.DONE)


if __name__ == "__main__":
    unittest.main()
