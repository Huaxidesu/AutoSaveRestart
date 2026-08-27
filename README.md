# AutoSaveRestart for MCDReforged

一个基于 MCDR 原生 `AsyncTaskExecutor` 的轻量自动保存插件。无第三方运行时依赖，不使用 `time.sleep`、APScheduler 或自行维护的阻塞定时线程。

## 兼容性

- MCDReforged >= 2.14.0
- Python 3.8+
- Java 版 Minecraft 服务端；默认保存命令为 `save-all flush`

## 安装

将打包后的 `AutoSaveRestart-v1.0.0.mcdr` 放进 MCDR 的 `plugins/` 目录，然后加载或重载插件：

```text
!!MCDR plugin load AutoSaveRestart-v1.0.0.mcdr
```

插件首次加载时会自动创建：

```text
config/autosave/config.json
```

修改 `command_root`、`command_aliases`、权限或提示文本后，请重载插件使命令树重新注册。`!!autosave set <分钟>` 不需要重载，会立即写入配置并重置自动保存计时器。

## 保存流程

默认流程：

1. 距离保存 60 秒时广播前置预警。
2. 静默等待 50 秒。
3. 最后 10 秒逐秒广播倒计时。
4. 广播“正在保存”。
5. 通过 MCDR TaskExecutor 执行 `save-all flush`。
6. 广播保存命令已执行。

`interval_minutes` 表示相邻自动保存执行时刻之间的间隔。因此配置中的 `warning_seconds` 不能长于整个自动保存间隔；非法配置会在加载时安全修正并写回。

## 管理命令

默认要求 MCDR `admin`（权限等级 3）或更高权限。控制台始终拥有 owner 权限，因此可直接使用。

```text
!!autosave
!!as
```

查看当前阶段、下一次自动保存剩余时间以及是否处于逐秒倒计时。

```text
!!autosave run
```

立即开始一次完整的“预警 -> 静默等待 -> 逐秒倒计时 -> 保存”流程。如果已有保存流程正在执行，不会创建第二份任务。

```text
!!autosave cancel
```

仅在逐秒倒计时阶段可用。它会取消当前协程，阻止剩余提示和保存命令，并广播“管理员手动取消”的原因。取消后重新从完整间隔开始安排下一次自动保存。

```text
!!autosave set <分钟>
```

修改自动保存间隔，立即写入 `config/autosave/config.json`。如果当前没有保存流程，会立刻取消旧定时任务并按新间隔重新计时；如果正处于保存流程，则当前流程继续，完成后按新间隔计时。

## 默认配置

完整示例见 `config.example.json`。首次加载时 MCDR 会自动生成等价的 `config/autosave/config.json`。

```json
{
  "interval_minutes": 30,
  "warning_seconds": 60,
  "countdown_seconds": 10,
  "save_command": "save-all flush",
  "command_root": "!!autosave",
  "command_aliases": ["!!as"],
  "permission_level": 3,
  "messages": {
    "warning": "[自动保存] 服务器将在 {seconds} 秒后保存地图，请注意可能出现短暂卡顿。",
    "countdown": "[自动保存] 地图将在 {seconds} 秒后保存。",
    "saving": "[自动保存] 正在保存服务器地图……",
    "saved": "[自动保存] 地图保存命令已执行。",
    "cancelled": "[自动保存] 本次保存已取消：{reason}"
  }
}
```

`messages` 中还有帮助文本、状态查询、权限、配置错误和阶段名称等文本；不要只复制上面的缩略片段覆盖原文件。直接编辑插件自动生成的完整文件即可。

## 异步与热重载安全

插件内部只有一个“周期任务”引用。自动等待、预警、静默等待和倒计时都运行在 MCDR 原生异步执行器中的协程里，延迟使用 `asyncio.sleep()`，不会阻塞 MCDR TaskExecutor。

每次重置计时器都会增加任务 generation。旧任务即使在取消信号和实际退出之间发生极短竞态，也会因为 generation 不再匹配而拒绝广播和执行保存命令。

所有 `server.say()` 与 `server.execute()` 都再次投递到 MCDR TaskExecutor，并在真正执行前检查：

- 插件尚未卸载；
- 任务 generation 仍有效；
- Minecraft 服务端仍在运行。

`on_unload` 会先把插件标记为 shutdown 并废弃当前 generation，然后取消主周期 Future 和所有仍在等待的 TaskExecutor Future。因此热重载不会遗留下一轮倒计时或“幽灵 save-all”。

## 源码结构

```text
autosave/
├── __init__.py       # MCDR 生命周期入口
├── config.py         # 默认配置、递归回退、类型/边界校验
└── plugin.py         # 命令、状态机、异步周期与生命周期管理
mcdreforged.plugin.json
config.example.json
tests/
```
