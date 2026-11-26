# UKUI 灵动岛设计说明

本文记录 0.7.2 的实现结构和取舍。安装、构建和验证范围见 [README](README.md)。

## 1. 参考与范围

界面机制参考两个项目：

- [BrimDeck](https://github.com/MoFeng2223/BrimDeck)（Apache-2.0，WPF）：收起态几何、紧凑槽位、语义化主题 token。
- [岛仔 Daozai](https://github.com/Renly1994/xiaotang-daozai)（MIT，Rust/egui）：皮肤调色板、材质、宠物和展开页的组织方式。

`island/geometry.py` 使用了 BrimDeck 的几何数值，`themes/*.json` 使用了岛仔的皮肤配色和命名。绘制代码、状态机和数据采集都是本项目自己实现的。

0.7.2 只支持屏幕顶部停靠。多屏、侧边停靠和 Wayland 不在当前实现范围内。

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

设置的外观页「材质」可以改玻璃皮肤的不透明度（`glass_alpha`，20–100，两种玻璃皮肤共用一个值）。`theme.with_alpha()` 只换 `material["alpha"]`，调色板不动；`IslandApp.active_theme` 每次按当前皮肤和这个取值算出真正交给 `IslandWindow` 的主题，`glass_alpha` 为空表示跟随皮肤自己在主题文件里写的 `alpha`。设置预览的底色按生效后的岛面颜色反推，保证岛框始终和预览背景分得开。

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

### 设置预览

预览画的是一枚隐藏的样例岛（`SettingsDialog._sample_window`），读数全部固定：资源环、天气、+1.07% 的行情和「正在执行」的 AI 状态，不读真实行情也不读本机会话。开关一拨就立刻重画，不用等后台线程回信号。样例岛不 `show()`，定时器全停，`_apply_blur` 置空，所以不碰 X11，也不打扰正在运行的真岛。

## 5. 布局与页面

### 收起态槽位

收起态由有序槽位组成，从左到右依次是：

`CPU/内存环 · 宠物 · AI 状态 · 音乐 · 待办 · 专注 · 邮件 · 饮水 · 会议 · 股票 · 天气 · 时钟 · 电量`

时钟和电量组成右侧固定组，电量永远在最右。电量把百分比数字画在电池框内部，电池填充只是数字下的一层柔和底色，充电时整格转绿、低于 15% 转红，百分比后面不另写 `%`。桌面机没有电池时整个电量格消失。邮件未读会显示 6 秒呼吸底色。

指示条形态不绘制这些槽位，填充比例按专注计时、音乐进度、资源占用、静止短段的顺序取值。

### 显示开关

收起状态显示什么集中在外观页的一组开关里：`show_monitor`、`show_pet`、`show_weather`、`show_stock`、`show_activity`、`show_battery`。它们只决定胶囊画不画这一格，展开页全部保留。

- `show_monitor` 关闭后 `Sampler` 停掉资源读数，窗口用 `monitor_focus` 在有读数的视图打开时临时开启，离开时保留最后一次读数。
- `show_activity` 关闭后 `Activity` 线程不启动，也不再读取本机会话记录。
- `show_battery` 关闭后右侧时钟旁的电量格不画、也不占宽度，和台式机读到 `None` 时表现一致；音乐页的「电量」读数格不受影响。

提醒类开关（`focus_remind`、`water_remind`、`mail_remind`）留在各自功能页，`meeting_detect` 在外观页的「启动与行为」。

### 展开面板

展开面板的顶部是页标题、日期时钟和设置齿轮，左右箭头在内容区外侧，页码豆贴底。页面切换时从方向侧滑入并淡入，时长 0.24 秒。

十一个页面：

`音乐 · 天气 · 专注 · 健康 · 置物架 · 待办 · 邮箱 · AI 额度 · 股票 · 日程 · 监控`

置物架页包含置物、剪贴和通知三个子页。置物架卡片只记录路径（上限 20 项），指向剪贴图片时画缩略图；下架只删我们自己暂存的那份 png，用户拖进来的文件不动。进入 tools 页时只改写默认子页：置物为空且有剪贴记录则落到剪贴，两边都空留在置物。

剪贴历史同时收文字和图片；文件管理器里复制图片只给 `text/uri-list`，`_record_clip_files` 按路径读字节。图片只在内存里留 PNG 字节（键是哈希前 16 位），点「上架」才写成 `$TMPDIR/ukui-dynamic-island-clips-<uid>/<key>.png`（0700/0600，名字避开单实例套接字），下架即删，可以再上架；文字点击复制，图片可放大预览。暂存放在 `/tmp`，重启由系统清理，`_load()` 只摘掉指向已消失暂存文件的卡片。上限：单张 12 MB、6 张图片、总条目 30 条。

音乐页在没有曲目时兼作资源读数：底部一格 `CPU · 内存 · 电量 · 网络`，不受 `show_monitor` 影响；有曲目时这一格让位给播放控件。因此 `_sync_monitor_sampling()` 把「音乐页空闲」也算作需要读数的视图。

AI 额度页顶部是来源胶囊和刷新按钮。左侧双同心环显示最短、次短周期的剩余比例，右侧显示周期、剩余百分比和重置时间，底部是今日 Token 与数据来源。没有官方周期时只显示本机今日 Token 数，不把预算折算成百分比。

### 股票

股票页默认 `sh000001` 上证指数，代码可在设置里改为 A 股、港股或美股。收起态只显示涨跌幅文字，占一个普通状态槽的宽度；展开页左侧是现价、涨跌额和最高/最低，右侧是按昨收画基线的当日分时线。

收起态的涨跌格按时段隐藏，判断在 `stock.chip_visible()`：`in_session()` 用 `SESSIONS` 的当地分钟区间（含午休，因为午休时涨跌仍是当天有效行情），美股先经 `local_now()` 换算到美东时间并按 `_us_summer()` 处理夏令时；`quote_fresh()` 再比对 `parse_quote()` 的 `date` 字段（行情日期不是今天就隐藏），这条同时覆盖节假日。区间右端多算 `stock_grace_minutes`（默认 15，0 表示收盘即隐藏），`stock_hide_closed` 关掉后 `chip_visible()` 恒为真。

`IslandWindow` 用和 AI 执行状态相同的做法缓存 `_stock_shown`，在 `_tick()`、`set_stock()` 和 `apply()` 里重算，变化时才 `_apply_geometry(animate=True)`，避免胶囊每秒抖动；`_paint_stock()` 只在隐藏时给标题行加一句说明，展开页数据不受影响。

### 天气

天气页左侧是地点、当前温度、天气现象、今日最高/最低、体感、湿度和风速；右侧七列对应今天到未来 7 天，每列显示星期、天气图标、最高/最低温和降水概率。收起态的天气槽可直接点开此页。

### 会议邀请识别

会议邀请识别在 `island/meeting.py`，纯解析、不写状态。`parse_meeting()` 先按「会议主题 + 会议时间」的标签邀请解析，命中不了再退一步认自由文本通知：`通知/定于/将于/大会/开会` 之一，加 `2026年11月12日` 式日期，再加带上午/下午的钟点，缺一样都不认。两条路径都要求完整年月日，只写「12 月 30 日」不认。

进解析前 `_plain()` 先还原富文本复制留下的痕迹：

- 全角冒号和数字归一半角，`下午16：00` 才不会漏。
- `&#x20;` 式数字实体解码。
- 行尾 Markdown 硬换行 `\` 和 `1\.` 式转义删掉；`\n`、`C:\Users` 这类后面跟字母数字的反斜杠不动，标题因此不会带一个多余的 `\`。

通知里「地点」独占一行时，`_place_block()` 把紧随其后的最多 3 行拼成一行，用 `；` 分隔，遇空行、`三、` 式新小节或会议号/链接行即停。

询问的生命周期：

- `IslandApp._clip_changed()` 先把剪贴板内容记进历史（有文字记文字，只有图片就记图片），再调 `IslandWindow.offer_meeting()`。询问还挂在 `_meeting_offer` 上时同一条不重复问，忽略或超时后再复制会重新问。
- 待办页打开时询问直接画在卡片上，其余时候走 `_enqueue_alert("meeting", …)` 横幅。横幅 8 秒后消失，`MEETING_OFFER_SECONDS`（60 秒）内收起态保留「会议待办」一格，超时由 `_tick()` 清理。
- 只有 `meeting_accept` 会调用 `productivity.add_todo()`。

### 待办与会议详情

待办新增 `remind_on`（`YYYY-MM-DD`，可空），把「哪天」和「几点」分开存，`meeting.py` 在有 `remind` 时才写它。`Productivity.todo_due()` 见到 `remind_on` 就直接按日期比较，跳过 `repeat` 判定，所以 `progress()`、`display_order()` 和 `_todo_reminder_tick()` 三个调用点一次改到位：非当天的会议不算今日、不排前面、只在会议当天提醒一次，过了当天彻底安静。`remind_on` 为空的老数据行为完全不变。代价是 dated 待办过了当天就 `due=False`，会显示成灰色，所以待办行的勾选热区放宽成 `due or item.get("remind_on")`，过期会议仍可勾掉。

会议号、地点/房间号和入会链接存进待办的 `meeting` 字段：`parse_meeting()` 用 `CODE_RE`/`PLACE_RE`/`LINK_RE` 从原文抽取，`productivity.clean_meeting()` 只保留 `code`(32)/`place`(60)/`link`(300) 三项并按长度截断，多余键丢弃，非字典输入返回 `{}`。

收起态行放不下完整会议号（184px 卡片里主题会被省略到 44px），所以详情单独一页：

- `_todo_details(item)` 把时间、会议号、地点、链接整理成行，`_paint_todo_detail()` 用整个 `_content_rect()`（338px）绘制，每行右侧复用现成的 `copy` 动作，顶部「完成」直接走 `todo_toggle`。
- 入口有两个：待办行文字（`todo_detail`，右侧画 chevron 提示可点），以及到点横幅（`_enqueue_alert(..., key=item)` 存的是待办对象本身，`_open_notice()` 比对 `item is notice["key"]` 后定位索引）。
- 有 `meeting` 的行勾选热区缩到左边 20px 圆圈，其余行保持整行可勾。
- `_todo_detail` 存索引，所以 `todo_remove`/`todo_clear` 和切页都会清空它，`_paint_todo()` 每次绘制前重验索引有效且仍有详情，否则回落到列表。

## 6. 数据来源

| 数据 | 来源 |
| --- | --- |
| CPU、内存、网络、磁盘、温度 | `/proc`、`statvfs`、`/sys/class/hwmon`，GPU 可选 `nvidia-smi` |
| 电量 | `/sys/class/power_supply/BAT*` |
| 音量 | `pactl`，不可用时退回 `amixer` |
| 音乐和封面 | MPRIS over jeepney |
| 歌词 | 网易云歌词接口，按歌名和时长匹配 |
| 天气 | Open-Meteo 实况与 7 天预报、Geocoding 城市搜索；自动定位用 `ipinfo.io` 出口 IP 归属，失败回退 `wttr.in`；15 分钟缓存，断网回退旧数据 |
| 股票 | `qt.gtimg.cn` 实时行情、`web.ifzq.gtimg.cn` 当日分时，60 秒刷新 |
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
- 窗口管理器把岛最小化时（显示桌面、快捷键或别的程序），每 1 秒读一次 `WM_STATE`，仍是 Iconic 就发 `_NET_ACTIVE_WINDOW` 请求救回并把焦点还给原窗口。Qt 的 `isMinimized()` 在 `showNormal()` 之后会翻回 False，不能用来判断；`showNormal()`、`XMapWindow` 和去掉 `_NET_WM_STATE_HIDDEN` 都救不回 KWin 的 Iconic 状态。

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
QT_QPA_PLATFORM=offscreen dist/ukui-dynamic-island/ukui-dynamic-island --self-test
```
