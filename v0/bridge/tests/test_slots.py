import unittest

from opendeck.slots import SlotTable, SlotState
from opendeck.tmux import Session, Window

from fakes import FakeTmux


def window(index=0, command="zsh", name="", active=True, activity=False, bell=False):
    return Window(index=index, name=name, command=command, active=active,
                  activity=activity, bell=bell)


class TestFixedBinding(unittest.TestCase):
    """A key means one session, always. Nothing is discovered."""

    def test_slots_default_to_the_lowercased_labels(self):
        table = SlotTable(FakeTmux())
        self.assertEqual(table.slots, ("fox", "owl", "cat", "pnda"))

    def test_a_key_means_its_session_even_before_it_exists(self):
        # The whole point: an unused key still does something when pressed.
        table = SlotTable(FakeTmux(sessions=[]))
        table.refresh()
        self.assertEqual(table.session_for(0), "fox")
        self.assertFalse(table.exists(0))

    def test_unrelated_sessions_never_take_a_slot(self):
        # Old behaviour vacuumed any session into the first free slot, so a
        # key's meaning depended on what you had started that morning.
        table = SlotTable(FakeTmux(sessions=["webapp", "api", "scratch"]))
        table.refresh()
        self.assertEqual(table.slots, ("fox", "owl", "cat", "pnda"))
        self.assertIsNone(table.slot_of("webapp"))

    def test_configured_names_override_the_defaults(self):
        table = SlotTable(FakeTmux(), pinned=("webapp", None, "api", None))
        self.assertEqual(table.slots, ("webapp", "owl", "api", "pnda"))

    def test_slot_lookup_round_trips(self):
        table = SlotTable(FakeTmux())
        self.assertEqual(table.slot_of("cat"), 2)
        self.assertIsNone(table.slot_of("nothing"))

    def test_binding_survives_a_session_disappearing(self):
        table = SlotTable(FakeTmux(sessions=["fox"]))
        table.refresh()
        self.assertTrue(table.exists(0))

        table._tmux._sessions = []
        table.refresh()
        self.assertFalse(table.exists(0))
        self.assertEqual(table.session_for(0), "fox")   # still means fox


class TestCreate(unittest.TestCase):
    def test_creates_the_session_named_after_the_key(self):
        tmux = FakeTmux(sessions=[])
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.create_for(1), "owl")
        self.assertIn(("new_session", "owl"), tmux.calls)

    def test_existing_session_is_returned_without_recreating(self):
        tmux = FakeTmux(sessions=["fox"])
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.create_for(0), "fox")
        self.assertNotIn(("new_session", "fox"), tmux.calls)

    def test_out_of_range_slot_is_a_noop(self):
        table = SlotTable(FakeTmux())
        self.assertIsNone(table.create_for(9))


class TestStrip(unittest.TestCase):
    """The four characters the deck draws under Pixie."""

    def test_missing_session_reads_empty(self):
        table = SlotTable(FakeTmux(sessions=[]))
        table.refresh()
        self.assertEqual(table.state_of(0), SlotState.EMPTY)

    def test_a_shell_reads_idle(self):
        table = SlotTable(FakeTmux(sessions=["fox"], panes={"fox": []}))
        table.refresh()
        self.assertEqual(table.state_of(0), SlotState.IDLE)

    def test_a_running_program_reads_working(self):
        tmux = FakeTmux(sessions=["fox"])
        tmux._panes = {"fox": [type("P", (), {"command": "grok"})()]}
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.state_of(0), SlotState.WORKING)

    def test_a_bell_reads_attention(self):
        tmux = FakeTmux(sessions=["fox"], windows={"fox": [window(bell=True)]})
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.state_of(0), SlotState.ATTENTION)

    def test_attention_outranks_working(self):
        tmux = FakeTmux(sessions=["fox"], windows={"fox": [window(bell=True)]})
        tmux._panes = {"fox": [type("P", (), {"command": "grok"})()]}
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.state_of(0), SlotState.ATTENTION)

    def test_activity_in_the_session_you_are_watching_is_not_attention(self):
        # You are looking at it, so it is not news.
        tmux = FakeTmux(sessions=["fox"], windows={"fox": [window(activity=True)]},
                        client=True)
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.state_of(0), SlotState.IDLE)

    def test_strip_is_four_characters(self):
        table = SlotTable(FakeTmux(sessions=["fox", "cat"]))
        table.refresh()
        strip = table.strip()
        self.assertEqual(len(strip), 4)
        self.assertEqual(strip[1], SlotState.EMPTY)   # owl does not exist


class TestCurrentSession(unittest.TestCase):
    def test_prefers_the_attached_session(self):
        table = SlotTable(FakeTmux(sessions=["fox", "owl"], client=True))
        table.refresh()
        self.assertEqual(table.current_session(), "fox")

    def test_falls_back_to_the_first_live_slot(self):
        table = SlotTable(FakeTmux(sessions=["cat"], client=False))
        table.refresh()
        self.assertEqual(table.current_session(), "cat")

    def test_none_when_nothing_is_running(self):
        table = SlotTable(FakeTmux(sessions=[], client=False))
        table.refresh()
        self.assertIsNone(table.current_session())


if __name__ == "__main__":
    unittest.main()
