from __future__ import annotations

import asyncio
import logging
import sys
import threading
import types
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from pathlib import Path
from typing import Any, Coroutine, List, Optional


class DummyNode:
    def __init__(self, value: str) -> None:
        self.value = value

    def requires(self, *args: Any, **kwargs: Any) -> DummyNode:
        del args, kwargs
        return self

    def runs(self, *args: Any, **kwargs: Any) -> DummyNode:
        del args, kwargs
        return self

    def then(self, *args: Any, **kwargs: Any) -> DummyNode:
        del args, kwargs
        return self

    def at_min(self, *args: Any, **kwargs: Any) -> DummyNode:
        del args, kwargs
        return self


class DummyInteger(DummyNode):
    pass


class DummyLiteral(DummyNode):
    pass


class DummyCommandSource:
    pass


class DummyPluginServerInterface:
    pass


def install_mcdr_stub() -> None:
    mcdr_module = types.ModuleType("mcdreforged")
    api_module = types.ModuleType("mcdreforged.api")
    all_module = types.ModuleType("mcdreforged.api.all")
    all_module.CommandSource = DummyCommandSource
    all_module.Integer = DummyInteger
    all_module.Literal = DummyLiteral
    all_module.PluginServerInterface = DummyPluginServerInterface

    sys.modules.setdefault("mcdreforged", mcdr_module)
    sys.modules.setdefault("mcdreforged.api", api_module)
    sys.modules.setdefault("mcdreforged.api.all", all_module)

    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


class FakeServer:
    def __init__(self) -> None:
        self.logger = logging.getLogger("autosave-test")
        self.running = True
        self.messages: List[str] = []
        self.commands: List[str] = []
        self.saved_configs: List[dict[str, Any]] = []
        self._executor = ThreadPoolExecutor(max_workers=1)
        self._loop = asyncio.new_event_loop()
        self._loop_thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
        )
        self._loop_thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def schedule_task(self, callback: Any) -> Future[Any]:
        if asyncio.iscoroutine(callback):
            return asyncio.run_coroutine_threadsafe(callback, self._loop)
        return self._executor.submit(callback)

    def is_server_running(self) -> bool:
        return self.running

    def say(self, message: str) -> None:
        self.messages.append(message)

    def execute(self, command: str) -> None:
        self.commands.append(command)

    def register_command(self, command: Any) -> None:
        del command

    def register_help_message(
        self,
        prefix: str,
        message: str,
        permission: int = 0,
    ) -> None:
        del prefix, message, permission

    def save_config_simple(
        self,
        config: dict[str, Any],
        file_name: str,
    ) -> None:
        del file_name
        self.saved_configs.append(config)

    async def _drain_loop(self) -> None:
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    def close(self) -> None:
        drain_future = asyncio.run_coroutine_threadsafe(
            self._drain_loop(),
            self._loop,
        )
        try:
            drain_future.result(timeout=1)
        except TimeoutError:
            drain_future.cancel()

        self._loop.call_soon_threadsafe(self._loop.stop)
        self._loop_thread.join(timeout=2)
        self._executor.shutdown(wait=True, cancel_futures=True)


class FakeSource:
    def __init__(
        self,
        *,
        permission_level: int = 4,
        player: Optional[str] = None,
        console: bool = True,
    ) -> None:
        self.permission_level = permission_level
        self.player = player
        self.is_console = console
        self.is_player = player is not None
        self.replies: List[str] = []

    def has_permission(self, level: int) -> bool:
        return self.permission_level >= level

    def reply(self, message: str) -> None:
        self.replies.append(message)
