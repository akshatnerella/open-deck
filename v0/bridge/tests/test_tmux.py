import unittest

from opendeck.tmux import Pane, Window


class TestPane(unittest.TestCase):
    def test_target_addresses_window_and_pane(self):
        self.assertEqual(Pane(2, 1, "zsh", True, True).target, "2.1")

    def test_active_requires_both_window_and_pane(self):
        self.assertTrue(Pane(0, 0, "zsh", True, True).active)
        self.assertFalse(Pane(0, 0, "zsh", True, False).active)
        # A pane can be active within a window that isn't the current one.
        self.assertFalse(Pane(0, 0, "zsh", False, True).active)


class TestWindowLabel(unittest.TestCase):
    def test_prefers_a_deliberate_name(self):
        self.assertEqual(Window(0, "claude", "node", True, False, False).label, "claude")

    def test_falls_back_to_the_command_for_generic_names(self):
        self.assertEqual(Window(0, "zsh", "vim", True, False, False).label, "vim")

    def test_flags(self):
        self.assertEqual(Window(0, "a", "z", True, False, True).flag, "!")
        self.assertEqual(Window(0, "a", "z", True, True, False).flag, "*")
        self.assertEqual(Window(0, "a", "z", True, False, False).flag, " ")


if __name__ == "__main__":
    unittest.main()
