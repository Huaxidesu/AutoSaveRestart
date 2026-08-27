from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple


CONFIG_FILE_NAME = "config.json"
MIN_PERMISSION_LEVEL = 3
MAX_PERMISSION_LEVEL = 4

DEFAULT_CONFIG: Dict[str, Any] = {
    "interval_minutes": 30,
    "warning_seconds": 60,
    "countdown_seconds": 10,
    "save_command": "save-all flush",
    "command_root": "!!autosave",
    "command_aliases": ["!!as"],
    "permission_level": 3,
    "messages": {
        "help": "Minecraft 自动保存管理",
        "warning": (
            "[自动保存] 服务器将在 {seconds} 秒后保存地图，"
            "请注意可能出现短暂卡顿。"
        ),
        "countdown": "[自动保存] 地图将在 {seconds} 秒后保存。",
        "saving": "[自动保存] 正在保存服务器地图……",
        "saved": "[自动保存] 地图保存命令已执行。",
        "cancelled": "[自动保存] 本次保存已取消：{reason}",
        "server_offline": "[自动保存] 游戏服务器未运行，本次保存已跳过。",
        "status_header": "[自动保存] 当前状态：{phase}",
        "status_next": "下一次自动保存：{remaining}",
        "status_current_flow": "当前保存流程预计：{remaining} 后执行保存",
        "status_countdown": "倒计时状态：是，剩余 {seconds} 秒",
        "status_not_countdown": "倒计时状态：否",
        "status_next_after_flow": "下一次自动保存：本次流程结束后重新计时",
        "manual_started": "[自动保存] 已手动触发完整保存流程。",
        "already_running": "[自动保存] 已有保存流程正在进行，未重复触发。",
        "cancel_not_available": "[自动保存] 当前不在倒计时阶段，无法取消。",
        "cancel_reason_admin": "管理员 {actor} 手动取消",
        "interval_updated": (
            "[自动保存] 自动保存间隔已修改为 {minutes} 分钟，"
            "并已重置定时器。"
        ),
        "config_save_failed": "[自动保存] 配置写入失败，间隔未修改。",
        "manual_server_offline": "[自动保存] 游戏服务器未运行，无法开始保存。",
        "permission_denied": "[自动保存] 权限不足，仅管理员或控制台可使用。",
        "interval_too_short": (
            "[自动保存] 间隔至少需要 {minimum_minutes} 分钟，"
            "否则无法容纳当前的前置预警时间。"
        ),
        "phase_waiting": "等待下一次自动保存",
        "phase_warning": "已发送前置预警",
        "phase_silent_wait": "预警后的静默等待",
        "phase_countdown": "逐秒倒计时",
        "phase_saving": "正在执行保存",
    },
}


@dataclass(frozen=True)
class MessageConfig:
    help: str
    warning: str
    countdown: str
    saving: str
    saved: str
    cancelled: str
    server_offline: str
    status_header: str
    status_next: str
    status_current_flow: str
    status_countdown: str
    status_not_countdown: str
    status_next_after_flow: str
    manual_started: str
    already_running: str
    cancel_not_available: str
    cancel_reason_admin: str
    interval_updated: str
    config_save_failed: str
    manual_server_offline: str
    permission_denied: str
    interval_too_short: str
    phase_waiting: str
    phase_warning: str
    phase_silent_wait: str
    phase_countdown: str
    phase_saving: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "help": self.help,
            "warning": self.warning,
            "countdown": self.countdown,
            "saving": self.saving,
            "saved": self.saved,
            "cancelled": self.cancelled,
            "server_offline": self.server_offline,
            "status_header": self.status_header,
            "status_next": self.status_next,
            "status_current_flow": self.status_current_flow,
            "status_countdown": self.status_countdown,
            "status_not_countdown": self.status_not_countdown,
            "status_next_after_flow": self.status_next_after_flow,
            "manual_started": self.manual_started,
            "already_running": self.already_running,
            "cancel_not_available": self.cancel_not_available,
            "cancel_reason_admin": self.cancel_reason_admin,
            "interval_updated": self.interval_updated,
            "config_save_failed": self.config_save_failed,
            "manual_server_offline": self.manual_server_offline,
            "permission_denied": self.permission_denied,
            "interval_too_short": self.interval_too_short,
            "phase_waiting": self.phase_waiting,
            "phase_warning": self.phase_warning,
            "phase_silent_wait": self.phase_silent_wait,
            "phase_countdown": self.phase_countdown,
            "phase_saving": self.phase_saving,
        }


@dataclass(frozen=True)
class AutoSaveConfig:
    interval_minutes: int
    warning_seconds: int
    countdown_seconds: int
    save_command: str
    command_root: str
    command_aliases: Tuple[str, ...]
    permission_level: int
    messages: MessageConfig

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60

    @property
    def silent_wait_seconds(self) -> int:
        return self.warning_seconds - self.countdown_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interval_minutes": self.interval_minutes,
            "warning_seconds": self.warning_seconds,
            "countdown_seconds": self.countdown_seconds,
            "save_command": self.save_command,
            "command_root": self.command_root,
            "command_aliases": list(self.command_aliases),
            "permission_level": self.permission_level,
            "messages": self.messages.to_dict(),
        }

    def with_interval_minutes(self, minutes: int) -> AutoSaveConfig:
        return AutoSaveConfig(
            interval_minutes=minutes,
            warning_seconds=self.warning_seconds,
            countdown_seconds=self.countdown_seconds,
            save_command=self.save_command,
            command_root=self.command_root,
            command_aliases=self.command_aliases,
            permission_level=self.permission_level,
            messages=self.messages,
        )


def default_config_dict() -> Dict[str, Any]:
    return deepcopy(DEFAULT_CONFIG)


def deep_merge_defaults(
    data: MutableMapping[str, Any],
    defaults: Mapping[str, Any],
) -> bool:
    changed = False
    for key, default_value in defaults.items():
        if key not in data:
            data[key] = deepcopy(default_value)
            changed = True
            continue

        current_value = data[key]
        if isinstance(default_value, Mapping):
            if not isinstance(current_value, MutableMapping):
                data[key] = deepcopy(default_value)
                changed = True
                continue
            if deep_merge_defaults(current_value, default_value):
                changed = True

    return changed


def parse_config(raw: Mapping[str, Any]) -> Tuple[AutoSaveConfig, bool]:
    working: Dict[str, Any] = deepcopy(dict(raw))
    changed = deep_merge_defaults(working, DEFAULT_CONFIG)

    interval_minutes, value_changed = _read_int(
        working,
        "interval_minutes",
        int(DEFAULT_CONFIG["interval_minutes"]),
        minimum=1,
    )
    changed = changed or value_changed

    warning_seconds, value_changed = _read_int(
        working,
        "warning_seconds",
        int(DEFAULT_CONFIG["warning_seconds"]),
        minimum=0,
    )
    changed = changed or value_changed

    countdown_seconds, value_changed = _read_int(
        working,
        "countdown_seconds",
        int(DEFAULT_CONFIG["countdown_seconds"]),
        minimum=0,
    )
    changed = changed or value_changed

    if warning_seconds < countdown_seconds:
        warning_seconds = countdown_seconds
        working["warning_seconds"] = warning_seconds
        changed = True

    minimum_interval_minutes = max(1, (warning_seconds + 59) // 60)
    if interval_minutes < minimum_interval_minutes:
        interval_minutes = minimum_interval_minutes
        working["interval_minutes"] = interval_minutes
        changed = True

    save_command, value_changed = _read_nonempty_string(
        working,
        "save_command",
        str(DEFAULT_CONFIG["save_command"]),
    )
    changed = changed or value_changed

    command_root, value_changed = _read_command_literal(
        working,
        "command_root",
        str(DEFAULT_CONFIG["command_root"]),
    )
    changed = changed or value_changed

    command_aliases, value_changed = _read_aliases(
        working,
        "command_aliases",
        command_root,
    )
    changed = changed or value_changed

    permission_level, value_changed = _read_int(
        working,
        "permission_level",
        int(DEFAULT_CONFIG["permission_level"]),
        minimum=MIN_PERMISSION_LEVEL,
        maximum=MAX_PERMISSION_LEVEL,
    )
    changed = changed or value_changed

    raw_messages = working.get("messages")
    if not isinstance(raw_messages, MutableMapping):
        raw_messages = deepcopy(DEFAULT_CONFIG["messages"])
        working["messages"] = raw_messages
        changed = True

    message_values: Dict[str, str] = {}
    default_messages = DEFAULT_CONFIG["messages"]
    if not isinstance(default_messages, Mapping):
        raise TypeError("DEFAULT_CONFIG['messages'] must be a mapping")

    for key, default_value in default_messages.items():
        value = raw_messages.get(key)
        if not isinstance(value, str) or not value:
            value = str(default_value)
            raw_messages[key] = value
            changed = True
        message_values[key] = value

    messages = MessageConfig(**message_values)
    config = AutoSaveConfig(
        interval_minutes=interval_minutes,
        warning_seconds=warning_seconds,
        countdown_seconds=countdown_seconds,
        save_command=save_command,
        command_root=command_root,
        command_aliases=tuple(command_aliases),
        permission_level=permission_level,
        messages=messages,
    )

    if config.to_dict() != working:
        changed = True

    return config, changed


def _read_int(
    data: MutableMapping[str, Any],
    key: str,
    default: int,
    *,
    minimum: int,
    maximum: Optional[int] = None,
) -> Tuple[int, bool]:
    value = data.get(key)
    is_valid_int = isinstance(value, int) and not isinstance(value, bool)
    if not is_valid_int:
        data[key] = default
        return default, True

    int_value = int(value)
    if int_value < minimum:
        data[key] = default
        return default, True
    if maximum is not None and int_value > maximum:
        data[key] = default
        return default, True
    return int_value, False


def _read_nonempty_string(
    data: MutableMapping[str, Any],
    key: str,
    default: str,
) -> Tuple[str, bool]:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        data[key] = default
        return default, True

    normalized = value.strip()
    if normalized != value:
        data[key] = normalized
        return normalized, True
    return normalized, False


def _read_command_literal(
    data: MutableMapping[str, Any],
    key: str,
    default: str,
) -> Tuple[str, bool]:
    value, changed = _read_nonempty_string(data, key, default)
    if any(character.isspace() for character in value):
        data[key] = default
        return default, True
    return value, changed


def _read_aliases(
    data: MutableMapping[str, Any],
    key: str,
    command_root: str,
) -> Tuple[List[str], bool]:
    raw_aliases = data.get(key)
    default_aliases = list(DEFAULT_CONFIG["command_aliases"])
    if not isinstance(raw_aliases, list):
        data[key] = default_aliases
        return default_aliases, True

    aliases: List[str] = []
    changed = False
    seen = {command_root}
    for item in raw_aliases:
        if not isinstance(item, str):
            changed = True
            continue

        alias = item.strip()
        if not alias or any(character.isspace() for character in alias):
            changed = True
            continue
        if alias in seen:
            changed = True
            continue

        seen.add(alias)
        aliases.append(alias)
        if alias != item:
            changed = True

    if not aliases and raw_aliases:
        aliases = [
            alias
            for alias in default_aliases
            if alias != command_root
        ]
        changed = True

    if aliases != raw_aliases:
        data[key] = aliases
        changed = True

    return aliases, changed
