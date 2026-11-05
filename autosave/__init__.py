from __future__ import annotations

from types import ModuleType
from typing import Optional

from mcdreforged.api.all import PluginServerInterface

from .plugin import AutoSaveManager, load_config


_manager: Optional[AutoSaveManager] = None


def on_load(
    server: PluginServerInterface,
    prev_module: Optional[ModuleType],
) -> None:
    del prev_module
    global _manager

    config = load_config(server)
    manager = AutoSaveManager(server, config)
    _manager = manager
    manager.start()


def on_unload(server: PluginServerInterface) -> None:
    del server
    global _manager

    manager = _manager
    _manager = None
    if manager is not None:
        manager.shutdown()


def on_server_start(server: PluginServerInterface) -> None:
    """
    服务端进程启动后立即重设 MCDR 的退出标志。

    MCDR 在每次启动服务端后都会把 EXIT_AFTER_STOP 重新置位，若不在每次启动时
    重设，崩溃守护会在第一次重启之后失效。
    """
    del server
    manager = _manager
    if manager is not None:
        manager.handle_server_start()


def on_server_startup(server: PluginServerInterface) -> None:
    del server
    manager = _manager
    if manager is not None:
        manager.handle_server_startup()


def on_server_stop(
    server: PluginServerInterface,
    server_return_code: int,
) -> None:
    del server
    manager = _manager
    if manager is not None:
        manager.handle_server_stop(server_return_code)
