import logging
import unittest

from fakes import FakeTerminal, FakeTmux
from opendeck import actions
from opendeck.actions import Context
from opendeck.config import Config
from opendeck.slots import SlotTable


logging.disable(logging.CRITICAL)


def make_context(tmux=None, config=None, terminal=None):
    tmux = tmux or FakeTmux(sessions=["fox", "owl"])
    terminal = terminal or FakeTerminal()
    config = config or Config(launch_command="cla")
    slots = SlotTable(tmux, config.sessions)
    slots.refresh()
    return Context(tmux=tmux, terminal=terminal, slots=slots, config=config), tmux, terminal


class TestSummon(unittest.TestCase):
    def test_switches_and_focuses_when_a_client_is_attached(self):
        ctx, tmux, terminal = make_context()
        actions.summon(0)(ctx)
        self.assertIn(("switch", "fox"), tmux.calls)
        self.assertIn(("focus",), terminal.calls)

    def test_launches_a_terminal_when_nothing_is_attached(self):
        tmux = FakeTmux(sessions=["fox"], client=False)
        ctx, _, terminal = make_context(tmux=tmux)
        actions.summon(0)(ctx)
        self.assertIn(("launch_attached", "fox"), terminal.calls)

    def test_empty_slot_creates_a_session_named_after_the_key(self):
        ctx, tmux, terminal = make_context()
        actions.summon(3)(ctx)
        self.assertIn(("new_session", "pnda"), tmux.calls)
        self.assertIn(("switch", "pnda"), tmux.calls)
        self.assertEqual(ctx.slots.session_for(3), "pnda")

    def test_an_existing_session_of_that_name_is_reused_not_duplicated(self):
        # The fixed binding removes the old name-collision problem entirely:
        # if a session called "pnda" exists, that IS what PNDA means.
        tmux = FakeTmux(sessions=["pnda"])
        ctx, _, _ = make_context(tmux=tmux)
        actions.summon(3)(ctx)
        self.assertNotIn(("new_session", "pnda"), tmux.calls)
        self.assertIn(("switch", "pnda"), tmux.calls)


class TestInterrupt(unittest.TestCase):
    def test_sends_escape_without_switching(self):
        ctx, tmux, terminal = make_context()
        actions.interrupt(1)(ctx)
        self.assertEqual(tmux.calls, [("send_keys", "owl", "Escape")])
        self.assertEqual(terminal.calls, [])

    def test_empty_slot_is_a_noop(self):
        ctx, tmux, _ = make_context()
        actions.interrupt(2)(ctx)
        self.assertEqual(tmux.calls, [])


class TestSendKeys(unittest.TestCase):
    def test_sends_to_the_current_session(self):
        ctx, tmux, _ = make_context()
        actions.send_keys(["Space"])(ctx)
        self.assertEqual(tmux.calls, [("send_keys", "fox", "Space")])

    def test_no_session_is_a_noop(self):
        ctx, tmux, _ = make_context(tmux=FakeTmux(sessions=[], client=False))
        actions.send_keys(["Escape"])(ctx)
        self.assertEqual(tmux.calls, [])


class TestLaunchAgent(unittest.TestCase):
    def test_launches_into_an_idle_shell(self):
        ctx, tmux, _ = make_context()
        actions.launch_agent()(ctx)
        self.assertEqual(tmux.calls, [("run_command", "fox", "cla")])

    def test_refuses_to_type_over_a_running_program(self):
        for program in ("vim", "nvim", "python", "npm", "less", "ssh"):
            with self.subTest(program=program):
                tmux = FakeTmux(sessions=["fox"], active_command=program)
                ctx, _, _ = make_context(tmux=tmux)
                actions.launch_agent()(ctx)
                self.assertEqual(tmux.calls, [], f"must not type into {program}")

    def test_does_not_relaunch_when_already_running(self):
        tmux = FakeTmux(sessions=["fox"], active_command="cla")
        ctx, _, _ = make_context(tmux=tmux)
        actions.launch_agent()(ctx)
        self.assertEqual(tmux.calls, [])

    def test_launching_never_splits(self):
        # Tap fills the pane you are in. Making a pane is its own gesture, so
        # one key can no longer rearrange the screen as a side effect.
        ctx, tmux, _ = make_context()
        actions.launch_agent()(ctx)
        self.assertNotIn("split_window", [c[0] for c in tmux.calls])


class TestSplitPane(unittest.TestCase):
    """Double-tap TERM: a new empty terminal, with no agent typed into it."""

    def test_splits_beside_by_default(self):
        ctx, tmux, _ = make_context()
        actions.split_pane()(ctx)
        self.assertEqual(tmux.calls, [("split_window", "fox", True)])

    def test_splits_below_when_asked(self):
        # The one chord on the deck: hold ENTER, double-tap TERM.
        ctx, tmux, _ = make_context()
        actions.split_pane(below=True)(ctx)
        self.assertEqual(tmux.calls, [("split_window", "fox", False)])

    def test_never_runs_a_command_in_the_new_pane(self):
        ctx, tmux, _ = make_context()
        actions.split_pane()(ctx)
        self.assertNotIn("run_command", [c[0] for c in tmux.calls])


class TestContextKey(unittest.TestCase):
    """One physical key, three meanings, decided by what is in the pane."""

    def _ctx(self, running):
        return make_context(tmux=FakeTmux(sessions=["fox"], active_command=running))

    def test_cancel_kills_a_shell_but_escapes_an_agent(self):
        ctx, tmux, _ = self._ctx("zsh")
        actions.context_key("cancel")(ctx)
        self.assertIn(("send_keys", "fox", "C-c"), tmux.calls)

        ctx, tmux, _ = self._ctx("2.1.268")
        actions.context_key("cancel")(ctx)
        self.assertIn(("send_keys", "fox", "Escape"), tmux.calls)

    def test_voice_differs_between_harnesses(self):
        ctx, tmux, _ = self._ctx("2.1.268")
        actions.context_key("voice")(ctx)
        self.assertIn(("send_keys", "fox", "Space"), tmux.calls)

        ctx, tmux, _ = self._ctx("grok-1.0.30-mac")
        actions.context_key("voice")(ctx)
        self.assertIn(("send_keys", "fox", "C-Space"), tmux.calls)

    def test_voice_sends_nothing_in_a_shell(self):
        # There is no voice mode to toggle; a stray Space would type one.
        ctx, tmux, _ = self._ctx("zsh")
        actions.context_key("voice")(ctx)
        self.assertEqual(tmux.calls, [])

    def test_enter_is_enter_everywhere(self):
        for running in ("zsh", "2.1.268", "grok-1.0.30-mac"):
            ctx, tmux, _ = self._ctx(running)
            actions.context_key("enter")(ctx)
            self.assertIn(("send_keys", "fox", "Enter"), tmux.calls, running)

    def test_an_unknown_program_is_treated_as_a_shell(self):
        ctx, tmux, _ = self._ctx("vim")
        actions.context_key("cancel")(ctx)
        self.assertIn(("send_keys", "fox", "C-c"), tmux.calls)


class TestWindowActions(unittest.TestCase):
    def test_new_window(self):
        ctx, tmux, _ = make_context()
        actions.new_window()(ctx)
        self.assertEqual(tmux.calls, [("new_window", "fox")])


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



class TestClosePane(unittest.TestCase):
    """Double-tap X: close this pane, the way you would close it yourself."""

    def test_an_idle_shell_is_closed_with_exit(self):
        tmux = FakeTmux(sessions=["fox"], active_command="zsh")
        ctx, _, _ = make_context(tmux=tmux)
        actions.close_pane()(ctx)
        self.assertIn(("run_command", "fox", "exit"), tmux.calls)

    def test_a_running_program_is_left_alone(self):
        # Tapping X already interrupts, so the sequence is tap then
        # double-tap. A double-tap that kills a working agent outright is not
        # worth the keystroke it saves.
        for running in ("2.1.268", "grok-1.0.30-mac", "vim"):
            tmux = FakeTmux(sessions=["fox"], active_command=running)
            ctx, _, _ = make_context(tmux=tmux)
            actions.close_pane()(ctx)
            self.assertEqual(tmux.calls, [], running)

    def test_it_never_kills_the_pane_outright(self):
        tmux = FakeTmux(sessions=["fox"], active_command="zsh")
        ctx, _, _ = make_context(tmux=tmux)
        actions.close_pane()(ctx)
        self.assertNotIn("kill_pane", [c[0] for c in tmux.calls])
