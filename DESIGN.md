# UKUI 灵动岛设计说明

本文记录 0.6.0 的实现结构和取舍。安装、构建和验证范围见 [README](README.md)。

## 1. 参考与范围

界面机制参考两个项目：

- [BrimDeck](https://github.com/MoFeng2223/BrimDeck)（Apache-2.0，WPF）：收起态几何、紧凑槽位、语义化主题 token。
- [岛仔 Daozai](https://github.com/Renly1994/xiaotang-daozai)（MIT，Rust/egui）：皮肤调色板、材质、宠物和展开页的组织方式。

`island/geometry.py` 使用了 BrimDeck 的几何数值，`themes/*.json` 使用了岛仔的皮肤配色和命名。绘制代码、状态机和数据采集都是本项目自己实现的。

`references/` 是开发时的本地参考副本，不参与构建，也不进入安装包。发布源码时如果保留这个目录，需要同时保留两个项目各自的 LICENSE。

0.6.0 只支持屏幕顶部停靠。多屏、侧边停靠和 Wayland 不在当前实现范围内。

## 2. 技术栈

- Python 3.8 + PySide2 5.15.2.1 + Qt 5.15.2。
- PySide2 采用 LGPLv3，Qt 和 PySide2 以独立动态库随包分发，用户可以替换。
- D-Bus 使用 jeepney。PySide2 的 manylinux 包不包含 QtDBus，MPRIS 和通知监听不能依赖 `PySide2.QtDBus`。
- 单进程、单 UI 线程。系统读数、天气、音乐、邮件、日历、额度和通知都在 `QThread` 或子进程中运行，通过信号回到 UI 线程。
- 单实例由 `QLocalServer` 保证。第二次启动会通知已有窗口切换展开状态，然后退出。
- 窗口行为使用 X11 EWMH、`xprop` 和 XShape。毛玻璃通过 `_KDE_NET_WM_BLUR_BEHIND_REGION` 提示窗口管理器。

## 3. 形态与皮肤

形态决定收起状态的几何，皮肤决定调色板和材质。两者独立组合。

| 形态 | 说明 |
| --- | --- |
| `notch` 刘海 | 贴住屏幕上边缘，顶部两角为直角，底部圆角 12，肩线 16 |
| `capsule` 胶囊 | 悬浮在顶部下方 5px，圆角为高度的一半 |
| `line` 指示条 | 56×4 的细条，按状态填充，适合只看进度的场景 |

收起尺寸：

| 形态 | 默认尺寸 | 位置 |
| --- | --- | --- |
| 刘海 | 238×32 | `y=0` |
| 胶囊 | 196×32 | `y=5` |
| 指示条 | 56×4 | `y=4` |

缩放范围是 80% 至 140%。展开面板固定 420×140，屏幕宽度不足 436px 时取屏幕宽度减 16。

五种皮肤：

- `classic` 经典：纯黑底，浅色文字，蓝色强调。
- `cream` 奶油：暖白底，深棕文字，橙色强调。
- `glass-light` 毛玻璃·浅：浅色半透明材质。
- `glass-dark` 毛玻璃·深：深色半透明材质。
- `fluid` 悬浮云：半透明灰底，带一层偏左的径向光晕。

3 种形态 × 5 种皮肤共 15 种组合，矩阵图由 `tests/style-theme-matrix.py` 生成。

## 4. 主题系统

主题文件是带整行 `//` 注释的 JSON，放在 `themes/` 下。程序按文件名加载主题，文件名就是主题 id。

岛体和文字颜色来自语义 token，绘制函数不写死主题色：

| 组 | token | 用途 |
| --- | --- | --- |
| 底色 | `surface` | 岛体背景 |
| 文字 | `textPrimary` `textSecondary` `textTertiary` | 标题、正文、脚注 |
| 强调 | `accent` `onAccent` | 进度环、选中态、强调色上的文字 |
| 状态 | `danger` `warning` `success` | 告警、预警、充电和正常状态 |
| 专用 | `clock` `equalizer` `indicator` | 时钟、律动条、指示条 |
| 结构 | `hairline` `track` `ringTrack` `fill` `hover` `pressed` `outline` | 分隔线、轨道、填充和交互态 |
| 浮层 | `popup` `popupBorder` `input` `shadow` | 展开面板、设置窗口、输入框和阴影 |

材质有三种：

| `kind` | 表现 |
| --- | --- |
| `opaque` | 直接填充 `surface` |
| `glass` | 半透明 tint 加 1px 内高光；窗口管理器支持模糊原子时实时模糊，否则静态半透明 |
| `fluid` | 半透明底色，加一层偏左的径向光晕 |

一个只写差异的主题文件：

```json
{
  "formatVersion": 1,
  "id": "my-glass",
  "name": "示例毛玻璃",
  "base": "classic",
  "material": { "kind": "glass", "tint": "#FFFFFF", "alpha": 0.62, "rim": 0.55 },
  "colors": {
    "surface": "#F2FFFFFF",
    "accent": "#0A70E6"
  }
}
```

`base` 指向另一份主题，缺省 token 会从基主题继承。没有 `base` 的主题必须写全所有必需 token。加载时会检查 token、颜色格式和 `base` 循环。文字对比度低于 4.5:1、强调色低于 3:1 时，颜色会沿色相调整到刚好达标。

## 5. 布局与页面

收起态由有序槽位组成，从左到右依次是：

`CPU/内存环 · 宠物 · AI 状态 · 音乐 · 待办 · 专注 · 邮件 · 饮水 · 天气 · 时钟 · 电量`

时钟和电量组成右侧固定组，电量永远在最右。桌面机没有电池时整个电量格消失。邮件未读会显示 6 秒呼吸底色。指示条形态不绘制这些槽位，填充比例按专注计时、音乐进度、资源占用、静止短段的顺序取值。

展开面板的顶部是页标题、日期时钟和设置齿轮，左右箭头在内容区外侧，页码豆贴底。页面切换时从方向侧滑入并淡入，时长 0.24 秒。

九个页面：

`音乐 · 专注 · 健康 · 置物架 · 待办 · 邮箱 · AI 额度 · 日程 · 监控`

置物架页包含置物、剪贴和通知三个子页。置物架显示 5 张 60px 宽的横向卡片，保存上限 20 项，只记录路径。

AI 额度页顶部是来源胶囊和刷新按钮。左侧双同心环显示最短、次短周期的剩余比例，右侧显示周期、剩余百分比和重置时间，底部是今日 Token 与数据来源。没有官方周期时只显示本机今日 Token 数，不把预算折算成百分比。

## 6. 数据来源

| 数据 | 来源 |
| --- | --- |
| CPU、内存、网络、磁盘、温度 | `/proc`、`statvfs`、`/sys/class/hwmon`，GPU 可选 `nvidia-smi` |
| 电量 | `/sys/class/power_supply/BAT*` |
| 音量 | `pactl`，不可用时退回 `amixer` |
| 音乐和封面 | MPRIS over jeepney |
| 歌词 | 网易云歌词接口，按歌名和时长匹配 |
| 天气 | `wttr.in`，15 分钟缓存，断网回退旧数据 |
| 邮件 | IMAP，`imaplib` 加 `email` 标准库 |
| 日程 | 本地 `.ics`、HTTP(S) `.ics`、CalDAV |
| AI 额度 | Codex/Claude/WorkBuddy/Trae CN/Copilot 本地记录，可选的官方接口，自定义 JSON 地址 |
| 通知 | `dbus-monitor` 监听 `org.freedesktop.Notifications.Notify` |
| 全屏状态 | `xprop` 读取 `_NET_ACTIVE_WINDOW` 和 `_NET_WM_STATE` |

在线额度默认关闭。开启后只访问对应官方域名，超时 12 秒，不跟随重定向。令牌不写入日志，也不进入异常文本。

## 7. 模块

```
island/
├── app.py / window.py / geometry.py / motion.py / render.py / theme.py
├── sources.py / music.py / lyrics.py / weather.py / presence.py / blur.py / x11.py
├── productivity.py / mail.py / mail_reader.py / calendar.py / quota.py / activity.py
└── settings_window.py / tray.py / config.py / autostart.py / single_instance.py
```

`window.py` 负责窗口、交互和页面绘制，`render.py` 提供材质、文字和图标绘制函数，`sources.py` 及同类模块只负责取数。数据采集层不碰 QPainter，绘制层不发起网络请求。

## 8. 渲染与性能

- 窗口使用 `WA_TranslucentBackground`、`FramelessWindowHint`、`Tool` 和 `WindowStaysOnTopHint`，全部内容由 `paintEvent` 自绘。
- 展开和收起使用与帧率无关的弹簧。动画进行时启动 16ms 帧定时器，弹簧收敛后停止。
- 时钟、律动条、歌词和通知各自使用低频定时器刷新，静止状态不持续跑满帧。
- 系统读数每 2 秒采样一次，天气每 15 分钟刷新一次。UI 线程只做绘制和轻量状态更新。

## 9. 限制

- 毛玻璃效果取决于窗口管理器是否响应 `_KDE_NET_WM_BLUR_BEHIND_REGION`。不支持时只能退化为静态半透明。
- 当前实现绑定 X11。麒麟后续版本如果默认 Wayland，需要改用 layer-shell。
- Python 3.8 已经 EOL，新增依赖需要固定在 3.8 可安装的版本。
- 官方额度接口、IMAP 和 CalDAV 都可能随服务端变化。失败时会保留本地数据并显示原因。
- 多屏、侧边停靠、全局快捷键和自动更新尚未实现。

## 10. 开发命令

`.build-venv` 由 `packaging/build.sh` 创建。`style-theme-matrix.py` 依赖系统里的 PyQt5，用 `/usr/bin/python3` 运行。

```bash
./packaging/build.sh
.build-venv/bin/python tests/test_core.py
QT_QPA_PLATFORM=offscreen .build-venv/bin/python tests/smoke_offscreen.py
QT_QPA_PLATFORM=offscreen /usr/bin/python3 tests/style-theme-matrix.py
QT_QPA_PLATFORM=offscreen dist/ukui-island/ukui-island --self-test
```
