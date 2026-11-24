# UKUI 灵动岛

这是给银河麒麟 V10 SP1 和 UKUI 桌面做的顶边灵动岛。收起时贴在屏幕顶部，显示时间、系统状态和待处理事项。鼠标移上去展开成 420×140 的面板，移开自动收起。

项目用 Python 3.8 和 PySide2 5.15 写，安装包自带 Qt 和 Python 运行时，装好后不用再配 Python 环境。当前版本 0.7.1，只支持 X11 会话。

![展开页总览](screenshots/pages.png)

## 功能

### 收起态

- 显示时钟、日期、电量、天气、CPU/内存环、可配置的股票涨跌幅和状态块。股票可以关掉常驻，只保留展开页；没有电池的设备自动隐藏电量。
- 待办、专注、邮件、饮水提醒会在对应状态出现。
- 外观可以选刘海、胶囊或指示条，皮肤有经典、奶油、毛玻璃·浅、毛玻璃·深和悬浮云五种，形态和皮肤可以自由组合。
- 股票涨跌只在交易时段显示：沪深 09:30–15:00、港股 09:30–16:00、美股 09:30–16:00（按美东时间）。周末、休市和节假日（按行情日期判断）自动隐藏，收盘后默认再多留 15 分钟。宽限时长和这个开关在设置的外观页「股票」里，关掉开关就恢复成一直显示。展开的股票页不受影响，休市时标题行会标出「休市，收起态已隐藏」。

### 展开页

- 十一个页面：音乐、天气、专注、健康、置物架、待办、邮箱、AI 额度、股票、日程、监控。左右箭头、底部页码豆和滚轮都能切页。
- 天气页左侧显示实况和体感/湿度/风速，右侧并排显示未来 7 天的天气图标、最高/最低温和降水概率；收起态的天气可以点开这一页。设置里支持城市搜索、最多 5 个常用城市和按网络出口自动定位。
- 音乐页通过 MPRIS 读取播放器，显示封面、进度、音量和同步歌词，支持播放控制与拖动进度。没有播放曲目时底部改成一行 CPU、内存、电量和网络读数。
- 股票页画出当日分时、昨收基线和最高/最低价，默认代码是上证指数 `sh000001`，可以在设置里改成其他 A 股、港股或美股代码。
- 置物架支持从文件管理器拖入文件，只记录路径，不复制文件。置物架空着而有剪贴记录时，进页面默认先看剪贴；两边都空则留在置物架看拖拽提示。
- 系统监控显示 CPU、内存、磁盘、温度、网络速率和 NVIDIA GPU 占用，数据来自 `/proc`、`statvfs` 和 `hwmon`。收起态不显示这几格时，只在打开监控页或音乐页没有播放曲目时采集。

### 待办与提醒

- 待办支持每天、工作日、指定星期重复和 HH:MM 提醒。「+ 添加」和「改一下」在左侧上下排列，列表占满其余宽度，长标题少被省略。
- 另有番茄专注、饮水记录、剪贴板历史（最多 30 条）和文件置物架。
- 复制腾讯/飞书/企业微信的会议邀请（要同时有「会议主题」和带日期的「会议时间」）时，岛上会先问一次，点「创建待办」才写入，点「忽略」或 1 分钟不理会消失。询问还没确认时，底部待办页的页码豆上会亮一个提醒点（和喝水待确认一样），确认或超时后熄灭。
- 会议待办带上会议日期：只有会议当天才提醒一次，过了当天不再响，也不计入「今日 N 项」，非当天的会议不会冒充今天的任务。
- 会议号、会议地点/房间号和入会链接会一起存进待办。待办行右侧有箭头表示可展开，点文字进详情页，四行「时间 / 会议号 / 地点 / 链接」各带一个复制按钮，详情页顶部可直接「完成」；点圆圈仍然只勾完成。到点提醒横幅也直接打开这个详情页，不用回列表找。
- 会议识别只读邀请文本里已有的信息，没写就不显示。普通复制照常进剪贴板历史，外观页的「启动与行为」可以关掉这个识别。

### 数据源与账号

- 邮箱使用 IMAP 轮询，识别验证码，可复制、标已读/未读和删除。写操作默认关闭，开启后才会同步到服务器；服务器没接受时会明确报错，不会假装成功。
- 日程支持本地 `.ics`、HTTP(S) `.ics` 和 CalDAV。
- AI 额度页显示 Codex、Claude、WorkBuddy、Trae CN 和 Copilot 的本地用量，也可以配置自定义 JSON 地址。在线官方额度默认关闭，开启后只把本机登录令牌发给对应官方域名。
- 收起态和额度页会显示 Codex、Claude 的实时回合状态，包括思考、执行、回答和完成。外观页的「AI 执行状态」关掉后不再读取本机会话记录，收起格和额度页的提示一起消失。

### 系统

- 托盘菜单可切换皮肤和形态，也能开关开机自启、全屏隐藏和鼠标穿透。

## 形态与皮肤

![形态与皮肤矩阵](screenshots/style-theme-matrix.png)

图里是 15 种形态和皮肤组合。

提醒状态见 [提醒状态矩阵](screenshots/reminder-matrix.png)。

## 系统要求

- 银河麒麟 V10 SP1，UKUI 桌面，X11 会话，x86_64 或 arm64。
- Releases 提供 amd64 和 arm64 两种 deb 与便携包；arm64 由 CI 构建并通过自检，尚未在 ARM 真机验证。
- x86_64 已在 1920×1080 单屏上验证。其他分辨率和多屏环境未测试。
- 音量控制需要 `pactl` 或 `amixer`。电池从 `/sys/class/power_supply` 读取。
- 通知监听需要 `dbus-monitor`，全屏检测和毛玻璃探测需要 `xprop`。
- NVIDIA GPU 监控需要 `nvidia-smi`，其他显卡不显示 GPU 数据。
- 设置里输入中文需要系统装好 fcitx 的 Qt5 插件（`fcitx-frontend-qt5`）。包自带的 Qt 只有 ibus 和 compose 插件，启动时程序会把系统的 fcitx 插件挂进自己的搜索路径；找不到时日志记录 `input method: ...`，输入框只能输英文。

## 安装

### deb 包

```bash
sudo dpkg -i ukui-dynamic-island_0.7.1_amd64.deb   # x86_64
sudo dpkg -i ukui-dynamic-island_0.7.1_arm64.deb   # arm64
sudo apt -f install
```

安装后从应用菜单打开「UKUI 灵动岛」，或在终端运行：

```bash
ukui-dynamic-island
```

卸载命令：

```bash
sudo apt remove ukui-dynamic-island
```

### 便携包

```bash
mkdir -p ~/apps/ukui-dynamic-island
tar -xzf ukui-dynamic-island-0.7.1-x86_64.tar.gz -C ~/apps/ukui-dynamic-island   # x86_64
tar -xzf ukui-dynamic-island-0.7.1-aarch64.tar.gz -C ~/apps/ukui-dynamic-island  # arm64
~/apps/ukui-dynamic-island/run.sh
```

便携包里的 `install.sh` 会安装到 `~/.local/share/ukui-dynamic-island`，并在 `~/.local/bin` 和用户应用菜单里创建入口。

### 从源码运行

```bash
python3 -m venv .venv
.venv/bin/pip install "PySide2==5.15.2.1" "jeepney>=0.8"
.venv/bin/python run.py
```

Python 3.8 是打包和验证使用的版本。系统缺少 Qt 运行库时，先安装 `libxcb-cursor0`、`libxcb-xinerama0`、`libxkbcommon-x11-0`、`libgl1`、`libegl1`、`libdbus-1-3`、`libglib2.0-0`、`libgssapi-krb5-2` 和 `fonts-noto-cjk`。

## 构建

```bash
./packaging/build.sh
ls -lh out/
```

脚本会创建 `.build-venv`，安装 PySide2 5.15.2.1、PyInstaller 6.11.1 和 jeepney，然后生成：

- `out/ukui-dynamic-island_0.7.1_amd64.deb`
- `out/ukui-dynamic-island-0.7.1-x86_64.tar.gz`
- `out/SHA256SUMS.txt`

打包目录在 `dist/ukui-dynamic-island/`，可以直接运行自检：

```bash
QT_QPA_PLATFORM=offscreen dist/ukui-dynamic-island/ukui-dynamic-island --self-test
```

发布前检查：

1. `dpkg-deb -I out/ukui-dynamic-island_0.7.1_amd64.deb` 的 `Depends` 与 `ldd dist/ukui-dynamic-island/ukui-dynamic-island` 的结果对得上。
2. 从解包后的 `/opt/ukui-dynamic-island` 目录运行 `--self-test`，不要只跑 `dist/`。
3. 在没有 `~/.config/ukui-dynamic-island` 的账户下启动一次。
4. 把 deb、tar.gz 和 `SHA256SUMS.txt` 一起上传到 Releases。

### ARM

arm64 包在 `ubuntu-22.04-arm` runner 上用 Debian bullseye 的 PySide2 5.15.2 构建。本地构建需要 arm64 机器：

```bash
./packaging/build-arm64.sh
```

产物在 `out-arm64/`：

- `out-arm64/ukui-dynamic-island_0.7.1_arm64.deb`
- `out-arm64/ukui-dynamic-island-0.7.1-aarch64.tar.gz`
- `out-arm64/SHA256SUMS.txt`

发布流水线在 `.github/workflows/release.yml`。推 `v*` tag 后会同时构建 amd64 和 arm64，并创建 Release。arm64 job 使用 `ubuntu-22.04-arm` runner，已在 Debian bullseye arm64 环境通过自检和离屏冒烟测试，但还没有在麒麟 ARM 真机上验证。

## 使用

- 鼠标移到岛上展开，移开收起。展开后可用左右箭头、底部页码豆或滚轮切页。
- 点击托盘图标切换展开状态；右键打开皮肤、形态、开机自启、鼠标穿透和退出菜单。
- 设置窗口可改皮肤、形态、时间格式、天气城市、股票代码、邮件、日历和额度。收起态显示哪几格集中在外观页的「收起状态显示」，只管胶囊；例外是资源监控（关闭后只在需要读数的视图采集，监控页仍在）和 AI 执行状态（关闭会停止读取本机会话记录）。
- `ukui-dynamic-island --version` 输出版本，`ukui-dynamic-island --self-test` 输出 JSON 自检结果。

## 数据与卸载

| 内容 | 位置 |
| --- | --- |
| 配置 | `~/.config/ukui-dynamic-island/config.json`（0600） |
| 待办、饮水、剪贴板、置物架 | `~/.local/state/ukui-dynamic-island/productivity.json`（0600） |
| 日志 | `~/.local/state/ukui-dynamic-island/island.log`，超过 1 MB 轮转为 `island.log.1` |
| 开机自启 | `~/.config/autostart/ukui-dynamic-island.desktop`（仅勾选时创建；条目失效时下次启动改指向当前运行的构建） |
| 已连接账号的令牌 | `~/.config/ukui-dynamic-island/*.json`（0600） |

升级时直接安装新版本的 deb，程序目录会被覆盖，用户配置保留。回滚时安装上一个版本的 deb。配置解析失败会自动回退默认值，不会阻止启动，并在日志里记录解析错误。

彻底清理用户数据：

```bash
rm -rf ~/.config/ukui-dynamic-island ~/.local/state/ukui-dynamic-island
```

便携包安装到用户目录时，再删除 `~/.local/share/ukui-dynamic-island`、`~/.local/bin/ukui-dynamic-island` 和 `~/.local/share/applications/ukui-dynamic-island.desktop`。

## 网络与隐私

程序不上报遥测。会联网的地方有：

- 天气：Open-Meteo 实况与 7 天预报，城市搜索用 Open-Meteo Geocoding；自动定位用 `ipinfo.io` 的出口 IP 归属，失败时回退 `wttr.in`；15 分钟缓存，断网时显示旧数据。
- 股票：腾讯行情 `qt.gtimg.cn` 和分时 `web.ifzq.gtimg.cn`，只查询设置里的代码，每分钟刷新一次。
- 歌词：`music.163.com`，播放时按歌名和时长查询。
- 邮件、日历和自定义额度：只在设置里填了地址或账号后访问。
- 在线官方额度：默认关闭，开启后只访问对应的官方域名，12 秒超时，不跟随重定向。

配置、待办和登录令牌都留在本机。日志不记录邮件正文、账号密码或剪贴板内容。会议邀请识别只在本机解析剪贴板文本，不联网、不上传。

## 验证范围

在 Kylin V10 SP1 / UKUI / X11 / 1920×1080 上验证过安装包解包运行、便携包启动、顶边显示和悬停展开。九个页面的切换、置物架拖放、QQ 和企业邮箱 IMAP 登录、Codex/Copilot 本机额度读取、通知监听也都实际试过。

以下项目还没验证：

- 纯净系统。依赖列表来自开发机。
- 开机自启。只复现了 UKUI 的执行环境（从 `$HOME` 运行同一条 `Exec`），没有重启登录验证。
- arm64 真机。arm64 包只在 CI 中完成构建、自检和离屏测试。
- Wayland 会话、多屏和侧边停靠。
- CalDAV 和部分在线额度。没有用真实账号完成联调，失败时会回退本地数据。
- 连续运行 24 小时、内存曲线、代码签名和自动更新。
- 毛玻璃。取决于窗口管理器是否支持 `_KDE_NET_WM_BLUR_BEHIND_REGION`，不支持时使用静态半透明，没有实时模糊。

## 开发与测试

`.build-venv` 由 `packaging/build.sh` 创建。只想跑测试的话，也可以手动建：

```bash
/usr/bin/python3 -m venv .build-venv
.build-venv/bin/pip install "PySide2==5.15.2.1" "jeepney>=0.8"
```

然后运行：

```bash
.build-venv/bin/python tests/test_core.py
QT_QPA_PLATFORM=offscreen .build-venv/bin/python tests/smoke_offscreen.py
QT_QPA_PLATFORM=offscreen .build-venv/bin/python tests/pages-matrix.py
QT_QPA_PLATFORM=offscreen .build-venv/bin/python tests/reminder-matrix.py
QT_QPA_PLATFORM=offscreen /usr/bin/python3 tests/style-theme-matrix.py
```

`style-theme-matrix.py` 用的是系统 Python 里的 PyQt5，所以单独用 `/usr/bin/python3` 跑。UI 冒烟测试使用 offscreen 平台，不需要启动桌面。截图脚本会覆盖 `screenshots/` 下的同名文件。

## 文档

- [DESIGN.md](DESIGN.md)：形态几何、主题格式、页面布局和平台实现。
- [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)：第三方组件、LGPL 合规和素材署名。

## 参考项目

形态几何、主题参数和交互方式参考了 [BrimDeck](https://github.com/MoFeng2223/BrimDeck)（Apache-2.0）和 [岛仔 Daozai](https://github.com/Renly1994/xiaotang-daozai)（MIT）。详细署名见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 许可证

MIT，见 [LICENSE](LICENSE)。随包分发的第三方组件遵循各自的许可证，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
