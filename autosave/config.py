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

# 自动重启发送给服务端的停止指令，1.7.10 原版为 stop
DEFAULT_STOP_COMMAND = "stop"

# 全服提示的发送方式：
#   say     —— 执行原生 say 指令，颜色用 § 码（1.7.10 / GTNH 推荐）
#   tellraw —— 使用 MCDR 的 server.say()，即 tellraw @a，支持 RText 富文本
BROADCAST_MODES = ("say", "tellraw")
DEFAULT_BROADCAST_MODE = "say"

# 配置文件中的说明条目。JSON 不支持注释，说明以独立字段随配置一起写入，
# 每次保存都会重写为当前版本，因此修改本常量即可更新所有已部署实例的说明。
CONFIG_NOTES: List[str] = [
    "本文件由 AutoSaveRestart 插件自动生成；除标注「需重新加载插件」的项目外，保存后立即生效。",
    "保存间隔分钟：两次自动保存之间的间隔，单位分钟，最小 1，默认 30。",
    "保存预警秒数：保存前多少秒向全服播报预警，0 表示不播报，默认 60；该值不得小于保存倒计时秒数。",
    "保存倒计时秒数：保存前最后多少秒逐秒播报，0 表示不逐秒播报，默认 10。",
    "保存指令：执行保存时发送给服务端的指令。1.7.10 只有 save-all，没有 flush 参数。",
    "播报方式：say 表示执行原生 say 指令并用 § 颜色码，tellraw 表示使用 MCDR 富文本；1.7.10 推荐 say。",
    "崩溃守护：true 表示服务端进程退出（崩溃或执行 stop）后由插件自动拉起，false 表示不拉起。",
    "拉起延迟秒数：服务端退出后等待多少秒再拉起，0 表示立即拉起，默认 5。",
    "定时重启间隔分钟：每隔多少分钟自动重启一次，0 表示关闭定时重启，默认 0。",
    "崩溃次数上限：统计窗口内异常退出达到该次数后暂停自动拉起，0 表示不限制，默认 3。",
    "崩溃统计窗口分钟：异常退出的统计窗口长度，单位分钟，默认 10。",
    "重启指令：自动重启时发送给服务端的指令，默认 stop。",
    "主指令：插件管理指令的名称，默认 !!autosave。",
    "指令别名：主指令的别名列表，默认 !!as。",
    "权限等级：执行管理指令所需的 MCDR 权限等级，3 为管理员，4 为所有者。",
    "提示文字：播报与回复文案，可用占位符见 README 的「提示文字占位符」一节。",
]

DEFAULT_MESSAGES: Dict[str, str] = {
    "帮助": "Minecraft 自动保存与自动重启管理，执行 !!autosave help 查看详细说明",
    "保存预警": (
        "【自动保存】服务器将在 {seconds} 秒后保存地图，"
        "期间可能出现短暂卡顿。"
    ),
    "保存倒计时": "【自动保存】{seconds} 秒后保存地图。",
    "正在保存": "【自动保存】正在保存地图，请稍候……",
    "保存完成": "【自动保存】地图保存完成。",
    "保存已取消": "【自动保存】本次保存已取消：{reason}",
    "服务器未运行": "【自动保存】服务器当前未运行，本次保存已跳过。",
    "状态标题": "【自动保存】当前状态：{phase}",
    "下次保存": "下一次自动保存：{remaining}",
    "当前流程": "当前流程预计：{remaining} 后执行",
    "倒计时状态": "倒计时状态：是，剩余 {seconds} 秒",
    "非倒计时": "倒计时状态：否",
    "流程结束后": "下一次自动保存：本次流程结束后重新计时",
    "手动保存开始": "【自动保存】已开始手动保存流程。",
    "流程进行中": "【自动保存】已有流程正在进行，请稍候。",
    "无法取消": "【自动保存】当前没有可取消的流程。",
    "取消原因": "{actor} 已取消本次操作",
    "间隔已更新": (
        "【自动保存】自动保存间隔已设为 {minutes} 分钟，"
        "新的计时已开始。"
    ),
    "配置保存失败": "【自动保存】设置保存失败，请检查服务器日志。",
    "手动时服务器未运行": "【自动保存】服务器当前未运行，无法开始保存。",
    "权限不足": "【自动保存】权限不足，仅管理员或控制台可使用。",
    "间隔过短": (
        "【自动保存】间隔至少需要 {minimum_minutes} 分钟，"
        "请设置更长的保存间隔。"
    ),
    "阶段等待": "等待下一次自动保存",
    "阶段预警": "已发送前置预警",
    "阶段静默": "预警后的静默等待",
    "阶段倒计时": "逐秒倒计时",
    "阶段保存": "正在执行保存",
    "阶段重启": "正在执行重启",
    "重启预警": (
        "【自动重启】服务器将在 {seconds} 秒后重启，"
        "请提前离开危险区域并结束正在进行的操作。"
    ),
    "重启倒计时": "【自动重启】{seconds} 秒后重启。",
    "正在重启": "【自动重启】正在保存并重启服务器，请稍候……",
    "重启指令已发送": "【自动重启】重启指令已发送，服务器将自动拉起。",
    "手动重启开始": "【自动重启】已开始手动重启流程。",
    "已打断重启": "【自动重启】已打断本次自动重启：{reason}",
    "无可打断": "【自动重启】当前没有待执行的重启。",
    "打断原因": "{actor} 打断了本次重启",
    "延后成功": "【自动重启】下一次自动重启已延后 {duration}，当前剩余 {remaining}。",
    "延后格式错误": (
        "【自动重启】无法识别时长「{text}」。"
        "可用写法：30m、2h、90s、1h30m、1h30m15s、1小时30分。"
    ),
    "守护已开启": "【自动重启】崩溃守护已开启，服务端退出后会自动拉起。",
    "守护已关闭": "【自动重启】崩溃守护已关闭，服务端停止后不会自动拉起。",
    "守护已暂停": (
        "【自动重启】{window} 分钟内已连续退出 {count} 次，"
        "自动拉起已暂停。检查日志后执行 !!autosave guard on 恢复。"
    ),
    "守护已恢复": "【自动重启】崩溃计数已清零，崩溃守护已恢复。",
    "关服完成": "【自动重启】崩溃守护已关闭，正在停止服务器，停止后不会自动拉起。",
    "启动请求已发送": "【自动重启】已请求启动服务端进程。",
    "启动失败": "【自动重启】服务端进程启动失败，请检查启动指令与端口占用情况。",
    "服务器已在运行": "【自动重启】服务端已在运行。",
    "状态守护开启": "崩溃守护：已开启",
    "状态守护关闭": "崩溃守护：已关闭",
    "状态守护暂停": "崩溃守护：已暂停（连续退出过多）",
    "下次重启": "下一次自动重启：{remaining}",
    "定时重启未启用": "定时重启：未启用",
    "崩溃统计": "最近 {window} 分钟内异常退出：{count} 次",
    "上次退出码": "上次服务端退出码：{code}",
    "自动拉起失败": "【自动重启】服务端进程未能启动，已放弃本次自动拉起。",
}

DEFAULT_CONFIG: Dict[str, Any] = {
    "配置说明": CONFIG_NOTES,
    "保存间隔分钟": 30,
    "保存预警秒数": 60,
    "保存倒计时秒数": 10,
    "保存指令": DEFAULT_SAVE_COMMAND,
    "播报方式": DEFAULT_BROADCAST_MODE,
    "崩溃守护": True,
    "拉起延迟秒数": 5,
    "定时重启间隔分钟": 0,
    "崩溃次数上限": 3,
    "崩溃统计窗口分钟": 10,
    "重启指令": DEFAULT_STOP_COMMAND,
    "主指令": "!!autosave",
    "指令别名": ["!!as"],
    "权限等级": 3,
    "提示文字": DEFAULT_MESSAGES,
}

# 提示文字在代码中的属性名与配置文件中的中文键一一对应。
# 代码使用英文属性名以便检索与静态检查，配置文件对使用者保持全中文。
MESSAGE_KEYS: Dict[str, str] = {
    "help": "帮助",
    "warning": "保存预警",
    "countdown": "保存倒计时",
    "saving": "正在保存",
    "saved": "保存完成",
    "cancelled": "保存已取消",
    "server_offline": "服务器未运行",
    "status_header": "状态标题",
    "status_next": "下次保存",
    "status_current_flow": "当前流程",
    "status_countdown": "倒计时状态",
    "status_not_countdown": "非倒计时",
    "status_next_after_flow": "流程结束后",
    "manual_started": "手动保存开始",
    "already_running": "流程进行中",
    "cancel_not_available": "无法取消",
    "cancel_reason_admin": "取消原因",
    "interval_updated": "间隔已更新",
    "config_save_failed": "配置保存失败",
    "manual_server_offline": "手动时服务器未运行",
    "permission_denied": "权限不足",
    "interval_too_short": "间隔过短",
    "phase_waiting": "阶段等待",
    "phase_warning": "阶段预警",
    "phase_silent_wait": "阶段静默",
    "phase_countdown": "阶段倒计时",
    "phase_saving": "阶段保存",
    "phase_restarting": "阶段重启",
    "restart_warning": "重启预警",
    "restart_countdown": "重启倒计时",
    "restarting": "正在重启",
    "restart_dispatched": "重启指令已发送",
    "manual_restart_started": "手动重启开始",
    "interrupt_done": "已打断重启",
    "interrupt_none": "无可打断",
    "interrupt_reason_admin": "打断原因",
    "delay_done": "延后成功",
    "delay_invalid": "延后格式错误",
    "guard_on": "守护已开启",
    "guard_off": "守护已关闭",
    "guard_halted": "守护已暂停",
    "guard_resumed": "守护已恢复",
    "shutdown_done": "关服完成",
    "start_requested": "启动请求已发送",
    "start_failed": "启动失败",
    "server_already_running": "服务器已在运行",
    "status_guard_on": "状态守护开启",
    "status_guard_off": "状态守护关闭",
    "status_guard_halted": "状态守护暂停",
    "status_restart_next": "下次重启",
    "status_restart_disabled": "定时重启未启用",
    "status_crash": "崩溃统计",
    "status_last_exit": "上次退出码",
    "restart_start_failed": "自动拉起失败",
}

# 旧版英文键到中文键的映射，用于升级时自动迁移已有配置。
LEGACY_KEY_MAP: Dict[str, str] = {
    "interval_minutes": "保存间隔分钟",
    "warning_seconds": "保存预警秒数",
    "countdown_seconds": "保存倒计时秒数",
    "save_command": "保存指令",
    "broadcast_mode": "播报方式",
    "command_root": "主指令",
    "command_aliases": "指令别名",
    "permission_level": "权限等级",
    "messages": "提示文字",
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
    phase_restarting: str
    restart_warning: str
    restart_countdown: str
    restarting: str
    restart_dispatched: str
    manual_restart_started: str
    interrupt_done: str
    interrupt_none: str
    interrupt_reason_admin: str
    delay_done: str
    delay_invalid: str
    guard_on: str
    guard_off: str
    guard_halted: str
    guard_resumed: str
    shutdown_done: str
    start_requested: str
    start_failed: str
    server_already_running: str
    status_guard_on: str
    status_guard_off: str
    status_guard_halted: str
    status_restart_next: str
    status_restart_disabled: str
    status_crash: str
    status_last_exit: str
    restart_start_failed: str

    def to_dict(self) -> Dict[str, str]:
        return {
            key: getattr(self, attribute)
            for attribute, key in MESSAGE_KEYS.items()
        }


@dataclass(frozen=True)
class RestartConfig:
    """
    自动重启相关设置。

    guard 为崩溃守护总开关：开启后服务端进程退出时由插件重新拉起，
    这也是定时重启能够完成闭环的前提。interval_minutes 为 0 时关闭定时重启。
    """

    guard: bool
    delay_seconds: int
    interval_minutes: int
    crash_limit: int
    crash_window_minutes: int
    stop_command: str

    @property
    def interval_seconds(self) -> int:
        return self.interval_minutes * 60

    @property
    def crash_window_seconds(self) -> int:
        return self.crash_window_minutes * 60

    @property
    def timed_restart_enabled(self) -> bool:
        return self.interval_minutes > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "崩溃守护": self.guard,
            "拉起延迟秒数": self.delay_seconds,
            "定时重启间隔分钟": self.interval_minutes,
            "崩溃次数上限": self.crash_limit,
            "崩溃统计窗口分钟": self.crash_window_minutes,
            "重启指令": self.stop_command,
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
    restart: RestartConfig
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
        payload: Dict[str, Any] = {
            "配置说明": list(CONFIG_NOTES),
            "保存间隔分钟": self.interval_minutes,
            "保存预警秒数": self.warning_seconds,
            "保存倒计时秒数": self.countdown_seconds,
            "保存指令": self.save_command,
            "播报方式": self.broadcast_mode,
        }
        payload.update(self.restart.to_dict())
        payload.update(
            {
                "主指令": self.command_root,
                "指令别名": list(self.command_aliases),
                "权限等级": self.permission_level,
                "提示文字": self.messages.to_dict(),
            }
        )
        return payload

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
            restart=self.restart,
            messages=self.messages,
        )


def default_config_dict() -> Dict[str, Any]:
    return deepcopy(DEFAULT_CONFIG)


def migrate_legacy_config(data: MutableMapping[str, Any]) -> bool:
    """
    把旧版英文配置键就地改名为中文键。

    仅在旧键存在且新键缺失时搬运取值，避免覆盖用户已经手写的中文键。
    返回是否发生了改动，调用方据此决定是否写回配置文件。
    """
    changed = False
    for legacy_key, chinese_key in LEGACY_KEY_MAP.items():
        if legacy_key not in data:
            continue
        if chinese_key not in data:
            data[chinese_key] = data[legacy_key]
        del data[legacy_key]
        changed = True

    messages = data.get("提示文字")
    if isinstance(messages, MutableMapping):
        for legacy_key, chinese_key in MESSAGE_KEYS.items():
            if legacy_key not in messages:
                continue
            if chinese_key not in messages:
                messages[chinese_key] = messages[legacy_key]
            del messages[legacy_key]
            changed = True

    return changed


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
    changed = migrate_legacy_config(working)
    if deep_merge_defaults(working, DEFAULT_CONFIG):
        changed = True

    interval_minutes, value_changed = _read_int(
        working,
        "保存间隔分钟",
        int(DEFAULT_CONFIG["保存间隔分钟"]),
        minimum=1,
    )
    changed = changed or value_changed

    warning_seconds, value_changed = _read_int(
        working,
        "保存预警秒数",
        int(DEFAULT_CONFIG["保存预警秒数"]),
        minimum=0,
    )
    changed = changed or value_changed

    countdown_seconds, value_changed = _read_int(
        working,
        "保存倒计时秒数",
        int(DEFAULT_CONFIG["保存倒计时秒数"]),
        minimum=0,
    )
    changed = changed or value_changed

    if warning_seconds < countdown_seconds:
        warning_seconds = countdown_seconds
        working["保存预警秒数"] = warning_seconds
        changed = True

    minimum_interval_minutes = max(1, (warning_seconds + 59) // 60)
    if interval_minutes < minimum_interval_minutes:
        interval_minutes = minimum_interval_minutes
        working["保存间隔分钟"] = interval_minutes
        changed = True

    save_command, value_changed = _read_nonempty_string(
        working,
        "保存指令",
        DEFAULT_SAVE_COMMAND,
    )
    save_command, command_changed = _normalize_save_command(save_command)
    if command_changed:
        working["保存指令"] = save_command
    changed = changed or value_changed or command_changed

    broadcast_mode, value_changed = _read_broadcast_mode(working)
    changed = changed or value_changed

    restart, value_changed = _read_restart(working, warning_seconds)
    changed = changed or value_changed

    command_root, value_changed = _read_command_literal(
        working,
        "主指令",
        str(DEFAULT_CONFIG["主指令"]),
    )
    changed = changed or value_changed

    command_aliases, value_changed = _read_aliases(
        working,
        "指令别名",
        command_root,
    )
    changed = changed or value_changed

    permission_level, value_changed = _read_int(
        working,
        "权限等级",
        int(DEFAULT_CONFIG["权限等级"]),
        minimum=MIN_PERMISSION_LEVEL,
        maximum=MAX_PERMISSION_LEVEL,
    )
    changed = changed or value_changed

    raw_messages = working.get("提示文字")
    if not isinstance(raw_messages, MutableMapping):
        raw_messages = deepcopy(DEFAULT_MESSAGES)
        working["提示文字"] = raw_messages
        changed = True

    message_values: Dict[str, str] = {}
    for attribute, chinese_key in MESSAGE_KEYS.items():
        default_value = DEFAULT_MESSAGES[chinese_key]
        value = raw_messages.get(chinese_key)
        if not isinstance(value, str) or not value:
            value = default_value
            raw_messages[chinese_key] = value
            changed = True
        message_values[attribute] = value

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
        restart=restart,
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


def _read_bool(
    data: MutableMapping[str, Any],
    key: str,
    default: bool,
) -> Tuple[bool, bool]:
    value = data.get(key)
    if not isinstance(value, bool):
        data[key] = default
        return default, True
    return value, False


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
    value = data.get("播报方式")
    if not isinstance(value, str):
        data["播报方式"] = DEFAULT_BROADCAST_MODE
        return DEFAULT_BROADCAST_MODE, True

    mode = value.strip().lower()
    if mode not in BROADCAST_MODES:
        data["播报方式"] = DEFAULT_BROADCAST_MODE
        return DEFAULT_BROADCAST_MODE, True

    if mode != value:
        data["播报方式"] = mode
        return mode, True
    return mode, False


def _read_restart(
    data: MutableMapping[str, Any],
    warning_seconds: int,
) -> Tuple[RestartConfig, bool]:
    changed = False

    guard, value_changed = _read_bool(
        data,
        "崩溃守护",
        bool(DEFAULT_CONFIG["崩溃守护"]),
    )
    changed = changed or value_changed

    delay_seconds, value_changed = _read_int(
        data,
        "拉起延迟秒数",
        int(DEFAULT_CONFIG["拉起延迟秒数"]),
        minimum=0,
    )
    changed = changed or value_changed

    interval_minutes, value_changed = _read_int(
        data,
        "定时重启间隔分钟",
        int(DEFAULT_CONFIG["定时重启间隔分钟"]),
        minimum=0,
    )
    changed = changed or value_changed

    # 定时重启必须留出完整的预警与倒计时时间，否则预警会在流程开始时立即触发。
    minimum_restart_minutes = max(1, (warning_seconds + 59) // 60)
    if 0 < interval_minutes < minimum_restart_minutes:
        interval_minutes = minimum_restart_minutes
        data["定时重启间隔分钟"] = interval_minutes
        changed = True

    crash_limit, value_changed = _read_int(
        data,
        "崩溃次数上限",
        int(DEFAULT_CONFIG["崩溃次数上限"]),
        minimum=0,
    )
    changed = changed or value_changed

    crash_window_minutes, value_changed = _read_int(
        data,
        "崩溃统计窗口分钟",
        int(DEFAULT_CONFIG["崩溃统计窗口分钟"]),
        minimum=1,
    )
    changed = changed or value_changed

    stop_command, value_changed = _read_nonempty_string(
        data,
        "重启指令",
        DEFAULT_STOP_COMMAND,
    )
    stop_command, command_changed = _normalize_save_command(stop_command)
    if command_changed:
        data["重启指令"] = stop_command
    changed = changed or value_changed or command_changed

    restart = RestartConfig(
        guard=guard,
        delay_seconds=delay_seconds,
        interval_minutes=interval_minutes,
        crash_limit=crash_limit,
        crash_window_minutes=crash_window_minutes,
        stop_command=stop_command,
    )
    return restart, changed


def _read_aliases(
    data: MutableMapping[str, Any],
    key: str,
    command_root: str,
) -> Tuple[List[str], bool]:
    raw_aliases = data.get(key)
    default_aliases = list(DEFAULT_CONFIG["指令别名"])
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
