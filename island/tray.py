"""Tray menu: skin, style, autostart, settings, quit."""
from PySide2.QtCore import QObject
from PySide2.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide2.QtWidgets import QAction, QActionGroup, QMenu, QSystemTrayIcon

from island import APP_NAME


def app_icon() -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QColor(0, 0, 0, 0))
    p.setBrush(QColor("#0A0A0C"))
    p.drawRoundedRect(4, 18, 56, 28, 14, 14)
    p.setBrush(QColor("#3EACF8"))
    p.drawEllipse(15, 26, 12, 12)
    p.setBrush(QColor("#F5F5F7"))
    p.drawRoundedRect(33, 27, 18, 3, 1.5, 1.5)
    p.drawRoundedRect(33, 34, 11, 3, 1.5, 1.5)
    p.end()
    return QIcon(pm)


class Tray(QObject):
    def __init__(self, app, themes, on_settings):
        super().__init__(None)
        self.app = app
        self.tray = QSystemTrayIcon(app_icon(), self)
        self.tray.setToolTip(APP_NAME)
        self.menu = QMenu()
        self.theme_menu = self.menu.addMenu("皮肤")
        self.style_menu = self.menu.addMenu("形态")
        self.theme_group = QActionGroup(self.menu)
        self.style_group = QActionGroup(self.menu)
        self.theme_actions = {}
        self.style_actions = {}
        for theme_id, theme in themes.items():
            act = QAction(theme.name or theme_id, self.theme_menu,
                          checkable=True)
            act.triggered.connect(lambda _=False, tid=theme_id: self.app.set_theme(tid))
            self.theme_group.addAction(act)
            self.theme_menu.addAction(act)
            self.theme_actions[theme_id] = act
        for style, label in (("notch", "刘海"), ("capsule", "胶囊"), ("line", "指示条")):
            act = QAction(label, self.style_menu, checkable=True)
            act.triggered.connect(lambda _=False, s=style: self.app.set_style(s))
            self.style_group.addAction(act)
            self.style_menu.addAction(act)
            self.style_actions[style] = act
        self.menu.addSeparator()
        self.autostart = QAction("开机自启", self.menu, checkable=True)
        self.autostart.triggered.connect(self.app.set_autostart)
        self.menu.addAction(self.autostart)
        self.click_through = QAction("鼠标穿透（从托盘恢复）", self.menu,
                                     checkable=True)
        self.click_through.triggered.connect(
            lambda on: self.app.set_option("click_through", bool(on)))
        self.menu.addAction(self.click_through)
        self.fullscreen_hide = QAction("全屏时隐藏", self.menu, checkable=True)
        self.fullscreen_hide.triggered.connect(
            lambda on: self.app.set_option("hide_fullscreen", bool(on)))
        self.menu.addAction(self.fullscreen_hide)
        self.settings = self.menu.addAction("设置…")
        self.settings.triggered.connect(lambda: on_settings())
        self.menu.addSeparator()
        self.quit = self.menu.addAction("退出")
        self.quit.triggered.connect(self.app.quit)
        self.tray.setContextMenu(self.menu)
        self.tray.activated.connect(self._activated)
        self.tray.show()

    def _activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            self.app.window.toggle()

    def sync(self, cfg):
        for theme_id, act in self.theme_actions.items():
            act.setChecked(theme_id == cfg["theme"])
        for style, act in self.style_actions.items():
            act.setChecked(style == cfg["style"])
        self.autostart.setChecked(cfg["autostart"])
        self.click_through.setChecked(cfg.get("click_through", False))
        self.fullscreen_hide.setChecked(cfg.get("hide_fullscreen", True))
