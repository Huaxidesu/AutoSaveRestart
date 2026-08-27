from __future__ import annotations

import time
import unittest

from stub_mcdr import (
    DummyRStyle,
    FakeServer,
    FakeSource,
    install_mcdr_stub,
)

install_mcdr_stub()

from autosave.config import default_config_dict, parse_config  # noqa: E402
from autosave.plugin import AutoSaveManager, Phase  # noqa: E402


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()

    def tearDown(self) -> None:
        self.server.close()

    def _make_manager(
        self,
        warning_seconds: int,
        countdown_seconds: int,
    ) -> AutoSaveManager:
        raw = default_config_dict()
        raw["interval_minutes"] = 1
        raw["warning_seconds"] = warning_seconds
        raw["countdown_seconds"] = countdown_seconds
        config, _ = parse_config(raw)
        manager = AutoSaveManager(self.server, config)
        manager.start()
        return manager

    def test_cancel_during_countdown_prevents_save(self) -> None:
        manager = self._make_manager(2, 2)
        source = FakeSource(player="Admin", console=False)
        manager._command_run(source)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with manager._lock:
                phase = manager._phase
            if phase is Phase.COUNTDOWN:
                break
            time.sleep(0.01)

        self.assertIs(phase, Phase.COUNTDOWN)
        manager._command_cancel(source)
        time.sleep(0.3)

        self.assertEqual(self.server.commands, [])
        self.assertTrue(
            any("已取消" in message for message in self.server.messages)
        )
        manager.shutdown()


    def test_manual_run_completes_save_once(self) -> None:
        manager = self._make_manager(1, 1)
        source = FakeSource(player="Admin", console=False)
        manager._command_run(source)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not self.server.commands:
            time.sleep(0.01)

        self.assertEqual(self.server.commands, ["save-all flush"])
        self.assertTrue(
            any("正在保存" in message for message in self.server.messages)
        )
        self.assertTrue(
            any("保存完成" in message for message in self.server.messages)
        )
        manager.shutdown()

    def test_player_messages_use_context_colors(self) -> None:
        manager = self._make_manager(1, 1)
        source = FakeSource(player="Admin", console=False)
        manager._command_run(source)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not self.server.commands:
            time.sleep(0.01)
        time.sleep(0.05)

        warning = next(
            message
            for message in self.server.raw_messages
            if "短暂卡顿" in str(message)
        )
        countdown = next(
            message
            for message in self.server.raw_messages
            if str(message) == "【自动保存】1 秒后保存地图。"
        )
        saving = next(
            message
            for message in self.server.raw_messages
            if "正在保存地图" in str(message)
        )
        saved = next(
            message
            for message in self.server.raw_messages
            if "地图保存完成" in str(message)
        )

        self.assertEqual(warning.color.name, "gold")
        self.assertEqual(countdown.color.name, "red")
        self.assertEqual(countdown.styles, DummyRStyle.bold)
        self.assertEqual(saving.color.name, "aqua")
        self.assertEqual(saving.styles, DummyRStyle.bold)
        self.assertEqual(saved.color.name, "green")
        self.assertEqual(saved.styles, DummyRStyle.bold)
        manager.shutdown()

    def test_set_interval_persists_and_resets_timer(self) -> None:
        manager = self._make_manager(2, 1)
        source = FakeSource(player="Admin", console=False)

        manager._command_set_interval(source, {"minutes": 2})

        self.assertEqual(manager.config.interval_minutes, 2)
        self.assertEqual(
            self.server.saved_configs[-1]["interval_minutes"],
            2,
        )
        with manager._lock:
            next_save_at = manager._next_auto_save_at
        self.assertIsNotNone(next_save_at)
        assert next_save_at is not None
        remaining = next_save_at - time.monotonic()
        self.assertGreater(remaining, 118)
        self.assertLessEqual(remaining, 120)
        self.assertTrue(any("2 分钟" in reply for reply in source.replies))
        manager.shutdown()

    def test_permission_check_is_admin_or_higher(self) -> None:
        manager = self._make_manager(2, 1)

        self.assertFalse(
            manager._has_permission(FakeSource(permission_level=2))
        )
        self.assertTrue(
            manager._has_permission(FakeSource(permission_level=3))
        )
        self.assertTrue(
            manager._has_permission(FakeSource(permission_level=4))
        )
        manager.shutdown()

    def test_unload_during_silent_wait_prevents_ghost_save(self) -> None:
        manager = self._make_manager(3, 1)
        source = FakeSource()
        manager._command_run(source)
        time.sleep(0.1)

        manager.shutdown()
        time.sleep(0.3)

        self.assertEqual(self.server.commands, [])


if __name__ == "__main__":
    unittest.main()
