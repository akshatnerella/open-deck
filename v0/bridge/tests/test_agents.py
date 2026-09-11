import unittest

from opendeck.agents import AgentRegistry, Status

TARGET = "webapp:1.0"


def hook(reg, event, payload=None, target=TARGET, now=None):
    reg.record(event, target, target.split(":")[0], payload or {}, now=now)


class TestLifecycle(unittest.TestCase):
    def setUp(self):
        self.reg = AgentRegistry()

    def test_prompt_submit_marks_working(self):
        hook(self.reg, "UserPromptSubmit")
        self.assertEqual(self.reg.for_target(TARGET).status, Status.WORKING)

    def test_stop_marks_done(self):
        hook(self.reg, "UserPromptSubmit")
        hook(self.reg, "Stop")
        self.assertEqual(self.reg.for_target(TARGET).status, Status.DONE)

    def test_session_end_removes_the_agent(self):
        hook(self.reg, "SessionStart")
        hook(self.reg, "SessionEnd")
        self.assertIsNone(self.reg.for_target(TARGET))

    def test_events_without_a_target_are_ignored(self):
        self.reg.record("Stop", "", "", {})
        self.assertEqual(self.reg.all(), [])

    def test_context_percent_is_clamped(self):
        hook(self.reg, "PreToolUse", {"context_percent": 150})
        self.assertEqual(self.reg.for_target(TARGET).context_pct, 100)

    def test_garbage_context_is_ignored(self):
        hook(self.reg, "PreToolUse", {"context_percent": "n/a"})
        self.assertEqual(self.reg.for_target(TARGET).context_pct, 0)

    def test_stale_agents_disappear(self):
        # Hooks have no goodbye that survives kill -9, so staleness is the
        # only honest signal that an agent is gone.
        hook(self.reg, "UserPromptSubmit", now=0.0)
        self.assertIsNotNone(self.reg.for_target(TARGET, now=10.0))
        self.assertIsNone(self.reg.for_target(TARGET, now=10_000.0))

    def test_target_parses_window_and_pane(self):
        hook(self.reg, "SessionStart", target="webapp:3.2")
        agent = self.reg.for_target("webapp:3.2")
        self.assertEqual((agent.window, agent.pane), (3, 2))


class TestBlockedStatus(unittest.TestCase):
    def setUp(self):
        self.reg = AgentRegistry()

    def test_a_request_for_input_marks_blocked(self):
        hook(self.reg, "Notification", {"message": "Claude needs your permission to use Bash"})
        self.assertEqual(self.reg.for_target(TARGET).status, Status.BLOCKED)

    def test_plain_notification_does_not_block(self):
        # Claude Code fires Notification for idle nudges too; those must not
        # raise an alert.
        hook(self.reg, "UserPromptSubmit")
        hook(self.reg, "Notification", {"message": "still working"})
        self.assertEqual(self.reg.for_target(TARGET).status, Status.WORKING)

    def test_blocked_lists_every_waiting_agent(self):
        for t in ("webapp:1.0", "api:2.0"):
            self.reg.record("Notification", t, t.split(":")[0],
                            {"message": "needs your permission"})
        self.assertEqual(len(self.reg.blocked()), 2)


if __name__ == "__main__":
    unittest.main()
