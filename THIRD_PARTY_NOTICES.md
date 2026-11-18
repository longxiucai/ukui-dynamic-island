# 第三方声明

本产品随包分发以下第三方组件。各组件保留其原始许可证；本文件不改变这些许可证。

| 组件 | 版本 | 许可证 | 用途 |
| --- | --- | --- | --- |
| PySide2 | 5.15.2.1 | LGPLv3（Riverbank 另有商业许可） | Qt 的 Python 绑定 |
| Qt | 5.15.2 | LGPLv3 / GPLv3 | 窗口、绘制、网络、DBus 客户端库 |
| shiboken2 | 5.15.2.1 | LGPLv3 | PySide2 绑定层 |
| jeepney | 0.8+ | MIT | 会话 D-Bus 客户端（MPRIS / 通知） |
| Python | 3.8 | PSF License | 运行时 |

## LGPL 合规说明

- Qt 与 PySide2 以**动态库**形式放在 `/opt/ukui-island/_internal/` 下，没有静态链接，也没有修改源码。
- 用户可以用自己编译的同名 `.so` 覆盖 `/opt/ukui-island/_internal/` 下的文件（便携包为 `ukui-island/_internal/`）；程序不校验签名，替换后仍可启动。
- 对应源码：<https://code.qt.io/cgit/pyside/pyside-setup.git/> 与 <https://download.qt.io/official_releases/qt/5.15/>
- 本程序自身代码不因链接 LGPL 库而必须开源；若修改了 Qt/PySide2 本体，修改部分需按 LGPLv3 提供。

## 设计与素材归属

- 三形态几何常量（刘海 238×32 / 胶囊 196×32 / 指示条 56×4、inset、圆角与肩线）参考 **BrimDeck**（Apache-2.0，<https://github.com/MoFeng2223/BrimDeck>）的 `CollapsedGeometry`，按其许可证要求在此署名。
- 五套皮肤的参数与命名参考 **岛仔 Daozai**（MIT，<https://github.com/Renly1994/xiaotang-daozai>），「悬浮云」皮肤原作者为 啵（@hanhb123）。上游 MIT 版权声明为 Copyright (c) 2026 小唐的Token and Daozai contributors。
- 图标为本次项目自绘。
- `references/` 是开发时的本地参考副本，不进入安装包。如果源码仓库保留该目录，需要同时保留两个项目各自的 LICENSE。

## 打包工具

PyInstaller 的 bootloader 采用 GPLv2 + 例外条款；打包产物（onedir）不受 GPL 传染。详见
<https://github.com/pyinstaller/pyinstaller/blob/develop/COPYING.txt>。
