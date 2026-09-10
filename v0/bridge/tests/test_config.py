import json
import tempfile
import unittest
from pathlib import Path

from opendeck.config import Binding, Config, default_bindings


class TestBinding(unittest.TestCase):
    def test_parses_a_bare_action_name(self):
        self.assertEqual(Binding.parse("new_window"), Binding("new_window", {}))

    def test_parses_action_with_args(self):
        b = Binding.parse({"action": "summon", "slot": 2})
        self.assertEqual(b, Binding("summon", {"slot": 2}))

    def test_rejects_a_spec_without_an_action(self):
        with self.assertRaises(ValueError):
            Binding.parse({"slot": 1})

    def test_rejects_a_non_mapping(self):
        with self.assertRaises(ValueError):
            Binding.parse(42)


class TestDefaults(unittest.TestCase):
    def test_all_eight_keys_are_bound(self):
        keys = set(default_bindings())
        self.assertEqual(len(keys), 8)

    def test_agent_keys_summon_their_own_slot(self):
        bindings = default_bindings()
        for slot, key in enumerate(("KEY_AGENT1", "KEY_AGENT2", "KEY_AGENT3", "KEY_AGENT4")):
            self.assertEqual(bindings[key]["tap"].args["slot"], slot)

    def test_term_has_all_three_gestures(self):
        self.assertEqual(set(default_bindings()["KEY_TERM"]), {"tap", "double", "hold"})


class TestConfigLoading(unittest.TestCase):
    def test_defaults(self):
        config = Config()
        self.assertEqual(config.launch_command, "claude")
        self.assertEqual(config.sessions, (None, None, None, None))

    def test_from_dict_overrides_scalars(self):
        config = Config.from_dict({"launch_command": "cla", "fullscreen": False})
        self.assertEqual(config.launch_command, "cla")
        self.assertFalse(config.fullscreen)

    def test_sessions_are_padded_to_four(self):
        config = Config.from_dict({"sessions": ["webapp"]})
        self.assertEqual(config.sessions, ("webapp", None, None, None))

    def test_sessions_are_truncated_to_four(self):
        config = Config.from_dict({"sessions": list("abcdef")})
        self.assertEqual(len(config.sessions), 4)

    def test_binding_override_merges_with_defaults(self):
        config = Config.from_dict(
            {"bindings": {"KEY_MIC": {"tap": {"action": "send_keys", "keys": ["Enter"]}}}}
        )
        self.assertEqual(config.binding("KEY_MIC", "tap").args, {"keys": ["Enter"]})
        self.assertIsNotNone(config.binding("KEY_TERM", "tap"))

    def test_unknown_keys_are_ignored(self):
        config = Config.from_dict({"nonsense": True, "launch_command": "cla"})
        self.assertEqual(config.launch_command, "cla")

    def test_missing_file_yields_defaults(self):
        self.assertEqual(Config.load(Path("/nonexistent/config.json")).launch_command, "claude")

    def test_round_trip_through_a_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps({"launch_command": "cla", "sessions": ["a", "b"]}))
            config = Config.load(path)
        self.assertEqual(config.launch_command, "cla")
        self.assertEqual(config.sessions, ("a", "b", None, None))

    def test_with_overrides_ignores_none(self):
        config = Config(launch_command="cla").with_overrides(launch_command=None, port=None)
        self.assertEqual(config.launch_command, "cla")

    def test_unbound_gesture_returns_none(self):
        self.assertIsNone(Config().binding("KEY_MIC", "hold"))


if __name__ == "__main__":
    unittest.main()
