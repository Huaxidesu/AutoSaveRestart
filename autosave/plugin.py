from __future__ import annotations

import asyncio
import math
import re
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Deque, Dict, Optional, Set, Tuple, TypeVar, Union

from mcdreforged.api.all import (
    CommandSource,
    GreedyText,
    Integer,
    Literal,
    PluginServerInterface,
    RColor,
    RStyle,
    RText,
    RTextBase,
)

from .config import (
    CONFIG_FILE_NAME,
    AutoSaveConfig,
    default_config_dict,
    parse_config,
)


T = TypeVar("T")
MessagePayload = Union[str, RTextBase]

# 插件卸载后，挂起的周期协程须在该间隔内自行退出。
# MCDR 的 TaskDoneFuture.cancel() 不会传导到 asyncio 任务，长睡眠协程
# （预警等待最长可达 interval_minutes 分钟）会拖住 MCDR 的 AsyncTaskExecutor
# 排空流程，导致 MCDR 在「正在关闭 MCDR」处长时间无响应，因此统一采用
# 分段睡眠并在每段结束时检查卸载状态。
SHUTDOWN_POLL_INTERVAL_SECONDS = 1.0

# 桥接同步任务执行器的等待上限，防止 MCDR 停机竞态下 future 永不完成。
EXECUTOR_WAIT_TIMEOUT_SECONDS = 15.0

# 服务端在启动阶段（尚未输出 Done）退出时，连续达到该次数即视为启动失败并暂停拉起。
# 启动失败通常由配置错误或端口占用导致，反复拉起只会不断刷日志。
STARTUP_FAILURE_LIMIT = 2

# 自动拉起失败后的重试次数与间隔。服务端刚退出时端口可能尚未释放，
# server.start() 会因绑定失败而返回 False，短间隔重试可覆盖该窗口。
RESTART_START_ATTEMPTS = 3
RESTART_RETRY_INTERVAL_SECONDS = 5.0

# 单次延后允许的最大时长，避免误输入把重启推到数月之后。
MAX_DELAY_SECONDS = 30 * 24 * 3600

# 1.7.10 仅支持 § 颜色码，不支持 RGB / hex，此表将 RColor 映射为对应的 § 码。
# 以 RColor 的 name 作为键，兼容 RColor 不是 Enum 的 MCDR 版本。
LEGACY_COLOR_CODES: Dict[str, str] = {
    "black": "0",
    "dark_blue": "1",
    "dark_green": "2",
    "dark_aqua": "3",
    "dark_red": "4",
    "dark_purple": "5",
    "gold": "6",
    "gray": "7",
    "dark_gray": "8",
    "blue": "9",
    "green": "a",
    "aqua": "b",
    "red": "c",
    "light_purple": "d",
    "yellow": "e",
    "white": "f",
}

_DURATION_TOKEN = re.compile(
    r"(\d+)\s*(小时|时|h|分钟|分|m|秒|s)",
    re.IGNORECASE,
)

_DURATION_FACTORS: Dict[str, int] = {
    "小时": 3600,
    "时": 3600,
    "h": 3600,
    "分钟": 60,
    "分": 60,
    "m": 60,
    "秒": 1,
    "s": 1,
}

HELP_LINES: Tuple[str, ...] = (
    "===== AutoSaveRestart 使用说明 =====",
    "本插件负责两件事：按间隔自动保存地图；在服务端退出后自动拉起，并按设定周期重启。",
    "",
    "【保存】",
    "{root}                查看当前状态（保存排期、重启排期、崩溃守护）",
    "{root} run            立即执行一次保存流程：预警 → 静默等待 → 倒计时 → 保存",
    "{root} cancel         取消正在进行的保存或重启流程",
    "{root} set <分钟>      修改自动保存间隔并写回配置文件，最小 1 分钟",
    "",
    "【重启】",
    "{root} restart        立即执行一次重启流程：保存 → 倒计时 → 停止服务端 → 自动拉起",
    "{root} interrupt      打断本次自动重启；若正在等待拉起，则取消本次拉起",
    "{root} delay <时长>    把下一次自动重启往后推，支持 30m、2h、90s、1h30m、1h30m15s",
    "{root} guard on       开启崩溃守护并清零崩溃计数",
    "{root} guard off      关闭崩溃守护，服务端停止后不再自动拉起",
    "{root} start          手动启动服务端进程，服务端已停止时使用",
    "{root} shutdown       关闭崩溃守护并正常关服，之后不会自动拉起",
    "",
    "【时长写法】",
    "单位可用 h 或 小时、m 或 分钟、s 或 秒；单独使用或任意组合均可。",
    "只写数字时按分钟计算，例如 delay 30 等同于 delay 30m。",
    "示例：delay 2h、delay 45m、delay 90s、delay 1h30m、delay 1小时30分、delay 1h30m15s。",
    "",
    "【自动重启规则】",
    "崩溃守护开启时，服务端进程退出（崩溃、控制台 stop、定时重启）后都会在「拉起延迟秒数」之后重新拉起。",
    "只有执行 shutdown 或 guard off 关闭守护后，停止服务端才不会自动拉起。",
    "「崩溃统计窗口分钟」内异常退出达到「崩溃次数上限」时自动拉起暂停，需执行 guard on 恢复。",
    "服务端在启动阶段（未输出 Done）退出属于启动失败，连续 2 次后同样暂停拉起。",
    "未启用定时重启（定时重启间隔分钟为 0）时，delay 表示从当前时刻起算，在该时长后自动重启一次。",
    "",
    "【配置文件】",
    "config/autosave/config.json，配置项全部为中文，文件内「配置说明」逐项写明用途与取值范围。",
)


def parse_duration(text: str) -> Optional[int]:
    """
    解析「1h30m15s」「2小时」「90s」这类时长写法，返回秒数。

    支持的单位为 h/小时/时、m/分钟/分、s/秒，可单独使用也可任意组合；
    只写数字时按分钟计算。无法完整解析、时长为 0 或超过 MAX_DELAY_SECONDS
    时返回 None，由调用方给出格式提示。
    """
    if not isinstance(text, str):
        return None

    cleaned = text.strip()
    if not cleaned:
        return None

    for separator in ("，", ",", " ", "\u3000"):
        cleaned = cleaned.replace(separator, "")
    if not cleaned:
        return None

    if cleaned.isdigit():
        total = int(cleaned) * 60
        return total if 0 < total <= MAX_DELAY_SECONDS else None

    total = 0
    consumed = 0
    matched = False
    for match in _DURATION_TOKEN.finditer(cleaned):
        if match.start() != consumed:
            return None
        factor = _DURATION_FACTORS.get(match.group(2).lower())
        if factor is None:
            return None
        total += int(match.group(1)) * factor
        consumed = match.end()
        matched = True

    if not matched or consumed != len(cleaned):
        return None
    if total <= 0 or total > MAX_DELAY_SECONDS:
        return None
    return total


@dataclass(frozen=True)
class Broadcast:
    """
    一条发往全服的提示。

    统一保存文本、颜色与加粗状态，发送时按 broadcast_mode 渲染：
    say 模式拼接 § 码后执行原生 say 指令（1.7.10 / GTNH 兼容性最佳），
    tellraw 模式还原为 RText 交给 server.say()。
    """

    text: str
    color: Any = None
    bold: bool = False


class Phase(Enum):
    WAITING = "waiting"
    WARNING = "warning"
    SILENT_WAIT = "silent_wait"
    COUNTDOWN = "countdown"
    SAVING = "saving"
    RESTARTING = "restarting"


class FlowKind(Enum):
    """一次流程结束时的收尾动作：只保存，或保存后重启。"""

    SAVE = "save"
    RESTART = "restart"


class AutoSaveManager:
    server: PluginServerInterface
    config: AutoSaveConfig

    def __init__(
        self,
        server: PluginServerInterface,
        config: AutoSaveConfig,
    ) -> None:
        self.server = server
        self.config = config
        self._lock: threading.RLock = threading.RLock()
        self._shutdown: bool = False
        self._generation: int = 0
        self._cycle_future: Optional[Future[Any]] = None
        self._executor_futures: Set[Future[Any]] = set()
        self._phase: Phase = Phase.WAITING
        self._flow_active: bool = False
        self._flow_kind: FlowKind = FlowKind.SAVE
        self._countdown_remaining: int = 0
        self._next_auto_save_at: Optional[float] = None
        self._next_restart_at: Optional[float] = None
        self._current_flow_save_at: Optional[float] = None
        self._cancel_reason: Optional[str] = None
        self._cancel_requested: bool = False

        # 崩溃守护相关状态。_guard_enabled 为运行期开关，加载时取自配置；
        # guard off / shutdown 只改运行期值，重新加载插件后恢复配置值。
        self._guard_enabled: bool = config.restart.guard
        self._guard_halted: bool = False
        self._startup_done: bool = False
        self._startup_failures: int = 0
        self._crash_times: Deque[float] = deque()
        self._last_return_code: Optional[int] = None
        self._awaiting_startup: bool = False
        self._restart_dispatched: bool = False

        # 守护拉起使用独立线程等待延迟，便于被 interrupt 打断。
        self._restart_cancel: threading.Event = threading.Event()
        self._restart_thread: Optional[threading.Thread] = None
        self._restart_deadline: Optional[float] = None

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self) -> None:
        self._register_commands()
        self._apply_exit_flag()
        now = time.monotonic()
        with self._lock:
            self._next_auto_save_at = now + self.config.interval_seconds
            self._next_restart_at = (
                now + self.config.restart.interval_seconds
                if self.config.restart.timed_restart_enabled
                else None
            )
            self._schedule_auto_cycle_locked()
        self.server.logger.info(
            "AutoSaveRestart loaded: interval=%d min, warning=%d s, "
            "countdown=%d s, guard=%s, restart_interval=%d min, "
            "broadcast=%s, save_command=%r",
            self.config.interval_minutes,
            self.config.warning_seconds,
            self.config.countdown_seconds,
            self._guard_enabled,
            self.config.restart.interval_minutes,
            self.config.broadcast_mode,
            self.config.save_command,
        )

    def shutdown(self) -> None:
        with self._lock:
            if self._shutdown:
                return

            self._shutdown = True
            self._generation += 1
            cycle_future = self._cycle_future
            self._cycle_future = None
            executor_futures = tuple(self._executor_futures)
            self._executor_futures.clear()
            self._flow_active = False
            self._countdown_remaining = 0
            self._next_auto_save_at = None
            self._next_restart_at = None
            self._current_flow_save_at = None
            self._cancel_reason = None
            self._cancel_requested = True
            restart_thread = self._restart_thread
            self._restart_thread = None
            self._restart_cancel.set()

        if cycle_future is not None:
            cycle_future.cancel()
        for future in executor_futures:
            future.cancel()
        if restart_thread is not None:
            restart_thread.join(timeout=2)

        self.server.logger.info(
            "AutoSaveRestart unloaded; all scheduled tasks cancelled"
        )

    def _apply_exit_flag(self) -> None:
        """
        让 MCDR 在服务端退出后保持运行。

        MCDR 每次启动服务端后都会把 EXIT_AFTER_STOP 重新置位，因此该标志
        必须在每次服务端启动时重设，只在插件加载时设置一次会在第一次重启后失效。
        """
        setter = getattr(self.server, "set_exit_after_stop_flag", None)
        if setter is None:
            if self._guard_enabled:
                self.server.logger.warning(
                    "Current MCDR has no set_exit_after_stop_flag; "
                    "MCDR will exit together with the server, "
                    "auto restart requires an outer restart loop"
                )
            return
        setter(not self._guard_enabled)

    # ------------------------------------------------------------------
    # MCDR 事件
    # ------------------------------------------------------------------

    def handle_server_start(self) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._startup_done = False
            self._restart_dispatched = False
        self._apply_exit_flag()

    def handle_server_startup(self) -> None:
        now = time.monotonic()
        with self._lock:
            if self._shutdown:
                return
            self._startup_done = True
            self._startup_failures = 0
            self._next_auto_save_at = now + self.config.interval_seconds
            if self.config.restart.timed_restart_enabled:
                self._next_restart_at = (
                    now + self.config.restart.interval_seconds
                )
            else:
                self._next_restart_at = None
            self._awaiting_startup = False
            self._schedule_auto_cycle_locked()

    def handle_server_stop(self, return_code: int) -> None:
        now = time.monotonic()
        with self._lock:
            if self._shutdown:
                return

            self._last_return_code = return_code
            started = self._startup_done
            self._startup_done = False
            self._abort_flow_locked()
            self._next_auto_save_at = None
            self._next_restart_at = None
            self._awaiting_startup = True

            if not self._guard_enabled:
                self.server.logger.info(
                    "Server stopped (code=%s); crash guard is off, "
                    "no restart will be scheduled",
                    return_code,
                )
                return

            if self._guard_halted:
                self.server.logger.warning(
                    "Server stopped (code=%s); crash guard is paused, "
                    "run guard on to resume",
                    return_code,
                )
                return

            if self._record_exit_locked(started, return_code, now):
                return

            delay = self.config.restart.delay_seconds

        self._schedule_guard_restart(delay)

    def _record_exit_locked(
        self,
        started: bool,
        return_code: int,
        now: float,
    ) -> bool:
        """
        记录一次退出并判断是否达到暂停阈值，返回 True 表示已暂停拉起。

        未进入 Done 的退出按启动失败计数；进入 Done 后的非 0 退出按崩溃计数，
        正常 stop（返回码 0）只重启不计数。
        """
        if not started:
            self._startup_failures += 1
            if self._startup_failures >= STARTUP_FAILURE_LIMIT:
                self._guard_halted = True
                self.server.logger.error(
                    "Server exited during startup %d times; "
                    "auto restart paused",
                    self._startup_failures,
                )
                return True
            self.server.logger.warning(
                "Server exited during startup (attempt %d/%d)",
                self._startup_failures,
                STARTUP_FAILURE_LIMIT,
            )
            return False

        if return_code != 0:
            self._crash_times.append(now)

        window = self.config.restart.crash_window_seconds
        while self._crash_times and now - self._crash_times[0] > window:
            self._crash_times.popleft()

        limit = self.config.restart.crash_limit
        if limit > 0 and len(self._crash_times) >= limit:
            self._guard_halted = True
            self.server.logger.error(
                "Server crashed %d times within %d minutes; "
                "auto restart paused",
                len(self._crash_times),
                self.config.restart.crash_window_minutes,
            )
            return True

        return False

    def _schedule_guard_restart(self, delay_seconds: int) -> None:
        self._restart_cancel.clear()
        self._restart_deadline = time.monotonic() + max(0, delay_seconds)
        thread = threading.Thread(
            target=self._guard_restart_worker,
            name="AutoSaveRestart-Guard",
            daemon=True,
        )
        with self._lock:
            if self._shutdown:
                return
            self._restart_thread = thread
        thread.start()

    def _guard_restart_worker(self) -> None:
        with self._lock:
            deadline = self._restart_deadline
        wait_seconds = 0.0 if deadline is None else deadline - time.monotonic()
        if wait_seconds > 0 and self._restart_cancel.wait(wait_seconds):
            self.server.logger.info(
                "Scheduled server restart was interrupted"
            )
            return

        attempts = 0
        while attempts < RESTART_START_ATTEMPTS:
            with self._lock:
                if (
                    self._shutdown
                    or not self._guard_enabled
                    or self._guard_halted
                ):
                    return
            if self.server.start():
                self.server.logger.info(
                    "Server restarted by crash guard (attempt %d)",
                    attempts + 1,
                )
                return
            attempts += 1
            if attempts < RESTART_START_ATTEMPTS:
                if self._restart_cancel.wait(
                    RESTART_RETRY_INTERVAL_SECONDS
                ):
                    return

        self.server.logger.error(
            "Failed to start the server after %d attempts; "
            "auto restart abandoned",
            RESTART_START_ATTEMPTS,
        )

    # ------------------------------------------------------------------
    # 指令注册
    # ------------------------------------------------------------------

    def _register_commands(self) -> None:
        command_names = (
            self.config.command_root,
            *self.config.command_aliases,
        )
        for command_name in command_names:
            self.server.register_command(
                self._build_command_tree(command_name)
            )

        self.server.register_help_message(
            self.config.command_root,
            self._styled_text(
                self.config.messages.help,
                RColor.aqua,
            ),
            permission=self.config.permission_level,
        )

    def _build_command_tree(self, command_name: str) -> Literal:
        root = Literal(command_name).requires(
            self._has_permission,
            self._permission_denied_message,
        )
        root.runs(self._command_status)
        root.then(Literal("help").runs(self._command_help))
        root.then(Literal("run").runs(self._command_run))
        root.then(Literal("restart").runs(self._command_restart))
        root.then(Literal("cancel").runs(self._command_cancel))
        root.then(Literal("interrupt").runs(self._command_interrupt))
        root.then(
            Literal("delay").then(
                GreedyText("duration").runs(self._command_delay)
            )
        )
        root.then(
            Literal("set").then(
                Integer("minutes")
                .at_min(1)
                .runs(self._command_set_interval)
            )
        )
        root.then(
            Literal("guard")
            .then(Literal("on").runs(self._command_guard_on))
            .then(Literal("off").runs(self._command_guard_off))
        )
        root.then(Literal("start").runs(self._command_start))
        root.then(Literal("shutdown").runs(self._command_shutdown))
        return root

    def _has_permission(self, source: CommandSource) -> bool:
        return source.has_permission(self.config.permission_level)

    def _permission_denied_message(
        self,
        source: CommandSource,
    ) -> MessagePayload:
        del source
        return self._styled_text(
            self.config.messages.permission_denied,
            RColor.red,
        )

    # ------------------------------------------------------------------
    # 状态与帮助
    # ------------------------------------------------------------------

    def _command_status(self, source: CommandSource) -> None:
        with self._lock:
            phase = self._phase
            flow_active = self._flow_active
            countdown_remaining = self._countdown_remaining
            next_auto_save_at = self._next_auto_save_at
            next_restart_at = self._next_restart_at
            current_flow_save_at = self._current_flow_save_at
            guard_enabled = self._guard_enabled
            guard_halted = self._guard_halted
            crash_count = len(self._crash_times)
            last_return_code = self._last_return_code
            restart_pending = (
                self._restart_thread is not None
                and self._restart_thread.is_alive()
            )

        source.reply(
            self._styled_text(
                self._format_message(
                    self.config.messages.status_header,
                    phase=self._phase_text(phase),
                ),
                RColor.aqua,
                bold=True,
            )
        )

        if flow_active:
            remaining = self._remaining_text(current_flow_save_at)
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.status_current_flow,
                        remaining=remaining,
                    ),
                    RColor.gold,
                )
            )
            source.reply(
                self._styled_text(
                    self.config.messages.status_next_after_flow,
                    RColor.gray,
                )
            )
        else:
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.status_next,
                        remaining=self._remaining_text(next_auto_save_at),
                    ),
                    RColor.yellow,
                )
            )

        if next_restart_at is not None:
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.status_restart_next,
                        remaining=self._remaining_text(next_restart_at),
                    ),
                    RColor.yellow,
                )
            )
        elif restart_pending:
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.status_restart_next,
                        remaining=self._remaining_text(self._restart_deadline),
                    ),
                    RColor.red,
                )
            )
        else:
            source.reply(
                self._styled_text(
                    self.config.messages.status_restart_disabled,
                    RColor.gray,
                )
            )

        if guard_halted:
            guard_message = self.config.messages.status_guard_halted
            guard_color = RColor.red
        elif guard_enabled:
            guard_message = self.config.messages.status_guard_on
            guard_color = RColor.green
        else:
            guard_message = self.config.messages.status_guard_off
            guard_color = RColor.gray
        source.reply(
            self._styled_text(guard_message, guard_color, bold=guard_halted)
        )

        source.reply(
            self._styled_text(
                self._format_message(
                    self.config.messages.status_crash,
                    window=self.config.restart.crash_window_minutes,
                    count=crash_count,
                ),
                RColor.gray,
            )
        )

        if last_return_code is not None:
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.status_last_exit,
                        code=last_return_code,
                    ),
                    RColor.gray,
                )
            )

        if phase is Phase.COUNTDOWN:
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.status_countdown,
                        seconds=countdown_remaining,
                    ),
                    RColor.red,
                    bold=True,
                )
            )
        else:
            source.reply(
                self._styled_text(
                    self.config.messages.status_not_countdown,
                    RColor.gray,
                )
            )

    def _command_help(self, source: CommandSource) -> None:
        root = self.config.command_root
        for line in HELP_LINES:
            text = line.replace("{root}", root)
            if text:
                source.reply(self._styled_text(text, RColor.aqua))
            else:
                source.reply("")

    # ------------------------------------------------------------------
    # 保存与重启流程
    # ------------------------------------------------------------------

    def _command_run(self, source: CommandSource) -> None:
        self._start_manual_flow(source, FlowKind.SAVE)

    def _command_restart(self, source: CommandSource) -> None:
        self._start_manual_flow(source, FlowKind.RESTART)

    def _start_manual_flow(
        self,
        source: CommandSource,
        kind: FlowKind,
    ) -> None:
        if not self.server.is_server_running():
            message = (
                self.config.messages.manual_server_offline
                if kind is FlowKind.SAVE
                else self.config.messages.server_offline
            )
            source.reply(self._styled_text(message, RColor.red))
            return

        with self._lock:
            if self._shutdown:
                return
            if self._flow_active:
                source.reply(
                    self._styled_text(
                        self.config.messages.already_running,
                        RColor.yellow,
                    )
                )
                return

            old_future = self._cycle_future
            self._generation += 1
            generation = self._generation
            self._flow_active = True
            self._flow_kind = kind
            self._restart_dispatched = False
            self._phase = Phase.WARNING
            self._countdown_remaining = 0
            self._next_auto_save_at = None
            self._current_flow_save_at = (
                time.monotonic() + self.config.warning_seconds
            )
            self._cancel_reason = None
            self._cancel_requested = False

            future = self.server.schedule_task(
                self._manual_cycle(generation, kind)
            )
            self._cycle_future = future
            future.add_done_callback(self._on_cycle_done)

        if old_future is not None:
            old_future.cancel()

        started_message = (
            self.config.messages.manual_started
            if kind is FlowKind.SAVE
            else self.config.messages.manual_restart_started
        )
        source.reply(self._styled_text(started_message, RColor.aqua))

    def _command_cancel(self, source: CommandSource) -> None:
        actor = self._actor_name(source)
        reason = self._format_message(
            self.config.messages.cancel_reason_admin,
            actor=actor,
        )
        self._cancel_active_flow(source, reason)

    def _command_interrupt(self, source: CommandSource) -> None:
        actor = self._actor_name(source)
        reason = self._format_message(
            self.config.messages.interrupt_reason_admin,
            actor=actor,
        )

        future: Optional[Future[Any]] = None
        acted = False
        with self._lock:
            if self._shutdown:
                return

            if self._flow_active and self._flow_kind is FlowKind.RESTART:
                self._cancel_reason = reason
                self._cancel_requested = True
                future = self._cycle_future
                acted = True
            elif (
                not self._flow_active
                and self._flow_kind is FlowKind.RESTART
                and self._cycle_future is not None
            ):
                # 重启还停留在等待阶段，直接作废本次排期并顺延到下一个周期。
                self._generation += 1
                future = self._cycle_future
                self._cycle_future = None
                now = time.monotonic()
                if self.config.restart.timed_restart_enabled:
                    self._next_restart_at = (
                        now + self.config.restart.interval_seconds
                    )
                if self._next_auto_save_at is None:
                    self._next_auto_save_at = (
                        now + self.config.interval_seconds
                    )
                self._schedule_auto_cycle_locked()
                acted = True

            if (
                self._restart_thread is not None
                and self._restart_thread.is_alive()
            ):
                self._restart_cancel.set()
                acted = True

        if future is not None:
            future.cancel()

        if not acted:
            source.reply(
                self._styled_text(
                    self.config.messages.interrupt_none,
                    RColor.yellow,
                )
            )
            return

        source.reply(
            self._styled_text(
                self._format_message(
                    self.config.messages.interrupt_done,
                    reason=reason,
                ),
                RColor.red,
                bold=True,
            )
        )

    def _cancel_active_flow(
        self,
        source: CommandSource,
        reason: Optional[str],
    ) -> None:
        with self._lock:
            if (
                self._shutdown
                or not self._flow_active
                or self._cycle_future is None
            ):
                source.reply(
                    self._styled_text(
                        self.config.messages.cancel_not_available,
                        RColor.yellow,
                    )
                )
                return

            self._cancel_reason = reason
            self._cancel_requested = True
            generation = self._generation
            future = self._cycle_future

        if not future.cancel():
            with self._lock:
                if (
                    generation == self._generation
                    and self._cycle_future is future
                ):
                    self._cancel_requested = False
                    self._cancel_reason = None
            source.reply(
                self._styled_text(
                    self.config.messages.cancel_not_available,
                    RColor.yellow,
                )
            )

    def _command_delay(
        self,
        source: CommandSource,
        context: Dict[str, Any],
    ) -> None:
        text = context.get("duration")
        seconds = parse_duration(text) if isinstance(text, str) else None
        if seconds is None:
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.delay_invalid,
                        text=str(text or ""),
                    ),
                    RColor.red,
                )
            )
            return

        future: Optional[Future[Any]] = None
        with self._lock:
            if self._shutdown:
                return

            now = time.monotonic()
            if self._next_restart_at is None:
                # 未启用定时重启时，把本次延后视为预约一次重启。
                self._next_restart_at = now + seconds
            else:
                self._next_restart_at += seconds
            remaining = self._next_restart_at - now

            if self._flow_active and self._flow_kind is FlowKind.RESTART:
                # 流程已开始，静默取消当前流程，由流程收尾按新的重启时间重排。
                self._cancel_requested = True
                self._cancel_reason = None
                future = self._cycle_future
            elif not self._flow_active:
                self._schedule_auto_cycle_locked()

        if future is not None:
            future.cancel()

        source.reply(
            self._styled_text(
                self._format_message(
                    self.config.messages.delay_done,
                    duration=self._format_duration(seconds),
                    remaining=self._format_duration(
                        max(0, math.ceil(remaining))
                    ),
                ),
                RColor.green,
            )
        )

    def _command_set_interval(
        self,
        source: CommandSource,
        context: Dict[str, Any],
    ) -> None:
        minutes_value = context.get("minutes")
        if not isinstance(minutes_value, int) or isinstance(
            minutes_value,
            bool,
        ):
            source.reply(
                self._styled_text(
                    self.config.messages.config_save_failed,
                    RColor.red,
                )
            )
            return

        minimum_minutes = max(
            1,
            (self.config.warning_seconds + 59) // 60,
        )
        if minutes_value < minimum_minutes:
            source.reply(
                self._styled_text(
                    self._format_message(
                        self.config.messages.interval_too_short,
                        minimum_minutes=minimum_minutes,
                    ),
                    RColor.red,
                )
            )
            return

        new_config = self.config.with_interval_minutes(minutes_value)
        try:
            self.server.save_config_simple(
                new_config.to_dict(),
                CONFIG_FILE_NAME,
            )
        except OSError as error:
            self.server.logger.error(
                "Failed to save AutoSaveRestart config: %s",
                error,
            )
            source.reply(
                self._styled_text(
                    self.config.messages.config_save_failed,
                    RColor.red,
                )
            )
            return

        with self._lock:
            if self._shutdown:
                return

            self.config = new_config
            if not self._flow_active:
                self._reset_auto_cycle_locked()

        source.reply(
            self._styled_text(
                self._format_message(
                    self.config.messages.interval_updated,
                    minutes=minutes_value,
                ),
                RColor.green,
            )
        )

    def _command_guard_on(self, source: CommandSource) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._guard_enabled = True
            self._guard_halted = False
            self._startup_failures = 0
            self._crash_times.clear()
        self._apply_exit_flag()
        source.reply(
            self._styled_text(
                self.config.messages.guard_resumed,
                RColor.green,
            )
        )

    def _command_guard_off(self, source: CommandSource) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._guard_enabled = False
        self._apply_exit_flag()
        source.reply(
            self._styled_text(
                self.config.messages.guard_off,
                RColor.yellow,
            )
        )

    def _command_start(self, source: CommandSource) -> None:
        if self.server.is_server_running():
            source.reply(
                self._styled_text(
                    self.config.messages.server_already_running,
                    RColor.yellow,
                )
            )
            return

        # 取消可能仍在等待的守护拉起，避免同时发起两次启动。
        self._restart_cancel.set()
        if self.server.start():
            source.reply(
                self._styled_text(
                    self.config.messages.start_requested,
                    RColor.aqua,
                )
            )
        else:
            source.reply(
                self._styled_text(
                    self.config.messages.start_failed,
                    RColor.red,
                )
            )

    def _command_shutdown(self, source: CommandSource) -> None:
        with self._lock:
            if self._shutdown:
                return
            self._guard_enabled = False
            self._restart_cancel.set()
        self._apply_exit_flag()

        if self.server.is_server_running():
            self.server.stop_exit()
        else:
            self.server.exit()

        source.reply(
            self._styled_text(
                self.config.messages.shutdown_done,
                RColor.gold,
                bold=True,
            )
        )

    # ------------------------------------------------------------------
    # 排期
    # ------------------------------------------------------------------

    def _reset_auto_cycle_locked(self) -> None:
        old_future = self._cycle_future
        self._generation += 1
        self._cycle_future = None
        if old_future is not None:
            old_future.cancel()
        self._next_auto_save_at = time.monotonic() + self.config.interval_seconds
        self._schedule_auto_cycle_locked(increment_generation=False)

    def _schedule_auto_cycle_locked(
        self,
        *,
        increment_generation: bool = True,
    ) -> None:
        """
        按「保存时间」与「重启时间」中较早的一个安排下一次流程。

        两个时间都以 monotonic 绝对时刻保存，因此 delay 指令只需修改
        _next_restart_at 即可生效，不必重新累计整个间隔。
        """
        if self._shutdown or self._awaiting_startup:
            return

        if increment_generation:
            self._generation += 1
        generation = self._generation
        now = time.monotonic()

        if self._next_auto_save_at is None:
            self._next_auto_save_at = now + self.config.interval_seconds

        restart_at = self._next_restart_at
        if restart_at is not None and restart_at <= now:
            # 已过期的时间点在服务端重启后才会出现，顺延一个完整周期避免立即触发。
            restart_at = now + max(1, self.config.restart.interval_seconds)
            self._next_restart_at = restart_at

        if restart_at is not None and restart_at <= self._next_auto_save_at:
            target = restart_at
            kind = FlowKind.RESTART
        else:
            target = self._next_auto_save_at
            kind = FlowKind.SAVE

        prewarning_delay = target - now - self.config.warning_seconds
        if prewarning_delay < 0:
            prewarning_delay = 0

        self._phase = Phase.WAITING
        self._flow_active = False
        self._flow_kind = kind
        self._countdown_remaining = 0
        self._cancel_reason = None
        self._cancel_requested = False
        self._current_flow_save_at = None

        future = self.server.schedule_task(
            self._automatic_cycle(generation, prewarning_delay, kind)
        )
        self._cycle_future = future
        future.add_done_callback(self._on_cycle_done)

    async def _automatic_cycle(
        self,
        generation: int,
        prewarning_delay: float,
        kind: FlowKind,
    ) -> None:
        try:
            if prewarning_delay > 0 and not await self._interruptible_sleep(
                prewarning_delay,
            ):
                return
        except asyncio.CancelledError:
            return

        with self._lock:
            if not self._is_generation_valid_locked(generation):
                return

            self._flow_active = True
            self._flow_kind = kind
            self._restart_dispatched = False
            self._phase = Phase.WARNING
            self._next_auto_save_at = None
            self._current_flow_save_at = (
                time.monotonic() + self.config.warning_seconds
            )
            self._cancel_reason = None
            self._cancel_requested = False

        await self._run_save_flow(generation, kind)

    async def _manual_cycle(
        self,
        generation: int,
        kind: FlowKind,
    ) -> None:
        await self._run_save_flow(generation, kind)

    def _flow_templates(
        self,
        config_snapshot: AutoSaveConfig,
        kind: FlowKind,
    ) -> Tuple[str, str, str, str]:
        messages = config_snapshot.messages
        if kind is FlowKind.RESTART:
            return (
                messages.restart_warning,
                messages.restart_countdown,
                messages.restarting,
                messages.restart_dispatched,
            )
        return (
            messages.warning,
            messages.countdown,
            messages.saving,
            messages.saved,
        )

    async def _run_save_flow(
        self,
        generation: int,
        kind: FlowKind,
    ) -> None:
        try:
            if not await self._server_running_async(generation):
                self.server.logger.info(
                    self.config.messages.server_offline
                )
                return

            config_snapshot = self.config
            warning_template, countdown_template, busy_template, done_template = (
                self._flow_templates(config_snapshot, kind)
            )

            if config_snapshot.warning_seconds > 0:
                self._set_phase(generation, Phase.WARNING)
                warning_message = self._format_message(
                    warning_template,
                    seconds=config_snapshot.warning_seconds,
                )
                if not await self._broadcast_async(
                    Broadcast(warning_message, RColor.gold),
                    generation,
                ):
                    return

            silent_wait = config_snapshot.silent_wait_seconds
            if silent_wait > 0:
                self._set_phase(generation, Phase.SILENT_WAIT)
                if not await self._interruptible_sleep(silent_wait):
                    return

            for seconds in range(
                config_snapshot.countdown_seconds,
                0,
                -1,
            ):
                if not self._set_countdown(generation, seconds):
                    return

                countdown_message = self._format_message(
                    countdown_template,
                    seconds=seconds,
                )
                countdown_color = (
                    RColor.red if seconds <= 5 else RColor.yellow
                )
                if not await self._broadcast_async(
                    Broadcast(
                        countdown_message,
                        countdown_color,
                        bold=seconds <= 5,
                    ),
                    generation,
                ):
                    return
                await asyncio.sleep(1)

            if not self._set_phase(generation, Phase.SAVING):
                return

            if not await self._broadcast_async(
                Broadcast(
                    busy_template,
                    RColor.aqua,
                    bold=True,
                ),
                generation,
            ):
                return

            if not await self._execute_save_async(
                config_snapshot.save_command,
                generation,
            ):
                return

            if kind is FlowKind.RESTART:
                await self._dispatch_restart_async(generation)
                return

            await self._broadcast_async(
                Broadcast(
                    done_template,
                    RColor.green,
                    bold=True,
                ),
                generation,
            )
        except asyncio.CancelledError:
            await self._announce_cancellation_if_needed(generation)
        finally:
            self._finish_flow(generation, kind)

    async def _dispatch_restart_async(self, generation: int) -> bool:
        return await self._run_on_executor(
            lambda: self._dispatch_restart_sync(generation)
        )

    def _dispatch_restart_sync(self, generation: int) -> bool:
        with self._lock:
            if not self._is_action_allowed_locked(generation):
                return False
        if not self.server.is_server_running():
            return False

        self._restart_dispatched = True
        command = self._sanitize_text(self.config.restart.stop_command)
        if self._guard_enabled:
            # 守护开启时只停止服务端，由 on_server_stop 触发重新拉起。
            self.server.execute(command)
        else:
            # 守护关闭时让 MCDR 一并退出，避免 MCDR 停留在无服务端状态。
            self.server.stop_exit()
        return True

    async def _announce_cancellation_if_needed(
        self,
        generation: int,
    ) -> None:
        with self._lock:
            if self._shutdown or generation != self._generation:
                return
            reason = self._cancel_reason

        if reason is None:
            return

        message = Broadcast(
            self._format_message(
                self.config.messages.cancelled,
                reason=reason,
            ),
            RColor.red,
            bold=True,
        )
        try:
            await self._broadcast_cancellation_async(message, generation)
        except asyncio.CancelledError:
            return

    def _abort_flow_locked(self) -> None:
        """服务端退出时作废当前流程与排期，不播报取消提示。"""
        self._generation += 1
        future = self._cycle_future
        self._cycle_future = None
        self._flow_active = False
        self._countdown_remaining = 0
        self._current_flow_save_at = None
        self._cancel_reason = None
        self._cancel_requested = False
        self._restart_dispatched = False
        if future is not None:
            future.cancel()

    def _finish_flow(self, generation: int, kind: FlowKind) -> None:
        with self._lock:
            if not self._is_generation_valid_locked(generation):
                return

            self._flow_active = False
            self._countdown_remaining = 0
            self._current_flow_save_at = None
            self._cancel_reason = None
            self._cancel_requested = False

            if self._restart_dispatched:
                # 服务端即将退出，排期推迟到重新启动完成后由 handle_server_startup 建立。
                self._awaiting_startup = True
                self._next_auto_save_at = None
                self._next_restart_at = None
                return

            now = time.monotonic()
            if kind is FlowKind.RESTART:
                # 本轮重启被取消或未发出，顺延一个完整周期后再试。
                if self.config.restart.timed_restart_enabled:
                    self._next_restart_at = (
                        now + self.config.restart.interval_seconds
                    )
                else:
                    self._next_restart_at = None
            self._next_auto_save_at = now + self.config.interval_seconds
            self._schedule_auto_cycle_locked()

    def _set_phase(self, generation: int, phase: Phase) -> bool:
        with self._lock:
            if not self._is_action_allowed_locked(generation):
                return False
            self._phase = phase
            if phase is not Phase.COUNTDOWN:
                self._countdown_remaining = 0
            return True

    def _set_countdown(self, generation: int, seconds: int) -> bool:
        with self._lock:
            if not self._is_action_allowed_locked(generation):
                return False
            self._phase = Phase.COUNTDOWN
            self._countdown_remaining = seconds
            return True

    def _is_generation_valid_locked(self, generation: int) -> bool:
        return not self._shutdown and generation == self._generation

    def _is_action_allowed_locked(self, generation: int) -> bool:
        return (
            self._is_generation_valid_locked(generation)
            and not self._cancel_requested
        )

    async def _interruptible_sleep(self, seconds: float) -> bool:
        """
        分段睡眠，每段结束时检查插件是否已进入卸载流程。

        返回 False 表示因 shutdown 提前结束，调用方应直接返回，
        避免挂起的协程拖住 MCDR 的 AsyncTaskExecutor 排空流程。
        """
        remaining = float(seconds)
        while remaining > 0:
            if self._shutdown:
                return False
            step = min(SHUTDOWN_POLL_INTERVAL_SECONDS, remaining)
            await asyncio.sleep(step)
            remaining -= step
        return not self._shutdown

    async def _server_running_async(self, generation: int) -> bool:
        return await self._run_on_executor(
            lambda: self._server_running_sync(generation)
        )

    def _server_running_sync(self, generation: int) -> bool:
        with self._lock:
            if not self._is_action_allowed_locked(generation):
                return False
        return self.server.is_server_running()

    async def _broadcast_async(
        self,
        message: Broadcast,
        generation: int,
    ) -> bool:
        return await self._run_on_executor(
            lambda: self._broadcast_sync(message, generation)
        )

    async def _broadcast_cancellation_async(
        self,
        message: Broadcast,
        generation: int,
    ) -> bool:
        return await self._run_on_executor(
            lambda: self._broadcast_sync(
                message,
                generation,
                allow_cancelled=True,
            )
        )

    def _broadcast_sync(
        self,
        message: Broadcast,
        generation: int,
        *,
        allow_cancelled: bool = False,
    ) -> bool:
        with self._lock:
            if allow_cancelled:
                allowed = self._is_generation_valid_locked(generation)
            else:
                allowed = self._is_action_allowed_locked(generation)
        if not allowed:
            return False
        if not self.server.is_server_running():
            return False

        try:
            self._deliver(message)
        except (OSError, UnicodeError) as error:
            self.server.logger.error(
                "Failed to broadcast AutoSaveRestart message: %s",
                error,
            )
            return False
        return True

    def _deliver(self, message: Broadcast) -> None:
        """
        按 broadcast_mode 发送一条 Broadcast。

        默认 say 模式执行原生 ``say`` 指令并使用 ``§`` 颜色码，兼容 1.7.10 / Thermos，
        不依赖 tellraw 的 JSON，也不受 GTNH 聊天格式化模组影响。
        tellraw 模式保留 RText 富文本，适用于较新版本的服务端。
        """
        body = self._sanitize_text(message.text)
        if not body:
            return

        if self.config.use_tellraw:
            self.server.say(
                RText(
                    body,
                    color=message.color,
                    styles=RStyle.bold if message.bold else None,
                )
            )
            return

        prefix = self._color_code(message.color)
        if message.bold:
            prefix += "\u00a7l"
        self.server.execute("say {}{}\u00a7r".format(prefix, body))

    @staticmethod
    def _color_code(color: Any) -> str:
        """
        获取颜色对应的 § 码。

        MCDR 的 RColor 自带 ``mc_code``（如 ``§6``），优先使用；取不到时按 name 查表
        （单元测试的桩对象属于此情况）。长度不为 2 的码（如 hex 长码）在 1.7.10 上
        无法渲染，返回空串。
        """
        mc_code = getattr(color, "mc_code", None)
        if isinstance(mc_code, str) and len(mc_code) == 2:
            return mc_code

        code = LEGACY_COLOR_CODES.get(
            str(getattr(color, "name", "")),
            "",
        )
        return "\u00a7" + code if code else ""

    async def _execute_save_async(
        self,
        command: str,
        generation: int,
    ) -> bool:
        return await self._run_on_executor(
            lambda: self._execute_save_sync(command, generation)
        )

    def _execute_save_sync(self, command: str, generation: int) -> bool:
        with self._lock:
            if not self._is_action_allowed_locked(generation):
                return False
        if not self.server.is_server_running():
            return False

        command = self._sanitize_text(command)
        if not command:
            return False

        try:
            self.server.execute(command)
        except (OSError, UnicodeError) as error:
            self.server.logger.error(
                "Failed to execute AutoSaveRestart command %r: %s",
                command,
                error,
            )
            return False
        return True

    async def _run_on_executor(self, callback: Callable[[], T]) -> T:
        future = self.server.schedule_task(callback)
        with self._lock:
            if self._shutdown:
                future.cancel()
            else:
                self._executor_futures.add(future)
        future.add_done_callback(self._on_executor_done)
        # MCDR 停机时同步执行器可能已不再消费任务，future 会永远悬空；
        # 限时等待保证本协程一定能够结束，不阻塞 AsyncTaskExecutor 排空。
        return await asyncio.wait_for(
            asyncio.wrap_future(future),
            timeout=EXECUTOR_WAIT_TIMEOUT_SECONDS,
        )

    def _on_executor_done(self, future: Future[Any]) -> None:
        with self._lock:
            self._executor_futures.discard(future)

    def _on_cycle_done(self, future: Future[Any]) -> None:
        with self._lock:
            if self._cycle_future is future:
                self._cycle_future = None

        if future.cancelled():
            return

        error = future.exception()
        if error is None:
            return

        self.server.logger.error(
            "Unhandled AutoSaveRestart task error",
            exc_info=(type(error), error, error.__traceback__),
        )

    def _phase_text(self, phase: Phase) -> str:
        messages = self.config.messages
        mapping = {
            Phase.WAITING: messages.phase_waiting,
            Phase.WARNING: messages.phase_warning,
            Phase.SILENT_WAIT: messages.phase_silent_wait,
            Phase.COUNTDOWN: messages.phase_countdown,
            Phase.SAVING: messages.phase_saving,
            Phase.RESTARTING: messages.phase_restarting,
        }
        return mapping[phase]

    def _remaining_text(self, target: Optional[float]) -> str:
        if target is None:
            return "未知"
        seconds = max(0, math.ceil(target - time.monotonic()))
        return self._format_duration(seconds)

    @staticmethod
    def _format_duration(total_seconds: int) -> str:
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts = []
        if hours:
            parts.append(f"{hours}小时")
        if minutes:
            parts.append(f"{minutes}分钟")
        if seconds or not parts:
            parts.append(f"{seconds}秒")
        return "".join(parts)

    def _format_message(self, template: str, **values: object) -> str:
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError, AttributeError) as error:
            self.server.logger.warning(
                "Invalid AutoSaveRestart message template %r: %s",
                template,
                error,
            )
            return template

    @staticmethod
    def _sanitize_text(text: str) -> str:
        """
        控制台按行读取指令，提示文本中的换行会把一条 ``say`` 拆成两条命令，
        因此统一压缩为单行并去除首尾空白。
        """
        return " ".join(
            str(text).replace("\r", " ").replace("\n", " ").split()
        )

    @staticmethod
    def _styled_text(
        text: str,
        color: RColor,
        *,
        bold: bool = False,
    ) -> RText:
        styles = RStyle.bold if bold else None
        return RText(text, color=color, styles=styles)

    @staticmethod
    def _actor_name(source: CommandSource) -> str:
        if source.is_console:
            return "控制台"
        if source.is_player:
            player = getattr(source, "player", None)
            if isinstance(player, str) and player:
                return player
        return "管理员"


def load_config(server: PluginServerInterface) -> AutoSaveConfig:
    defaults = default_config_dict()
    try:
        raw = server.load_config_simple(
            CONFIG_FILE_NAME,
            defaults,
            failure_policy="regen",
        )
    except (OSError, ValueError, TypeError) as error:
        server.logger.error(
            "Failed to load AutoSaveRestart config; using safe defaults: %s",
            error,
        )
        raw = defaults

    if not isinstance(raw, dict):
        server.logger.error(
            "AutoSaveRestart config root must be a JSON object; using defaults"
        )
        raw = defaults

    config, changed = parse_config(raw)
    if changed:
        try:
            server.save_config_simple(
                config.to_dict(),
                CONFIG_FILE_NAME,
            )
        except OSError as error:
            server.logger.error(
                "Failed to persist normalized AutoSaveRestart config: %s",
                error,
            )

    return config
