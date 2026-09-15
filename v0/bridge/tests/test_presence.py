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
    def test_no_sessions_is_calm(self):
        mon, _ = monitor([], client=False)
        self.assertEqual(mon.evaluate(0.0).state, State.CALM)

    def test_idle_shell_is_calm(self):
        mon, _ = monitor(["fox"], panes={"fox": [pane(command="zsh", pane_active=True)]})
        self.assertEqual(mon.evaluate(100.0).state, State.CALM)

    def test_running_agent_is_busy(self):
        mon, _ = monitor(
            ["fox"],
            panes={"fox": [pane(command="claude", window_active=True, pane_active=True)]},
        )
        self.assertEqual(mon.evaluate(100.0).state, State.BUSY)

    def test_activity_elsewhere_takes_priority_over_busy(self):
        mon, _ = monitor(
            ["fox", "owl"],
            panes={"fox": [pane(command="claude", pane_active=True)]},
            windows={"owl": [window(activity=True)]},
        )
        snapshot = mon.evaluate(100.0)
        self.assertEqual(snapshot.state, State.ALERT)
        self.assertEqual(snapshot.attention_session, "owl")

    def test_a_bell_also_raises_alert(self):
        mon, _ = monitor(
            ["fox", "owl"],
            panes={"fox": [pane(command="zsh")]},
            windows={"owl": [window(bell=True)]},
        )
        self.assertEqual(mon.evaluate(100.0).state, State.ALERT)

    def test_activity_in_the_current_session_is_not_an_alert(self):
        mon, _ = monitor(
            ["fox"],
            panes={"fox": [pane(command="zsh")]},
            windows={"fox": [window(activity=True)]},
        )
        self.assertNotEqual(mon.evaluate(100.0).state, State.ALERT)

    def test_agent_disappearing_reports_done_once(self):
        tmux = FakeTmux(
            sessions=["fox"],
            panes={"fox": [pane(command="claude", pane_active=True)]},
        )
        slots = SlotTable(tmux)
        slots.refresh()
        mon = PresenceMonitor(tmux, slots)

        self.assertEqual(mon.evaluate(10.0).state, State.BUSY)
        tmux._panes = {"fox": [pane(command="zsh", pane_active=True)]}
        self.assertEqual(mon.evaluate(11.0).state, State.DONE)
        # DONE must not latch, or the face would stay happy forever.
        self.assertEqual(mon.evaluate(12.0).state, State.CALM)

    def test_a_running_program_counts_as_busy(self):
        mon, _ = monitor(["fox"], panes={"fox": [pane(command="vim")]})
        self.assertEqual(mon.evaluate(100.0).state, State.BUSY)

    def test_shells_are_never_mistaken_for_agents(self):
        for shell in ("zsh", "bash", "fish", "-zsh"):
            with self.subTest(shell=shell):
                mon, _ = monitor(["fox"], panes={"fox": [pane(command=shell)]})
                self.assertEqual(mon.evaluate(100.0).state, State.CALM)

    def test_claude_code_version_string_is_recognised_as_an_agent(self):
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
            sessions=["fox"], panes={"fox": [pane(command="2.1.261", pane_active=True)]}
        )
        slots = SlotTable(tmux)
        slots.refresh()
        mon = PresenceMonitor(tmux, slots)
        self.assertEqual(mon.evaluate(10.0).state, State.BUSY)
        tmux._panes = {"fox": [pane(command="zsh", pane_active=True)]}
        self.assertEqual(mon.evaluate(11.0).state, State.DONE)

    def test_state_values_are_the_wire_names(self):
        self.assertEqual(
            {State.ALERT, State.BUSY, State.DONE, State.CALM},
            {"alert", "busy", "done", "calm"},
        )


if __name__ == "__main__":
    unittest.main()
