# AutoSaveRestart

AutoSaveRestart 是一个适用于 **MCDReforged** 的 Minecraft 服务器自动保存插件，默认针对 **GTNH / 1.7.10（Thermos）** 做了适配。

> 注意：插件名为 AutoSaveRestart，但**仅负责保存，不包含重启功能**。
> 定时重启需另行配置重启插件（例如定时执行 `stop`，由启动脚本中的 `:loop` 重新拉起进程）。

插件会按照设定的时间间隔自动保存服务器地图，并在保存前向全服发送醒目的彩色预警和倒计时提示。管理员也可以随时查看状态、手动触发保存、取消本次保存，或者修改自动保存间隔。

## 功能

- 定时自动保存服务器地图
- 保存前向全服发送预警
- 最后几秒逐秒倒计时
- 不同状态使用不同颜色提示
- 最后 5 秒使用红色加粗提醒
- 保存开始和完成时发送提示
- 管理员可手动触发一次完整保存流程
- 管理员可在倒计时期间取消本次保存
- 管理员可直接修改自动保存间隔
- 支持自定义保存命令和提示文字
- 配置文件首次使用时自动生成

## 使用要求

- MCDReforged 2.14.0 或更高版本
- Minecraft Java 版服务端

## 安装

1. 下载最新版 `AutoSaveRestart-v版本号.mcdr`。
2. 将文件放入 MCDReforged 的 `plugins` 文件夹。
3. 重启 MCDReforged，或者重新加载插件。
4. 插件首次加载后会自动生成配置文件：

```text
config/autosave/config.json
```

安装完成后，插件会按照默认设置自动运行。

## 默认保存流程

默认情况下：

1. 每 30 分钟自动保存一次。
2. 距离保存 60 秒时向全服发送金色预警。
3. 最后 10 秒开始逐秒倒计时。
4. 最后 5 秒变为红色加粗提示。
5. 保存开始时显示浅蓝色提示。
6. 保存完成后显示绿色提示。

保存间隔、预警时间、倒计时时间和提示文字都可以修改。

## 管理命令

默认情况下，以下命令仅管理员或控制台可以使用。

### 查看状态

```text
!!autosave
```

或者：

```text
!!as
```

可以查看插件当前状态、下一次自动保存剩余时间以及当前是否正在倒计时。

### 手动执行一次保存

```text
!!autosave run
```

立即开始一次完整流程：

```text
预警 → 等待 → 倒计时 → 保存
```

如果已经有保存流程正在进行，则不会重复开启第二次。

### 取消本次保存

```text
!!autosave cancel
```

在逐秒倒计时期间，可以取消当前这一次保存。

取消成功后，全服会收到红色取消提示，本次保存不会继续执行，下一轮自动保存仍会正常进行。

### 修改自动保存间隔

```text
!!autosave set <分钟>
```

例如：

```text
!!autosave set 60
```

表示将自动保存间隔修改为 60 分钟。

修改成功后会自动保存到配置文件。

## 配置文件

配置文件位置：

```text
config/autosave/config.json
```

常用配置：

| 配置项 | 作用 | 默认值 |
| --- | --- | --- |
| `interval_minutes` | 自动保存间隔，单位为分钟 | `30` |
| `warning_seconds` | 提前多少秒发送保存预警 | `60` |
| `countdown_seconds` | 最后多少秒开始逐秒倒计时 | `10` |
| `save_command` | 保存服务器地图时执行的命令 | `save-all` |
| `broadcast_mode` | 全服提示的发送方式：`say` 或 `tellraw` | `say` |
| `command_root` | 主命令名称 | `!!autosave` |
| `command_aliases` | 命令别名 | `!!as` |
| `permission_level` | 管理命令所需权限等级 | `3` |
| `messages` | 插件显示的各种提示文字 | 可自定义 |

如果只是修改自动保存间隔，推荐直接使用：

```text
!!autosave set <分钟>
```

如果需要修改预警时间、倒计时、保存命令或提示文字，则编辑 `config.json` 后重新加载插件。

仓库中的 `config.example.json` 提供了完整配置示例。

## 默认颜色

| 场景 | 显示效果 |
| --- | --- |
| 保存前预警 | 金色 |
| 普通倒计时 | 黄色 |
| 最后 5 秒 | 红色加粗 |
| 正在保存 | 浅蓝色加粗 |
| 保存完成 | 绿色加粗 |
| 保存取消 | 红色加粗 |
| 状态查询 | 根据状态使用浅蓝、黄色、金色、红色和灰色 |

颜色会由插件自动处理。修改 `config.json` 中的提示文字时，不需要添加 Minecraft 颜色代码。

## 保存命令

默认保存命令为：

```text
save-all
```

1.7.10（GTNH / Thermos）的 `/save-all` **没有 `flush` 参数**，该参数自 1.13 起提供。
若旧配置中仍为 `save-all flush`，插件加载时会自动降级为 `save-all` 并写回配置文件。

如果你的服务端需要使用其他保存命令，可以修改配置文件中的 `save_command`。

## GTNH / 1.7.10 适配

- **提示走原生 `say` 指令**：`broadcast_mode` 默认为 `say`，插件将颜色转换为 `§` 码后执行
  `say §6文本§r`，不依赖 `tellraw` 的 JSON，也不受 GTNH 聊天格式化模组影响。
  如需 RText 富文本，将 `broadcast_mode` 改为 `tellraw`。
- **仅使用 16 色**：1.7.10 不支持 RGB / hex，颜色固定映射到 `§0`–`§f`，加粗使用 `§l`。
- **单行发送**：提示文本中的换行会被压缩为空格，避免一条 `say` 被控制台拆分为两条命令。
- **编码**：MCDR 的 `config.yml` 中 `encoding` / `decoding` 保持 `utf8`，服务端启动参数需包含
  `-Dfile.encoding=UTF-8`（GTNH 整合包启动脚本通常已包含），否则中文提示会乱码。
- **服务端未运行时跳过**：GTNH 启动耗时较长，服务器未运行时插件会跳过本轮并重新计时，
  不会向尚未启动的控制台发送指令。
- **`save-all` 存在短暂卡顿**：GTNH 世界体积较大，保存瞬间可能出现 TPS 波动，预警文案已提示玩家；
  保存间隔不建议低于 15 分钟。
- **`say` 输出带 `[Server]` 前缀**：这是 1.7.10 原版行为，如需去掉可改用 `tellraw` 模式。

### 验证环境

- MCDReforged 2.16.2，Python 3.12.5
- Thermos 1.7.10（GTNH 整合包）
- 已核对 `schedule_task`、`load_config_simple`、`save_config_simple`、`register_help_message`、
  `register_command`、`CommandSource.has_permission`、`PlayerCommandSource.player` 等接口签名
- 单元测试 19 项全部通过

## 权限

默认管理命令权限等级为 `3`，即 MCDReforged 管理员权限。

服务器控制台可以直接使用全部管理命令。

## 更新插件

下载新版 `.mcdr` 文件后，替换 `plugins` 文件夹中的旧版本，然后重新加载插件即可。

建议保留自己的配置文件：

```text
config/autosave/config.json
```
