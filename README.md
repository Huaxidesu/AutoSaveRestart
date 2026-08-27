# AutoSaveRestart

AutoSaveRestart 是一个适用于 **MCDReforged** 的 Minecraft GTNH 插件端服务器自动保存插件。

插件可以按照设定的时间间隔自动保存服务器地图，并在保存前向全服发送预警和倒计时提示。

管理员也可以随时查看保存状态、手动触发保存、取消本次保存，或者直接修改自动保存间隔。

## 功能

* 定时自动保存服务器地图
* 保存前向全服发送预警
* 最后几秒逐秒倒计时
* 保存开始和完成时发送提示
* 支持管理员手动触发保存
* 支持倒计时期间取消本次保存
* 支持直接修改自动保存间隔
* 支持自定义保存命令
* 支持自定义提示文本
* 支持自定义命令名称和别名
* 配置文件首次使用时自动生成

## 使用要求

* MCDReforged 2.14.0 或更高版本
* Minecraft Java 版服务端

## 安装

1. 下载最新版 `AutoSaveRestart-v版本号.mcdr`
2. 将文件放入 MCDReforged 的 `plugins` 文件夹
3. 重启 MCDReforged，或者重新加载插件
4. 插件首次启动后会自动生成配置文件：

```text
config/autosave/config.json
```

安装完成后，插件会按照默认设置自动运行。

## 默认保存流程

默认情况下：

1. 每 30 分钟自动保存一次
2. 距离保存 60 秒时向全服发送预警
3. 最后 10 秒开始逐秒倒计时
4. 倒计时结束后提示正在保存
5. 执行服务器地图保存
6. 保存完成后发送提示

保存间隔、预警时间、倒计时时间和提示文字都可以修改。

## 管理命令

默认情况下，以下命令仅管理员或控制台可以使用。

### 查看插件状态

```text
!!autosave
```

或者：

```text
!!as
```

可以查看：

* 插件当前运行状态
* 距离下一次自动保存还有多久
* 当前是否正在进行保存流程
* 当前是否处于倒计时阶段

### 手动执行一次保存

```text
!!autosave run
```

立即开始一次完整的保存流程：

```text
预警 → 等待 → 倒计时 → 保存
```

如果当前已经有保存流程正在进行，则不会重复开启第二次。

### 取消本次保存

```text
!!autosave cancel
```

在逐秒倒计时期间，可以取消当前这一次保存。

取消后：

* 本次倒计时停止
* 本次保存不会执行
* 全服会收到取消提示
* 下一轮自动保存仍然会正常进行

### 修改自动保存间隔

```text
!!autosave set <分钟>
```

例如：

```text
!!autosave set 60
```

表示将自动保存间隔修改为：

```text
60 分钟
```

修改成功后会自动保存到配置文件。

## 常用示例

每 30 分钟保存一次：

```text
!!autosave set 30
```

每 1 小时保存一次：

```text
!!autosave set 60
```

立即执行一次保存：

```text
!!autosave run
```

查看下一次保存时间：

```text
!!autosave
```

取消当前倒计时：

```text
!!autosave cancel
```

## 配置文件

配置文件位置：

```text
config/autosave/config.json
```

常用配置：

| 配置项 | 作用 | 默认值 |
| ------------------- | ------------- | ---------------- |
| `interval_minutes` | 自动保存间隔，单位为分钟 | `30` |
| `warning_seconds` | 提前多少秒发送预警 | `60` |
| `countdown_seconds` | 最后多少秒开始逐秒倒计时 | `10` |
| `save_command` | 保存地图时执行的服务器命令 | `save-all flush` |
| `command_root` | 插件主命令 | `!!autosave` |
| `command_aliases` | 插件命令别名 | `!!as` |
| `permission_level` | 管理命令所需权限等级 | `3` |
| `messages` | 插件显示的各种提示文字 | 可自定义 |

如果只是修改自动保存间隔，推荐直接使用：

```text
!!autosave set <分钟>
```

如果需要修改预警时间、倒计时、保存命令或提示文字，则编辑：

```text
config/autosave/config.json
```

然后重新加载插件。

仓库中也提供了一份完整配置示例：

```text
config.example.json
```

## 保存命令

默认保存命令：

```text
save-all flush
```

如果你的服务器不适合使用该命令，可以在配置文件中修改：

```text
save_command
```

例如：

```text
save-all
```

具体使用哪个保存命令，请根据自己的 Minecraft 服务端进行选择。

## 权限

默认管理命令权限等级：

```text
3
```

也就是 MCDReforged 管理员权限。

服务器控制台可以直接使用插件的所有管理命令。

如果需要修改权限要求，可以修改配置文件中的：

```text
permission_level
```

## 更新插件

下载新版 `.mcdr` 文件后，替换 `plugins` 文件夹中的旧版本，然后重新加载插件即可。

建议更新前保留自己的配置文件：

```text
config/autosave/config.json
```

这样可以继续使用原来的保存间隔和自定义提示。

## AutoSaveRestart

一个简单、方便的 MCDReforged Minecraft 服务器自动保存插件。
