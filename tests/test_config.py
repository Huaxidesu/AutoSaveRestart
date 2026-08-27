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


if __name__ == "__main__":
    unittest.main()
