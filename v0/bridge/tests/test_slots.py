import unittest

from fakes import FakeTmux
from opendeck.slots import SlotTable


class TestSlotTable(unittest.TestCase):
    def test_sessions_fill_slots_in_discovery_order(self):
        table = SlotTable(FakeTmux(sessions=["webapp", "api", "notes"]))
        table.refresh()
        self.assertEqual(table.slots, ("webapp", "api", "notes", None))

    def test_only_four_sessions_get_slots(self):
        table = SlotTable(FakeTmux(sessions=list("abcde")))
        table.refresh()
        self.assertEqual(table.slots, ("a", "b", "c", "d"))

    def test_assignment_is_stable_across_refreshes(self):
        tmux = FakeTmux(sessions=["webapp", "api"])
        table = SlotTable(tmux)
        table.refresh()
        table.refresh()
        self.assertEqual(table.slots[:2], ("webapp", "api"))

    def test_slot_is_released_when_its_session_disappears(self):
        tmux = FakeTmux(sessions=["webapp", "api"])
        table = SlotTable(tmux)
        table.refresh()
        tmux._sessions = [s for s in tmux._sessions if s.name != "webapp"]
        table.refresh()
        self.assertIsNone(table.slots[0])

    def test_a_freed_slot_is_reused(self):
        tmux = FakeTmux(sessions=["webapp", "api"])
        table = SlotTable(tmux)
        table.refresh()
        tmux._sessions = [s for s in tmux._sessions if s.name != "webapp"]
        table.refresh()
        from opendeck.tmux import Session
        tmux._sessions.append(Session("newproj", 1, False))
        table.refresh()
        self.assertEqual(table.slots[0], "newproj")

    def test_pinned_sessions_keep_their_slot_even_when_absent(self):
        table = SlotTable(FakeTmux(sessions=["other"]), pinned=("webapp", None, None, None))
        table.refresh()
        self.assertEqual(table.slots[0], "webapp")
        self.assertEqual(table.slots[1], "other")

    def test_slot_lookup_round_trips(self):
        table = SlotTable(FakeTmux(sessions=["webapp", "api"]))
        table.refresh()
        self.assertEqual(table.slot_of("api"), 1)
        self.assertIsNone(table.slot_of("missing"))
        self.assertIsNone(table.slot_of(None))

    def test_labels(self):
        table = SlotTable(FakeTmux())
        self.assertEqual(table.label(0), "FOX")
        self.assertEqual(table.label(3), "PNDA")
        self.assertEqual(table.label(9), "--")

    def test_current_session_prefers_the_attached_one(self):
        table = SlotTable(FakeTmux(sessions=["webapp", "api"]))
        table.refresh()
        self.assertEqual(table.current_session(), "webapp")

    def test_current_session_falls_back_to_the_first_slot(self):
        table = SlotTable(FakeTmux(sessions=["webapp"], client=False))
        table.refresh()
        self.assertEqual(table.current_session(), "webapp")

    def test_out_of_range_slot_is_none(self):
        table = SlotTable(FakeTmux(sessions=["webapp"]))
        table.refresh()
        self.assertIsNone(table.session_for(7))


if __name__ == "__main__":
    unittest.main()


class TestCreateForSlot(unittest.TestCase):
    def test_creates_a_session_named_after_the_key(self):
        tmux = FakeTmux(sessions=[])
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.create_for(0), "fox")
        self.assertEqual(table.slots[0], "fox")

    def test_returns_the_existing_session_for_an_occupied_slot(self):
        tmux = FakeTmux(sessions=["webapp"])
        table = SlotTable(tmux)
        table.refresh()
        self.assertEqual(table.create_for(0), "webapp")
        self.assertNotIn(("new_session", "fox"), tmux.calls)

    def test_new_session_survives_a_refresh(self):
        tmux = FakeTmux(sessions=["webapp"])
        table = SlotTable(tmux)
        table.refresh()
        table.create_for(2)
        table.refresh()
        self.assertEqual(table.slots[2], "cat")

    def test_out_of_range_slot_is_none(self):
        table = SlotTable(FakeTmux(sessions=[]))
        self.assertIsNone(table.create_for(9))
