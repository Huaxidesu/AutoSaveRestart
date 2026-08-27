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
