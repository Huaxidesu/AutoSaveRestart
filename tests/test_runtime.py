from __future__ import annotations

import time
import unittest

from stub_mcdr import (
    FakeServer,
    FakeSource,
    install_mcdr_stub,
)

install_mcdr_stub()

from autosave.config import default_config_dict, parse_config  # noqa: E402
from autosave.plugin import AutoSaveManager, Phase  # noqa: E402

SAY_PREFIX = "say "


class _NoPropagateFuture:
    """
    cancel() 不传导到真实任务，模拟 MCDR TaskDoneFuture 的行为：
    卸载时取消 future 不会停止正在运行的 asyncio 协程。
    """

    def __init__(self, future) -> None:
        self._future = future

    def cancel(self) -> bool:
        return False

    def cancelled(self) -> bool:
        return self._future.cancelled()

    def done(self) -> bool:
        return self._future.done()

    def add_done_callback(self, callback) -> None:
        self._future.add_done_callback(lambda _future: callback(self))

    def result(self, timeout=None):
        return self._future.result(timeout)

    def exception(self, timeout=None):
        return self._future.exception(timeout)


class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()

    def tearDown(self) -> None:
        self.server.close()

    def _make_manager(
        self,
        warning_seconds: int,
        countdown_seconds: int,
        **overrides: object,
    ) -> AutoSaveManager:
        raw = default_config_dict()
        raw["interval_minutes"] = 1
        raw["warning_seconds"] = warning_seconds
        raw["countdown_seconds"] = countdown_seconds
        raw.update(overrides)
        config, _ = parse_config(raw)
        manager = AutoSaveManager(self.server, config)
        manager.start()
        return manager

    def _save_commands(self) -> list[str]:
        """真正发给服务端的指令（不含用于播报的 say）。"""
        return [
            command
            for command in self.server.commands
            if not command.startswith(SAY_PREFIX)
        ]

    def _broadcasts(self) -> list[str]:
        """say 模式下发出去的原始文本（含 § 颜色码）。"""
        return [
            command[len(SAY_PREFIX):]
            for command in self.server.commands
            if command.startswith(SAY_PREFIX)
        ]

    def _wait_for_save(self, timeout: float = 5) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and not self._save_commands():
            time.sleep(0.01)

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

        self.assertEqual(self._save_commands(), [])
        self.assertTrue(
            any("已取消" in text for text in self._broadcasts())
        )
        manager.shutdown()

    def test_manual_run_completes_save_once(self) -> None:
        manager = self._make_manager(1, 1)
        source = FakeSource(player="Admin", console=False)
        manager._command_run(source)

        self._wait_for_save()

        self.assertEqual(self._save_commands(), ["save-all"])
        self.assertTrue(
            any("正在保存" in text for text in self._broadcasts())
        )
        self.assertTrue(
            any("保存完成" in text for text in self._broadcasts())
        )
        manager.shutdown()

    def test_say_broadcasts_use_legacy_color_codes(self) -> None:
        manager = self._make_manager(1, 1)
        source = FakeSource(player="Admin", console=False)
        manager._command_run(source)

        self._wait_for_save()
        time.sleep(0.2)

        broadcasts = self._broadcasts()
        warning = next(text for text in broadcasts if "短暂卡顿" in text)
        # 预警文案里也有「N 秒后保存地图」，这里用句号区分倒计时那一行
        countdown = next(text for text in broadcasts if "秒后保存地图。" in text)
        saving = next(text for text in broadcasts if "正在保存地图" in text)
        saved = next(text for text in broadcasts if "地图保存完成" in text)

        self.assertTrue(warning.startswith("\u00a76"))
        self.assertTrue(countdown.startswith("\u00a7c\u00a7l"))
        self.assertTrue(saving.startswith("\u00a7b\u00a7l"))
        self.assertTrue(saved.startswith("\u00a7a\u00a7l"))
        for text in (warning, countdown, saving, saved):
            self.assertTrue(text.endswith("\u00a7r"))
        manager.shutdown()

    def test_tellraw_mode_keeps_rtext_colors(self) -> None:
        manager = self._make_manager(1, 1, broadcast_mode="tellraw")
        source = FakeSource(player="Admin", console=False)
        manager._command_run(source)

        deadline = time.monotonic() + 2
        while (
            time.monotonic() < deadline
            and not any(
                "短暂卡顿" in str(message)
                for message in self.server.raw_messages
            )
        ):
            time.sleep(0.01)

        warning = next(
            message
            for message in self.server.raw_messages
            if "短暂卡顿" in str(message)
        )
        self.assertEqual(warning.color.name, "gold")
        self.assertEqual(self._broadcasts(), [])
        manager.shutdown()

    def test_sanitize_text_flattens_newlines(self) -> None:
        self.assertEqual(
            AutoSaveManager._sanitize_text("第一行\n第二行\r\n  第三行  "),
            "第一行 第二行 第三行",
        )

    def test_set_interval_persists_and_resets_timer(self) -> None:
        manager = self._make_manager(2, 1)
        source = FakeSource(player="Admin", console=False)

        manager._command_set_interval(source, {"minutes": 2})

        self.assertEqual(manager.config.interval_minutes, 2)
        self.assertEqual(
            self.server.saved_configs[-1]["interval_minutes"],
            2,
        )
        self.assertEqual(
            self.server.saved_configs[-1]["broadcast_mode"],
            "say",
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

        self.assertEqual(self._save_commands(), [])

    def test_shutdown_interrupts_pending_cycle_wait_quickly(self) -> None:
        """
        回归：MCDR 的 TaskDoneFuture.cancel() 不会传导到 asyncio 任务。
        插件卸载后，正在等待下次自动保存的周期协程必须自行快速退出，
        否则会拖住 MCDR 的 AsyncTaskExecutor 排空流程，使 MCDR
        长时间停在「正在关闭 MCDR」，watchdog 持续打印卡住线程堆栈。
        """
        original_schedule = self.server.schedule_task
        self.server.schedule_task = (
            lambda callback: _NoPropagateFuture(original_schedule(callback))
        )
        # 间隔 2 分钟、预警 60 秒：周期协程将进入约 60 秒的预警等待睡眠
        manager = self._make_manager(60, 10, interval_minutes=2)
        time.sleep(0.3)

        start = time.monotonic()
        manager.shutdown()
        deadline = time.monotonic() + 5
        with manager._lock:
            cycle_future = manager._cycle_future
        while cycle_future is not None and time.monotonic() < deadline:
            time.sleep(0.05)
            with manager._lock:
                cycle_future = manager._cycle_future

        self.assertIsNone(cycle_future)
        self.assertLess(time.monotonic() - start, 4)


if __name__ == "__main__":
    unittest.main()
