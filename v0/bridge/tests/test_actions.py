import logging
import unittest

from fakes import FakeTerminal, FakeTmux
from opendeck import actions
from opendeck.actions import Context
from opendeck.config import Config
from opendeck.slots import SlotTable


logging.disable(logging.CRITICAL)


def make_context(tmux=None, config=None, terminal=None):
    tmux = tmux or FakeTmux(sessions=["webapp", "api"])
    terminal = terminal or FakeTerminal()
    config = config or Config(launch_command="cla")
    slots = SlotTable(tmux, config.sessions)
    slots.refresh()
    return Context(tmux=tmux, terminal=terminal, slots=slots, config=config), tmux, terminal


class TestSummon(unittest.TestCase):
    def test_switches_and_focuses_when_a_client_is_attached(self):
        ctx, tmux, terminal = make_context()
        actions.summon(0)(ctx)
        self.assertIn(("switch", "webapp"), tmux.calls)
        self.assertIn(("focus",), terminal.calls)

    def test_launches_a_terminal_when_nothing_is_attached(self):
        tmux = FakeTmux(sessions=["webapp"], client=False)
        ctx, _, terminal = make_context(tmux=tmux)
        actions.summon(0)(ctx)
        self.assertIn(("launch_attached", "webapp"), terminal.calls)

    def test_empty_slot_creates_a_session_named_after_the_key(self):
        ctx, tmux, terminal = make_context()
        actions.summon(3)(ctx)
        self.assertIn(("new_session", "pnda"), tmux.calls)
        self.assertIn(("switch", "pnda"), tmux.calls)
        self.assertEqual(ctx.slots.session_for(3), "pnda")

    def test_created_session_avoids_a_name_collision(self):
        tmux = FakeTmux(sessions=["webapp", "api", "notes", "other", "pnda"])
        ctx, _, _ = make_context(tmux=tmux)
        # first four slots are taken by the four discovered sessions
        ctx.slots._slots[3] = None
        actions.summon(3)(ctx)
        self.assertIn(("new_session", "pnda2"), tmux.calls)


class TestInterrupt(unittest.TestCase):
    def test_sends_escape_without_switching(self):
        ctx, tmux, terminal = make_context()
        actions.interrupt(1)(ctx)
        self.assertEqual(tmux.calls, [("send_keys", "api", "Escape")])
        self.assertEqual(terminal.calls, [])

    def test_empty_slot_is_a_noop(self):
        ctx, tmux, _ = make_context()
        actions.interrupt(2)(ctx)
        self.assertEqual(tmux.calls, [])


class TestSendKeys(unittest.TestCase):
    def test_sends_to_the_current_session(self):
        ctx, tmux, _ = make_context()
        actions.send_keys(["Space"])(ctx)
        self.assertEqual(tmux.calls, [("send_keys", "webapp", "Space")])

    def test_no_session_is_a_noop(self):
        ctx, tmux, _ = make_context(tmux=FakeTmux(sessions=[], client=False))
        actions.send_keys(["Escape"])(ctx)
        self.assertEqual(tmux.calls, [])


class TestLaunchAgent(unittest.TestCase):
    def test_launches_into_an_idle_shell(self):
        ctx, tmux, _ = make_context()
        actions.launch_agent()(ctx)
        self.assertEqual(tmux.calls, [("run_command", "webapp", "cla")])

    def test_refuses_to_type_over_a_running_program(self):
        for program in ("vim", "nvim", "python", "npm", "less", "ssh"):
            with self.subTest(program=program):
                tmux = FakeTmux(sessions=["webapp"], active_command=program)
                ctx, _, _ = make_context(tmux=tmux)
                actions.launch_agent()(ctx)
                self.assertEqual(tmux.calls, [], f"must not type into {program}")

    def test_does_not_relaunch_when_already_running(self):
        tmux = FakeTmux(sessions=["webapp"], active_command="cla")
        ctx, _, _ = make_context(tmux=tmux)
        actions.launch_agent()(ctx)
        self.assertEqual(tmux.calls, [])

    def test_split_launch_bypasses_the_busy_check(self):
        tmux = FakeTmux(sessions=["webapp"], active_command="vim")
        ctx, _, _ = make_context(tmux=tmux)
        actions.launch_agent(split=True)(ctx)
        self.assertEqual(
            tmux.calls,
            [("split_window", "webapp", True), ("run_command", "webapp", "cla")],
        )

    def test_split_direction_follows_config(self):
        ctx, tmux, _ = make_context(config=Config(launch_command="cla", split_horizontal=False))
        actions.launch_agent(split=True)(ctx)
        self.assertIn(("split_window", "webapp", False), tmux.calls)


class TestWindowActions(unittest.TestCase):
    def test_new_window(self):
        ctx, tmux, _ = make_context()
        actions.new_window()(ctx)
        self.assertEqual(tmux.calls, [("new_window", "webapp")])

    def test_cycle_window(self):
        ctx, tmux, _ = make_context()
        actions.cycle_window(-1)(ctx)
        self.assertEqual(tmux.calls, [("cycle_window", "webapp", -1)])

    def test_cycle_pane_spans_the_session_by_default(self):
        ctx, tmux, _ = make_context()
        actions.cycle_pane(1)(ctx)
        self.assertEqual(tmux.calls, [("cycle_pane", "webapp", 1, True)])

    def test_cycle_pane_can_be_scoped_to_the_current_window(self):
        ctx, tmux, _ = make_context(config=Config(encoder_scope="window"))
        actions.cycle_pane(1)(ctx)
        self.assertEqual(tmux.calls, [("cycle_pane", "webapp", 1, False)])


class TestRegistry(unittest.TestCase):
    def test_every_default_binding_resolves(self):
        from opendeck.config import default_bindings

        for key, gestures in default_bindings().items():
            for gesture, binding in gestures.items():
                with self.subTest(key=key, gesture=gesture):
                    self.assertTrue(callable(actions.build(binding.action, binding.args)))

    def test_unknown_action_raises(self):
        with self.assertRaises(KeyError):
            actions.build("nope", {})


if __name__ == "__main__":
    unittest.main()


class TestCancel(unittest.TestCase):
    """X interrupts what's running, or closes the pane when nothing is."""

    def test_interrupts_a_running_program(self):
        for program in ("cla", "2.1.261", "vim", "npm"):
            with self.subTest(program=program):
                tmux = FakeTmux(sessions=["webapp"], active_command=program)
                ctx, _, _ = make_context(tmux=tmux)
                actions.cancel()(ctx)
                self.assertEqual(tmux.calls, [("send_keys", "webapp", "C-c")])

    def test_closes_an_idle_pane(self):
        for shell in ("zsh", "bash", "-zsh"):
            with self.subTest(shell=shell):
                tmux = FakeTmux(sessions=["webapp"], active_command=shell)
                ctx, _, _ = make_context(tmux=tmux)
                actions.cancel()(ctx)
                self.assertEqual(tmux.calls, [("run_command", "webapp", "exit")])

    def test_no_session_is_a_noop(self):
        tmux = FakeTmux(sessions=[], client=False)
        ctx, _, _ = make_context(tmux=tmux)
        actions.cancel()(ctx)
        self.assertEqual(tmux.calls, [])
