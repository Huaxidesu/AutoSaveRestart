from __future__ import annotations

import unittest

from stub_mcdr import install_mcdr_stub

install_mcdr_stub()

from autosave.config import DEFAULT_CONFIG, parse_config  # noqa: E402


class ConfigTests(unittest.TestCase):
    def test_missing_fields_are_filled(self) -> None:
        config, changed = parse_config({"interval_minutes": 45})

        self.assertTrue(changed)
        self.assertEqual(config.interval_minutes, 45)
        self.assertEqual(
            config.command_root,
            DEFAULT_CONFIG["command_root"],
        )
        self.assertTrue(config.messages.warning)

    def test_warning_is_never_shorter_than_countdown(self) -> None:
        config, changed = parse_config(
            {
                "interval_minutes": 10,
                "warning_seconds": 5,
                "countdown_seconds": 10,
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.warning_seconds, 10)
        self.assertEqual(config.countdown_seconds, 10)

    def test_permission_cannot_drop_below_admin(self) -> None:
        config, changed = parse_config({"permission_level": 1})

        self.assertTrue(changed)
        self.assertEqual(config.permission_level, 3)

    def test_interval_is_large_enough_for_warning(self) -> None:
        config, changed = parse_config(
            {
                "interval_minutes": 1,
                "warning_seconds": 121,
                "countdown_seconds": 10,
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.interval_minutes, 3)

    def test_duplicate_aliases_are_removed(self) -> None:
        config, changed = parse_config(
            {
                "command_root": "!!autosave",
                "command_aliases": ["!!as", "!!as", "!!autosave"],
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.command_aliases, ("!!as",))

    def test_default_save_command_has_no_flush(self) -> None:
        config, _ = parse_config(dict(DEFAULT_CONFIG))

        self.assertEqual(config.save_command, "save-all")

    def test_legacy_flush_save_command_is_downgraded(self) -> None:
        config, changed = parse_config({"save_command": "save-all flush"})

        self.assertTrue(changed)
        self.assertEqual(config.save_command, "save-all")

    def test_save_command_newlines_are_flattened(self) -> None:
        config, changed = parse_config({"save_command": "save-all\r\n"})

        self.assertTrue(changed)
        self.assertEqual(config.save_command, "save-all")

    def test_broadcast_mode_defaults_to_say(self) -> None:
        config, changed = parse_config({})

        self.assertTrue(changed)
        self.assertEqual(config.broadcast_mode, "say")
        self.assertFalse(config.use_tellraw)

    def test_unknown_broadcast_mode_falls_back(self) -> None:
        config, changed = parse_config({"broadcast_mode": "json"})

        self.assertTrue(changed)
        self.assertEqual(config.broadcast_mode, "say")

    def test_broadcast_mode_is_case_insensitive(self) -> None:
        config, changed = parse_config({"broadcast_mode": " Tellraw "})

        self.assertTrue(changed)
        self.assertEqual(config.broadcast_mode, "tellraw")
        self.assertTrue(config.use_tellraw)


if __name__ == "__main__":
    unittest.main()
