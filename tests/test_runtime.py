from __future__ import annotations

import time
import unittest
from unittest import mock

from stub_mcdr import (
    FakeServer,
    FakeSource,
    install_mcdr_stub,
)

install_mcdr_stub()

from autosave.config import (  # noqa: E402
    AutoSaveConfig,
    default_config_dict,
    parse_config,
)
from autosave.plugin import (  # noqa: E402
    AutoSaveManager,
    FlowKind,
    Phase,
    parse_duration,
)

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


class DurationTests(unittest.TestCase):
    def test_single_units(self) -> None:
        self.assertEqual(parse_duration("90s"), 90)
        self.assertEqual(parse_duration("30m"), 30 * 60)
        self.assertEqual(parse_duration("2h"), 2 * 3600)
        self.assertEqual(parse_duration("45秒"), 45)
        self.assertEqual(parse_duration("20分钟"), 20 * 60)
        self.assertEqual(parse_duration("3小时"), 3 * 3600)

    def test_combined_units(self) -> None:
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(parse_duration("1h30m15s"), 5415)
        self.assertEqual(parse_duration("2h15m30s"), 8130)
        self.assertEqual(parse_duration("1小时30分"), 5400)
        self.assertEqual(parse_duration("1 小时 30 分 15 秒"), 5415)

    def test_bare_number_means_minutes(self) -> None:
        self.assertEqual(parse_duration("30"), 1800)
        self.assertEqual(parse_duration("1"), 60)

    def test_invalid_input(self) -> None:
        self.assertIsNone(parse_duration(""))
        self.assertIsNone(parse_duration("abc"))
        self.assertIsNone(parse_duration("1h30"))
        self.assertIsNone(parse_duration("0m"))
        self.assertIsNone(parse_duration("10x"))
        self.assertIsNone(parse_duration("999999h"))


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
        raw["保存间隔分钟"] = 1
        raw["保存预警秒数"] = warning_seconds
        raw["保存倒计时秒数"] = countdown_seconds
        raw.update(overrides)
        config, _ = parse_config(raw)
        manager = AutoSaveManager(self.server, config)
        manager.start()
        return manager

    def _simulate_running(self, manager: AutoSaveManager) -> None:
        """模拟服务端完成一次启动：进程启动事件 + 输出 Done。"""
        manager.handle_server_start()
        manager.handle_server_startup()

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

        # 真实 MCDR 的 TaskDoneFuture.cancel() 不会中断协程，流程要等到下一个
        # 检查点（倒计时每秒一次）才收尾，因此这里按轮询等待，而非假定立即生效。
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            if any("已取消" in text for text in self._broadcasts()):
                break
            time.sleep(0.02)

        self.assertEqual(self._save_commands(), [])
        self.assertTrue(
            any("已取消" in text for text in self._broadcasts())
        )
        manager.shutdown()

    def test_cancel_during_silent_wait_prevents_save(self) -> None:
        """回归：预警之后的静默等待阶段也必须响应 cancel。

        早期实现里 _interruptible_sleep 只检查插件卸载，导致静默等待期间的
        cancel 既不生效也不回执，服务端照常重启。
        """
        manager = self._make_manager(6, 2)
        source = FakeSource(player="Admin", console=False)
        manager._command_run(source)

        deadline = time.monotonic() + 5
        phase = None
        while time.monotonic() < deadline:
            with manager._lock:
                phase = manager._phase
            if phase is Phase.SILENT_WAIT:
                break
            time.sleep(0.01)

        self.assertIs(phase, Phase.SILENT_WAIT)
        manager._command_cancel(source)
        time.sleep(1.0)

        self.assertEqual(self._save_commands(), [])
        self.assertTrue(
            any("已取消" in text for text in self._broadcasts())
        )
        self.assertTrue(
            any("已取消本次操作" in reply for reply in source.replies)
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

    def test_manual_restart_saves_then_stops(self) -> None:
        manager = self._make_manager(1, 1)
        source = FakeSource(player="Admin", console=False)
        manager._command_restart(source)

        deadline = time.monotonic() + 5
        while time.monotonic() < deadline and "stop" not in self.server.commands:
            time.sleep(0.01)

        self.assertEqual(self._save_commands(), ["save-all", "stop"])
        self.assertTrue(
            any("正在保存并重启" in text for text in self._broadcasts())
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
        manager = self._make_manager(1, 1, 播报方式="tellraw")
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
            self.server.saved_configs[-1]["保存间隔分钟"],
            2,
        )
        self.assertEqual(
            self.server.saved_configs[-1]["播报方式"],
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
        manager = self._make_manager(60, 10, 保存间隔分钟=2)
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


class GuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()

    def tearDown(self) -> None:
        self.server.close()

    def _make_manager(self, **overrides: object) -> AutoSaveManager:
        raw = default_config_dict()
        raw["保存间隔分钟"] = 60
        raw["保存预警秒数"] = 5
        raw["保存倒计时秒数"] = 5
        raw.update(overrides)
        config, _ = parse_config(raw)
        manager = AutoSaveManager(self.server, config)
        manager.start()
        return manager

    def test_guard_keeps_mcdr_alive(self) -> None:
        manager = self._make_manager()

        self.assertIs(self.server.exit_after_stop, False)
        manager.shutdown()

    def test_guard_off_restores_exit_flag(self) -> None:
        manager = self._make_manager(崩溃守护=False)
        source = FakeSource()

        self.assertIs(self.server.exit_after_stop, True)
        manager._command_guard_on(source)
        self.assertIs(self.server.exit_after_stop, False)
        manager._command_guard_off(source)
        self.assertIs(self.server.exit_after_stop, True)
        manager.shutdown()

    def test_server_stop_restarts_when_guard_on(self) -> None:
        manager = self._make_manager(拉起延迟秒数=0)
        manager.handle_server_start()
        manager.handle_server_startup()

        manager.handle_server_stop(0)

        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and self.server.start_calls == 0:
            time.sleep(0.01)

        self.assertEqual(self.server.start_calls, 1)
        manager.shutdown()

    def test_server_stop_does_nothing_when_guard_off(self) -> None:
        manager = self._make_manager(崩溃守护=False, 拉起延迟秒数=0)
        manager.handle_server_start()
        manager.handle_server_startup()

        manager.handle_server_stop(0)
        time.sleep(0.3)

        self.assertEqual(self.server.start_calls, 0)
        manager.shutdown()

    def test_interrupt_cancels_guard_restart(self) -> None:
        manager = self._make_manager(拉起延迟秒数=30)
        manager.handle_server_start()
        manager.handle_server_startup()
        manager.handle_server_stop(0)

        source = FakeSource()
        manager._command_interrupt(source)
        time.sleep(0.2)

        self.assertEqual(self.server.start_calls, 0)
        self.assertTrue(any("打断" in reply for reply in source.replies))
        manager.shutdown()

    def test_crash_limit_pauses_guard(self) -> None:
        manager = self._make_manager(拉起延迟秒数=0, 崩溃次数上限=2)
        for _ in range(3):
            manager.handle_server_start()
            manager.handle_server_startup()
            manager.handle_server_stop(1)
            time.sleep(0.1)

        with manager._lock:
            halted = manager._guard_halted
        self.assertTrue(halted)
        self.assertEqual(self.server.start_calls, 1)
        manager.shutdown()

    def test_startup_failure_pauses_guard(self) -> None:
        manager = self._make_manager(拉起延迟秒数=0)
        for _ in range(2):
            manager.handle_server_start()
            manager.handle_server_stop(1)
            time.sleep(0.1)

        with manager._lock:
            halted = manager._guard_halted
        self.assertTrue(halted)
        manager.shutdown()

    def test_guard_on_clears_halt(self) -> None:
        manager = self._make_manager(拉起延迟秒数=0, 崩溃次数上限=1)
        manager.handle_server_start()
        manager.handle_server_startup()
        manager.handle_server_stop(1)

        with manager._lock:
            self.assertTrue(manager._guard_halted)

        source = FakeSource()
        manager._command_guard_on(source)

        with manager._lock:
            self.assertFalse(manager._guard_halted)
            self.assertEqual(len(manager._crash_times), 0)
        manager.shutdown()

    def test_shutdown_disables_guard_and_stops(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_shutdown(source)

        self.assertEqual(self.server.stop_exit_calls, 1)
        with manager._lock:
            self.assertFalse(manager._guard_enabled)
        self.assertTrue(any("停止服务器" in reply for reply in source.replies))
        manager.shutdown()

    def test_start_command_starts_stopped_server(self) -> None:
        manager = self._make_manager()
        self.server.running = False
        source = FakeSource()

        manager._command_start(source)

        self.assertEqual(self.server.start_calls, 1)
        self.assertTrue(any("启动" in reply for reply in source.replies))
        manager.shutdown()


class PluginLifecycleTests(unittest.TestCase):
    """验证 MCDR 调用 on_load / on_unload 时的完整装配流程。"""

    def setUp(self) -> None:
        self.server = FakeServer()

    def tearDown(self) -> None:
        self.server.close()

    def test_on_load_generates_chinese_config(self) -> None:
        import autosave

        # 空配置模拟首次安装，插件应补齐默认值并以中文键写回。
        self.server.stored_config = {}
        autosave.on_load(self.server, None)

        self.assertTrue(self.server.saved_configs)
        payload = self.server.saved_configs[-1]
        self.assertIn("配置说明", payload)
        self.assertIn("崩溃守护", payload)
        self.assertIn("提示文字", payload)
        self.assertNotIn("interval_minutes", payload)
        self.assertIs(self.server.exit_after_stop, False)

        autosave.on_unload(self.server)


class ScheduleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.server = FakeServer()

    def tearDown(self) -> None:
        self.server.close()

    def _make_manager(self, **overrides: object) -> AutoSaveManager:
        raw = default_config_dict()
        raw["保存间隔分钟"] = 60
        raw["保存预警秒数"] = 5
        raw["保存倒计时秒数"] = 5
        raw.update(overrides)
        config, _ = parse_config(raw)
        manager = AutoSaveManager(self.server, config)
        manager.start()
        return manager

    def test_timed_restart_becomes_pending_flow(self) -> None:
        manager = self._make_manager(定时重启间隔分钟=1)

        with manager._lock:
            self.assertIs(manager._flow_kind, FlowKind.RESTART)
            self.assertIsNotNone(manager._next_restart_at)
        manager.shutdown()

    def test_delay_postpones_next_restart(self) -> None:
        manager = self._make_manager(定时重启间隔分钟=10)
        source = FakeSource()

        with manager._lock:
            before = manager._next_restart_at
        assert before is not None

        manager._command_delay(source, {"duration": "1h"})

        with manager._lock:
            after = manager._next_restart_at
        assert after is not None
        self.assertAlmostEqual(after - before, 3600, delta=2)
        self.assertTrue(any("已延后" in reply for reply in source.replies))
        manager.shutdown()

    def test_delay_accepts_mixed_units(self) -> None:
        manager = self._make_manager(定时重启间隔分钟=10)
        source = FakeSource()

        with manager._lock:
            before = manager._next_restart_at
        assert before is not None

        manager._command_delay(source, {"duration": "1h30m15s"})

        with manager._lock:
            after = manager._next_restart_at
        assert after is not None
        self.assertAlmostEqual(after - before, 5415, delta=2)
        manager.shutdown()

    def test_delay_rejects_invalid_duration(self) -> None:
        manager = self._make_manager(定时重启间隔分钟=10)
        source = FakeSource()

        manager._command_delay(source, {"duration": "abc"})

        self.assertTrue(
            any("无法识别时长" in reply for reply in source.replies)
        )
        manager.shutdown()

    def test_delay_schedules_one_shot_restart_when_timer_disabled(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_delay(source, {"duration": "10m"})

        with manager._lock:
            scheduled = manager._next_restart_at
        self.assertIsNotNone(scheduled)
        assert scheduled is not None
        self.assertAlmostEqual(scheduled - time.monotonic(), 600, delta=2)
        self.assertTrue(any("已延后" in reply for reply in source.replies))
        manager.shutdown()

    def test_delay_accumulates(self) -> None:
        manager = self._make_manager(定时重启间隔分钟=10)
        source = FakeSource()

        with manager._lock:
            before = manager._next_restart_at
        assert before is not None

        manager._command_delay(source, {"duration": "10m"})
        manager._command_delay(source, {"duration": "20m"})

        with manager._lock:
            after = manager._next_restart_at
        assert after is not None
        self.assertAlmostEqual(after - before, 1800, delta=2)
        manager.shutdown()

    def test_interrupt_cancels_pending_restart(self) -> None:
        manager = self._make_manager(定时重启间隔分钟=1)
        source = FakeSource()

        with manager._lock:
            before = manager._next_restart_at
        assert before is not None

        manager._command_interrupt(source)

        with manager._lock:
            after = manager._next_restart_at
        assert after is not None
        self.assertGreater(after, before)
        self.assertTrue(any("打断" in reply for reply in source.replies))
        manager.shutdown()

    def test_interrupt_clears_one_shot_delay_restart(self) -> None:
        """回归：定时重启关闭时，interrupt 必须清掉 delay 产生的一次性重启。

        早期实现只重排不清空，_next_restart_at 会被重新捡回来，等于没打断。
        """
        manager = self._make_manager()
        source = FakeSource()

        manager._command_delay(source, {"duration": "30m"})
        with manager._lock:
            self.assertIsNotNone(manager._next_restart_at)

        manager._command_interrupt(source)

        with manager._lock:
            self.assertIsNone(manager._next_restart_at)
        self.assertTrue(any("打断" in reply for reply in source.replies))
        manager.shutdown()

    def test_interrupt_without_pending_restart_reports_none(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_interrupt(source)

        self.assertTrue(
            any("没有待执行的重启" in reply for reply in source.replies)
        )
        manager.shutdown()

    def test_status_reports_guard_and_restart(self) -> None:
        manager = self._make_manager(定时重启间隔分钟=10)
        source = FakeSource()

        manager._command_status(source)

        joined = "\n".join(source.replies)
        self.assertIn("崩溃守护", joined)
        self.assertIn("下一次自动重启", joined)
        manager.shutdown()

    def test_help_lists_all_subcommands(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_help(source)

        joined = "\n".join(source.replies)
        for keyword in (
            "run",
            "restart",
            "interrupt",
            "delay",
            "guard on",
            "shutdown",
            "时长写法",
        ):
            self.assertIn(keyword, joined)
        manager.shutdown()


class ScheduledFlowTests(unittest.TestCase):
    """验证 restart / shutdown 带时长时的预约流程、折半播报与自动保存。"""

    def setUp(self) -> None:
        self.server = FakeServer()

    def tearDown(self) -> None:
        self.server.close()

    def _make_manager(self, **overrides: object) -> AutoSaveManager:
        raw = default_config_dict()
        raw["保存间隔分钟"] = 60
        raw["保存预警秒数"] = 5
        raw["保存倒计时秒数"] = 5
        raw.update(overrides)
        config, _ = parse_config(raw)
        manager = AutoSaveManager(self.server, config)
        manager.start()
        return manager

    def _broadcasts(self) -> list[str]:
        return [
            command[len(SAY_PREFIX):]
            for command in self.server.commands
            if command.startswith(SAY_PREFIX)
        ]

    def _save_commands(self) -> list[str]:
        return [
            command
            for command in self.server.commands
            if not command.startswith(SAY_PREFIX)
        ]

    def _wait_for(self, predicate, timeout: float = 8.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.01)
        return False

    def test_announce_points_halve_remaining(self) -> None:
        points = AutoSaveManager._announce_points(1800, 60, 1000.0)

        self.assertEqual([value for _at, value in points], [900, 450, 225, 112])
        self.assertAlmostEqual(points[0][0], 100.0, delta=0.01)
        self.assertAlmostEqual(points[-1][0], 887.5, delta=0.01)

    def test_announce_points_stop_when_short(self) -> None:
        # 剩余时间不足下限时不产生折半播报，交由正式流程接管。
        self.assertEqual(AutoSaveManager._announce_points(90, 60, 1000.0), [])

    def test_restart_with_duration_defers_stop(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_restart(source, {"duration": "30m"})
        time.sleep(0.2)

        self.assertEqual(self._save_commands(), [])
        with manager._lock:
            self.assertIs(manager._phase, Phase.SCHEDULED)
            self.assertTrue(manager._flow_active)
            self.assertIs(manager._flow_kind, FlowKind.RESTART)
        self.assertTrue(any("已预约" in reply for reply in source.replies))
        self.assertTrue(
            any("30分钟" in text for text in self._broadcasts())
        )
        manager.shutdown()

    def test_restart_without_duration_runs_immediately(self) -> None:
        manager = self._make_manager(保存预警秒数=1, 保存倒计时秒数=1)
        source = FakeSource()

        manager._command_restart(source, {})

        self.assertTrue(
            self._wait_for(lambda: "stop" in self.server.commands, timeout=6)
        )
        self.assertEqual(self._save_commands(), ["save-all", "stop"])
        manager.shutdown()

    def test_invalid_duration_is_rejected(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_restart(source, {"duration": "abc"})
        time.sleep(0.1)

        self.assertTrue(
            any("无法识别时长" in reply for reply in source.replies)
        )
        with manager._lock:
            self.assertFalse(manager._flow_active)
        self.assertEqual(self.server.commands, [])
        manager.shutdown()

    def test_short_duration_compresses_warning(self) -> None:
        manager = self._make_manager(保存预警秒数=60, 保存倒计时秒数=10)
        source = FakeSource()

        started = time.monotonic()
        manager._command_restart(source, {"duration": "2s"})

        self.assertTrue(
            self._wait_for(lambda: "stop" in self.server.commands, timeout=8)
        )
        self.assertLess(time.monotonic() - started, 6)
        self.assertTrue(
            any("2 秒后重启" in text for text in self._broadcasts())
        )
        manager.shutdown()

    def test_delayed_shutdown_disables_guard_before_stop(self) -> None:
        manager = self._make_manager(保存预警秒数=1, 保存倒计时秒数=1)
        source = FakeSource()

        manager._command_shutdown(source, {"duration": "2s"})

        self.assertTrue(
            self._wait_for(
                lambda: self.server.stop_exit_calls >= 1,
                timeout=10,
            )
        )
        with manager._lock:
            self.assertFalse(manager._guard_enabled)
        self.assertIs(self.server.exit_after_stop, True)
        self.assertTrue(any("关服" in text for text in self._broadcasts()))
        manager.shutdown()

    def test_interrupt_cancels_scheduled_restart(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_restart(source, {"duration": "30m"})
        time.sleep(0.1)
        manager._command_interrupt(source)

        self.assertTrue(
            self._wait_for(lambda: not manager._flow_active, timeout=5)
        )
        self.assertEqual(self._save_commands(), [])
        self.assertTrue(
            any("本次重启已取消" in text for text in self._broadcasts())
        )
        manager.shutdown()

    def test_scheduled_wait_keeps_saving(self) -> None:
        manager = self._make_manager(保存预警秒数=1, 保存倒计时秒数=1)
        source = FakeSource()

        with mock.patch.object(
            AutoSaveConfig,
            "interval_seconds",
            new_callable=mock.PropertyMock,
            return_value=0.5,
        ):
            manager._command_restart(source, {"duration": "2s"})
            self.assertTrue(
                self._wait_for(
                    lambda: "stop" in self.server.commands,
                    timeout=8,
                )
            )

        saves = [cmd for cmd in self._save_commands() if cmd == "save-all"]
        self.assertGreaterEqual(len(saves), 2)
        manager.shutdown()

    def test_status_reports_scheduled_flow(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_restart(source, {"duration": "10m"})
        manager._command_status(source)

        joined = "\n".join(source.replies)
        self.assertIn("已预约重启", joined)
        self.assertIn("等待时间到达", joined)
        manager.shutdown()

    def test_help_documents_duration_forms(self) -> None:
        manager = self._make_manager()
        source = FakeSource()

        manager._command_help(source)

        joined = "\n".join(source.replies)
        self.assertIn("restart <时长>", joined)
        self.assertIn("shutdown <时长>", joined)
        self.assertIn("预约播报", joined)
        manager.shutdown()


if __name__ == "__main__":
    unittest.main()
