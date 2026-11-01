from __future__ import annotations

import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, MutableMapping, Optional, Tuple


CONFIG_FILE_NAME = "config.json"
MIN_PERMISSION_LEVEL = 3
MAX_PERMISSION_LEVEL = 4

# 1.7.10 的 /save-all 没有 flush 参数（该参数自 1.13 起提供），默认值使用 save-all
DEFAULT_SAVE_COMMAND = "save-all"

# 全服提示的发送方式：
#   say     —— 执行原生 say 指令，颜色用 § 码（1.7.10 / GTNH 推荐）
#   tellraw —— 走 MCDR 的 server.say()，即 tellraw @a，支持 RText 富文本
BROADCAST_MODES = ("say", "tellraw")
DEFAULT_BROADCAST_MODE = "say"

DEFAULT_CONFIG: Dict[str, Any] = {
    "interval_minutes": 30,
    "warning_seconds": 60,
    "countdown_seconds": 10,
    "save_command": DEFAULT_SAVE_COMMAND,
    "broadcast_mode": DEFAULT_BROADCAST_MODE,
    "command_root": "!!autosave",
    "command_aliases": ["!!as"],
    "permission_level": 3,
    "messages": {
        "help": "Minecraft 自动保存管理",
        "warning": (
            "【自动保存】服务器将在 {seconds} 秒后保存地图，"
            "期间可能出现短暂卡顿。"
        ),
        "countdown": "【自动保存】{seconds} 秒后保存地图。",
        "saving": "【自动保存】正在保存地图，请稍候……",
        "saved": "【自动保存】地图保存完成。",
        "cancelled": "【自动保存】本次保存已取消：{reason}",
        "server_offline": "【自动保存】服务器当前未运行，本次保存已跳过。",
        "status_header": "【自动保存】当前状态：{phase}",
        "status_next": "下一次自动保存：{remaining}",
        "status_current_flow": "当前保存流程预计：{remaining} 后执行保存",
        "status_countdown": "倒计时状态：是，剩余 {seconds} 秒",
        "status_not_countdown": "倒计时状态：否",
        "status_next_after_flow": "下一次自动保存：本次流程结束后重新计时",
        "manual_started": "【自动保存】已开始手动保存流程。",
        "already_running": "【自动保存】已有保存流程正在进行，请稍候。",
        "cancel_not_available": "【自动保存】当前不在倒计时阶段，无法取消。",
        "cancel_reason_admin": "{actor} 已取消本次保存",
        "interval_updated": (
            "【自动保存】自动保存间隔已设为 {minutes} 分钟，"
            "新的计时已开始。"
        ),
        "config_save_failed": "【自动保存】设置保存失败，请检查服务器日志。",
        "manual_server_offline": "【自动保存】服务器当前未运行，无法开始保存。",
        "permission_denied": "【自动保存】权限不足，仅管理员或控制台可使用。",
        "interval_too_short": (
            "【自动保存】间隔至少需要 {minimum_minutes} 分钟，"
            "请设置更长的保存间隔。"
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
    broadcast_mode: str
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

    @property
    def use_tellraw(self) -> bool:
        return self.broadcast_mode == "tellraw"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "interval_minutes": self.interval_minutes,
            "warning_seconds": self.warning_seconds,
            "countdown_seconds": self.countdown_seconds,
            "save_command": self.save_command,
            "broadcast_mode": self.broadcast_mode,
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
            broadcast_mode=self.broadcast_mode,
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
        DEFAULT_SAVE_COMMAND,
    )
    save_command, command_changed = _normalize_save_command(save_command)
    if command_changed:
        working["save_command"] = save_command
    changed = changed or value_changed or command_changed

    broadcast_mode, value_changed = _read_broadcast_mode(working)
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
        broadcast_mode=broadcast_mode,
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


_LEGACY_FLUSH_PATTERN = re.compile(r"^save-?all\s+flush$", re.IGNORECASE)


def _normalize_save_command(command: str) -> Tuple[str, bool]:
    """
    1.7.10 的 /save-all 没有 flush 参数（该参数自 1.13 起提供），旧配置中的
    "save-all flush" 在此自动降级为 "save-all"，避免 Thermos 解析失败；
    同时将换行替换为空格，防止一条命令被拆成两行发送。
    """
    normalized = command.replace("\r", " ").replace("\n", " ").strip()
    changed = normalized != command
    if _LEGACY_FLUSH_PATTERN.match(normalized):
        normalized = "save-all"
        changed = True
    return normalized, changed


def _read_broadcast_mode(
    data: MutableMapping[str, Any],
) -> Tuple[str, bool]:
    value = data.get("broadcast_mode")
    if not isinstance(value, str):
        data["broadcast_mode"] = DEFAULT_BROADCAST_MODE
        return DEFAULT_BROADCAST_MODE, True

    mode = value.strip().lower()
    if mode not in BROADCAST_MODES:
        data["broadcast_mode"] = DEFAULT_BROADCAST_MODE
        return DEFAULT_BROADCAST_MODE, True

    if mode != value:
        data["broadcast_mode"] = mode
        return mode, True
    return mode, False


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
