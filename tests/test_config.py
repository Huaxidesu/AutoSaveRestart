from __future__ import annotations

import unittest

from stub_mcdr import install_mcdr_stub

install_mcdr_stub()

from autosave.config import (  # noqa: E402
    CONFIG_NOTES,
    DEFAULT_CONFIG,
    DEFAULT_MESSAGES,
    MESSAGE_KEYS,
    migrate_legacy_config,
    parse_config,
)


class ConfigTests(unittest.TestCase):
    def test_missing_fields_are_filled(self) -> None:
        config, changed = parse_config({"保存间隔分钟": 45})

        self.assertTrue(changed)
        self.assertEqual(config.interval_minutes, 45)
        self.assertEqual(config.command_root, DEFAULT_CONFIG["主指令"])
        self.assertTrue(config.messages.warning)

    def test_warning_is_never_shorter_than_countdown(self) -> None:
        config, changed = parse_config(
            {
                "保存间隔分钟": 10,
                "保存预警秒数": 5,
                "保存倒计时秒数": 10,
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.warning_seconds, 10)
        self.assertEqual(config.countdown_seconds, 10)

    def test_permission_cannot_drop_below_admin(self) -> None:
        config, changed = parse_config({"权限等级": 1})

        self.assertTrue(changed)
        self.assertEqual(config.permission_level, 3)

    def test_interval_is_large_enough_for_warning(self) -> None:
        config, changed = parse_config(
            {
                "保存间隔分钟": 1,
                "保存预警秒数": 121,
                "保存倒计时秒数": 10,
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.interval_minutes, 3)

    def test_duplicate_aliases_are_removed(self) -> None:
        config, changed = parse_config(
            {
                "主指令": "!!autosave",
                "指令别名": ["!!as", "!!as", "!!autosave"],
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.command_aliases, ("!!as",))

    def test_default_save_command_has_no_flush(self) -> None:
        config, _ = parse_config(dict(DEFAULT_CONFIG))

        self.assertEqual(config.save_command, "save-all")

    def test_legacy_flush_save_command_is_downgraded(self) -> None:
        config, changed = parse_config({"保存指令": "save-all flush"})

        self.assertTrue(changed)
        self.assertEqual(config.save_command, "save-all")

    def test_save_command_newlines_are_flattened(self) -> None:
        config, changed = parse_config({"保存指令": "save-all\r\n"})

        self.assertTrue(changed)
        self.assertEqual(config.save_command, "save-all")

    def test_broadcast_mode_defaults_to_say(self) -> None:
        config, changed = parse_config({})

        self.assertTrue(changed)
        self.assertEqual(config.broadcast_mode, "say")
        self.assertFalse(config.use_tellraw)

    def test_unknown_broadcast_mode_falls_back(self) -> None:
        config, changed = parse_config({"播报方式": "json"})

        self.assertTrue(changed)
        self.assertEqual(config.broadcast_mode, "say")

    def test_broadcast_mode_is_case_insensitive(self) -> None:
        config, changed = parse_config({"播报方式": " Tellraw "})

        self.assertTrue(changed)
        self.assertEqual(config.broadcast_mode, "tellraw")
        self.assertTrue(config.use_tellraw)

    def test_legacy_english_keys_are_migrated(self) -> None:
        config, changed = parse_config(
            {
                "interval_minutes": 45,
                "warning_seconds": 30,
                "countdown_seconds": 5,
                "save_command": "save-off",
                "broadcast_mode": "tellraw",
                "command_root": "!!save",
                "command_aliases": ["!!sv"],
                "permission_level": 4,
                "messages": {"help": "自定义帮助"},
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.interval_minutes, 45)
        self.assertEqual(config.warning_seconds, 30)
        self.assertEqual(config.save_command, "save-off")
        self.assertEqual(config.command_root, "!!save")
        self.assertEqual(config.command_aliases, ("!!sv",))
        self.assertEqual(config.permission_level, 4)
        self.assertEqual(config.messages.help, "自定义帮助")

    def test_migration_prefers_existing_chinese_key(self) -> None:
        raw = {"interval_minutes": 45, "保存间隔分钟": 90}

        self.assertTrue(migrate_legacy_config(raw))
        self.assertNotIn("interval_minutes", raw)
        self.assertEqual(raw["保存间隔分钟"], 90)

    def test_restart_defaults(self) -> None:
        config, _ = parse_config({})

        self.assertTrue(config.restart.guard)
        self.assertEqual(config.restart.delay_seconds, 5)
        self.assertEqual(config.restart.interval_minutes, 0)
        self.assertFalse(config.restart.timed_restart_enabled)
        self.assertEqual(config.restart.crash_limit, 3)
        self.assertEqual(config.restart.stop_command, "stop")

    def test_restart_values_are_read(self) -> None:
        config, _ = parse_config(
            {
                "崩溃守护": False,
                "拉起延迟秒数": 0,
                "定时重启间隔分钟": 720,
                "崩溃次数上限": 0,
                "崩溃统计窗口分钟": 30,
                "重启指令": "shutdown",
            }
        )

        self.assertFalse(config.restart.guard)
        self.assertEqual(config.restart.delay_seconds, 0)
        self.assertEqual(config.restart.interval_minutes, 720)
        self.assertEqual(config.restart.crash_limit, 0)
        self.assertEqual(config.restart.crash_window_minutes, 30)
        self.assertEqual(config.restart.stop_command, "shutdown")

    def test_timed_restart_covers_warning_window(self) -> None:
        config, changed = parse_config(
            {
                "保存预警秒数": 180,
                "保存倒计时秒数": 10,
                "定时重启间隔分钟": 1,
            }
        )

        self.assertTrue(changed)
        self.assertEqual(config.restart.interval_minutes, 3)

    def test_config_file_is_fully_chinese(self) -> None:
        config, _ = parse_config({})
        payload = config.to_dict()

        self.assertEqual(payload["配置说明"], list(CONFIG_NOTES))
        self.assertEqual(set(payload["提示文字"]), set(DEFAULT_MESSAGES))
        for legacy_key in ("interval_minutes", "messages", "command_root"):
            self.assertNotIn(legacy_key, payload)
        self.assertEqual(len(MESSAGE_KEYS), len(DEFAULT_MESSAGES))


if __name__ == "__main__":
    unittest.main()
