from __future__ import annotations

import asyncio
import math
import threading
import time
from concurrent.futures import Future
from enum import Enum
from typing import Any, Callable, Dict, Optional, Set, TypeVar

from mcdreforged.api.all import (
    CommandSource,
    Integer,
    Literal,
    PluginServerInterface,
)

from .config import (
    CONFIG_FILE_NAME,
    AutoSaveConfig,
    default_config_dict,
    parse_config,
)


T = TypeVar("T")


class Phase(Enum):
    WAITING = "waiting"
    WARNING = "warning"
    SILENT_WAIT = "silent_wait"
    COUNTDOWN = "countdown"
    SAVING = "saving"


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
        self._countdown_remaining: int = 0
        self._next_auto_save_at: Optional[float] = None
        self._current_flow_save_at: Optional[float] = None
        self._cancel_reason: Optional[str] = None
        self._cancel_requested: bool = False

    def start(self) -> None:
        self._register_commands()
        with self._lock:
            self._schedule_auto_cycle_locked()
        self.server.logger.info(
            "AutoSaveRestart loaded: interval=%d min, warning=%d s, "
            "countdown=%d s",
            self.config.interval_minutes,
            self.config.warning_seconds,
            self.config.countdown_seconds,
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
            self._current_flow_save_at = None
            self._cancel_reason = None
            self._cancel_requested = True

        if cycle_future is not None:
            cycle_future.cancel()
        for future in executor_futures:
            future.cancel()

        self.server.logger.info(
            "AutoSaveRestart unloaded; all scheduled tasks cancelled"
        )

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
            self.config.messages.help,
            permission=self.config.permission_level,
        )

    def _build_command_tree(self, command_name: str) -> Literal:
        root = Literal(command_name).requires(
            self._has_permission,
            self._permission_denied_message,
        )
        root.runs(self._command_status)
        root.then(Literal("run").runs(self._command_run))
        root.then(Literal("cancel").runs(self._command_cancel))
        root.then(
            Literal("set").then(
                Integer("minutes")
                .at_min(1)
                .runs(self._command_set_interval)
            )
        )
        return root

    def _has_permission(self, source: CommandSource) -> bool:
        return source.has_permission(self.config.permission_level)

    def _permission_denied_message(self, source: CommandSource) -> str:
        del source
        return self.config.messages.permission_denied

    def _command_status(self, source: CommandSource) -> None:
        with self._lock:
            phase = self._phase
            flow_active = self._flow_active
            countdown_remaining = self._countdown_remaining
            next_auto_save_at = self._next_auto_save_at
            current_flow_save_at = self._current_flow_save_at

        phase_text = self._phase_text(phase)
        source.reply(
            self._format_message(
                self.config.messages.status_header,
                phase=phase_text,
            )
        )

        if flow_active:
            remaining = self._remaining_text(current_flow_save_at)
            source.reply(
                self._format_message(
                    self.config.messages.status_current_flow,
                    remaining=remaining,
                )
            )
            source.reply(self.config.messages.status_next_after_flow)
        else:
            source.reply(
                self._format_message(
                    self.config.messages.status_next,
                    remaining=self._remaining_text(next_auto_save_at),
                )
            )

        if phase is Phase.COUNTDOWN:
            source.reply(
                self._format_message(
                    self.config.messages.status_countdown,
                    seconds=countdown_remaining,
                )
            )
        else:
            source.reply(self.config.messages.status_not_countdown)

    def _command_run(self, source: CommandSource) -> None:
        if not self.server.is_server_running():
            source.reply(self.config.messages.manual_server_offline)
            return

        with self._lock:
            if self._shutdown:
                return
            if self._flow_active:
                source.reply(self.config.messages.already_running)
                return

            old_future = self._cycle_future
            self._generation += 1
            generation = self._generation
            self._flow_active = True
            self._phase = Phase.WARNING
            self._countdown_remaining = 0
            self._next_auto_save_at = None
            self._current_flow_save_at = (
                time.monotonic() + self.config.warning_seconds
            )
            self._cancel_reason = None
            self._cancel_requested = False

            future = self.server.schedule_task(
                self._manual_cycle(generation)
            )
            self._cycle_future = future
            future.add_done_callback(self._on_cycle_done)

        if old_future is not None:
            old_future.cancel()
        source.reply(self.config.messages.manual_started)

    def _command_cancel(self, source: CommandSource) -> None:
        with self._lock:
            if (
                self._shutdown
                or not self._flow_active
                or self._phase is not Phase.COUNTDOWN
                or self._cycle_future is None
            ):
                source.reply(self.config.messages.cancel_not_available)
                return

            actor = self._actor_name(source)
            self._cancel_reason = self._format_message(
                self.config.messages.cancel_reason_admin,
                actor=actor,
            )
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
            source.reply(self.config.messages.cancel_not_available)

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
            source.reply(self.config.messages.config_save_failed)
            return

        minimum_minutes = max(
            1,
            (self.config.warning_seconds + 59) // 60,
        )
        if minutes_value < minimum_minutes:
            source.reply(
                self._format_message(
                    self.config.messages.interval_too_short,
                    minimum_minutes=minimum_minutes,
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
            source.reply(self.config.messages.config_save_failed)
            return

        with self._lock:
            if self._shutdown:
                return

            self.config = new_config
            if not self._flow_active:
                self._reset_auto_cycle_locked()

        source.reply(
            self._format_message(
                self.config.messages.interval_updated,
                minutes=minutes_value,
            )
        )

    def _reset_auto_cycle_locked(self) -> None:
        old_future = self._cycle_future
        self._generation += 1
        self._cycle_future = None
        if old_future is not None:
            old_future.cancel()
        self._schedule_auto_cycle_locked(increment_generation=False)

    def _schedule_auto_cycle_locked(
        self,
        *,
        increment_generation: bool = True,
    ) -> None:
        if self._shutdown:
            return

        if increment_generation:
            self._generation += 1
        generation = self._generation
        delay_until_save = self.config.interval_seconds
        prewarning_delay = (
            delay_until_save - self.config.warning_seconds
        )
        if prewarning_delay < 0:
            prewarning_delay = 0

        self._phase = Phase.WAITING
        self._flow_active = False
        self._countdown_remaining = 0
        self._cancel_reason = None
        self._cancel_requested = False
        self._current_flow_save_at = None
        self._next_auto_save_at = time.monotonic() + delay_until_save

        future = self.server.schedule_task(
            self._automatic_cycle(generation, prewarning_delay)
        )
        self._cycle_future = future
        future.add_done_callback(self._on_cycle_done)

    async def _automatic_cycle(
        self,
        generation: int,
        prewarning_delay: int,
    ) -> None:
        try:
            if prewarning_delay > 0:
                await asyncio.sleep(prewarning_delay)
        except asyncio.CancelledError:
            return

        with self._lock:
            if not self._is_generation_valid_locked(generation):
                return

            self._flow_active = True
            self._phase = Phase.WARNING
            self._next_auto_save_at = None
            self._current_flow_save_at = (
                time.monotonic() + self.config.warning_seconds
            )
            self._cancel_reason = None
            self._cancel_requested = False

        await self._run_save_flow(generation)

    async def _manual_cycle(self, generation: int) -> None:
        await self._run_save_flow(generation)

    async def _run_save_flow(self, generation: int) -> None:
        try:
            if not await self._server_running_async(generation):
                self.server.logger.info(
                    self.config.messages.server_offline
                )
                return

            config_snapshot = self.config
            if config_snapshot.warning_seconds > 0:
                self._set_phase(generation, Phase.WARNING)
                warning_message = self._format_message(
                    config_snapshot.messages.warning,
                    seconds=config_snapshot.warning_seconds,
                )
                if not await self._broadcast_async(
                    warning_message,
                    generation,
                ):
                    return

            silent_wait = config_snapshot.silent_wait_seconds
            if silent_wait > 0:
                self._set_phase(generation, Phase.SILENT_WAIT)
                await asyncio.sleep(silent_wait)

            for seconds in range(
                config_snapshot.countdown_seconds,
                0,
                -1,
            ):
                if not self._set_countdown(generation, seconds):
                    return

                countdown_message = self._format_message(
                    config_snapshot.messages.countdown,
                    seconds=seconds,
                )
                if not await self._broadcast_async(
                    countdown_message,
                    generation,
                ):
                    return
                await asyncio.sleep(1)

            if not self._set_phase(generation, Phase.SAVING):
                return

            if not await self._broadcast_async(
                config_snapshot.messages.saving,
                generation,
            ):
                return

            if not await self._execute_save_async(
                config_snapshot.save_command,
                generation,
            ):
                return

            await self._broadcast_async(
                config_snapshot.messages.saved,
                generation,
            )
        except asyncio.CancelledError:
            await self._announce_cancellation_if_needed(generation)
        finally:
            self._finish_flow(generation)

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

        message = self._format_message(
            self.config.messages.cancelled,
            reason=reason,
        )
        try:
            await self._run_on_executor(
                lambda: self._broadcast_cancellation_sync(
                    message,
                    generation,
                )
            )
        except asyncio.CancelledError:
            return

    def _finish_flow(self, generation: int) -> None:
        with self._lock:
            if not self._is_generation_valid_locked(generation):
                return

            self._flow_active = False
            self._countdown_remaining = 0
            self._current_flow_save_at = None
            self._cancel_reason = None
            self._cancel_requested = False
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
        message: str,
        generation: int,
    ) -> bool:
        return await self._run_on_executor(
            lambda: self._broadcast_sync(message, generation)
        )

    def _broadcast_sync(self, message: str, generation: int) -> bool:
        with self._lock:
            if not self._is_action_allowed_locked(generation):
                return False
        if not self.server.is_server_running():
            return False

        try:
            self.server.say(message)
        except (OSError, UnicodeError) as error:
            self.server.logger.error(
                "Failed to broadcast AutoSaveRestart message: %s",
                error,
            )
            return False
        return True

    def _broadcast_cancellation_sync(
        self,
        message: str,
        generation: int,
    ) -> bool:
        with self._lock:
            if not self._is_generation_valid_locked(generation):
                return False
        if not self.server.is_server_running():
            return False

        try:
            self.server.say(message)
        except (OSError, UnicodeError) as error:
            self.server.logger.error(
                "Failed to broadcast AutoSaveRestart cancellation: %s",
                error,
            )
            return False
        return True

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
        return await asyncio.wrap_future(future)

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
