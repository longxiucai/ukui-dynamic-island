"""Application wiring: window, sampler, tray, settings, logging."""
import json
import os
import sys
import traceback

from PySide2.QtCore import Qt, QTimer
from PySide2.QtWidgets import QApplication, QMessageBox

from island import (APP_ID, APP_NAME, __version__, autostart, blur, config,
                    theme)
from island.activity import Activity
from island.calendar import Calendar
from island.mail import MailAction, MailFetcher
from island.music import Music
from island.notify import NotifyWatcher
from island.presence import Presence
from island.quota import Quota
from island.settings_window import SettingsDialog
from island.single_instance import SingleInstance
from island.sources import Sampler
from island.tray import Tray, app_icon
from island.weather import Weather
from island.window import IslandWindow


def _log_path():
    return config.state_dir() / "island.log"


def _log(message: str) -> None:
    line = f"[{__version__}] {message}\n"
    try:
        with open(_log_path(), "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


class IslandApp:
    def __init__(self, qt_app: QApplication):
        self.qt = qt_app
        self.cfg = config.load()
        self.theme_ids = theme.list_themes()
        self.themes = {tid: theme.load(tid) for tid in self.theme_ids}
        if self.cfg["theme"] not in self.themes:
            self.cfg["theme"] = "classic" if "classic" in self.themes else self.theme_ids[0]

        self.window = IslandWindow(self.cfg, self.themes[self.cfg["theme"]])
        self.window.show()
        self.window.open_settings.connect(self.open_settings)
        self.window.option_change.connect(self.set_option)
        self.window.mail_action.connect(self._mail_operation)
        self.sampler = Sampler(
            monitor_enabled=self.cfg.get("show_monitor", True))
        self.sampler.sampled.connect(self.window.set_data)
        self.sampler.start()
        self.weather = Weather(self.cfg)
        self.weather.updated.connect(self.window.set_weather)
        self.weather.start()
        self.music = Music()
        self.music.updated.connect(self.window.set_music)
        self.window.music_command.connect(self.music.command)
        self.window.music_seek.connect(self.music.seek)
        self.music.start()

        self.mail_thread = self._start_mail()
        self.calendar_thread = self._start_calendar()
        self.quota_thread = self._start_quota()
        self.activity_thread = Activity()
        self.activity_thread.updated.connect(self.window.set_activity)
        self.activity_thread.start()
        self.notify = NotifyWatcher()
        self.notify.notified.connect(self.window.add_notification)
        self.notify.failed.connect(self._notify_failed)
        self.notify.start()
        self.presence = Presence()
        self.presence.fullscreen.connect(self._on_fullscreen)
        self.presence.start()
        self._clip_guard = False
        self._mail_worker = None
        self._retired = []
        qt_app.clipboard().dataChanged.connect(self._clip_changed)

        self.settings_dialog = None
        self.tray = Tray(self, self.themes, self.open_settings)
        self.tray.sync(self.cfg)
        self._reposition()
        if self.cfg.get("click_through"):
            QTimer.singleShot(300, lambda: self.window.set_click_through(True))
        QTimer.singleShot(900, self._log_blur)
        _log(f"started theme={self.cfg['theme']} style={self.cfg['style']}")

    def _start_mail(self):
        thread = MailFetcher(self.cfg)
        thread.updated.connect(self.window.set_mail)
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None:
            dialog.watch_mail(thread)
        self.window.mail_refresh = thread.refresh
        thread.start()
        return thread

    def _mail_operation(self, action, uid=None):
        if self._mail_worker is not None and self._mail_worker.isRunning():
            return
        worker = MailAction(self.cfg, action, uid)
        worker.done.connect(self.window.set_mail_operation)
        worker.finished.connect(lambda: setattr(self, "_mail_worker", None))
        self._mail_worker = worker
        worker.start()

    def _start_calendar(self):
        thread = Calendar(self.cfg)
        thread.updated.connect(self.window.set_calendar)
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None:
            dialog.watch_calendar(thread)
        self.window.calendar_refresh = thread.refresh
        thread.start()
        return thread

    def _start_quota(self):
        thread = Quota(self.cfg)
        thread.updated.connect(self.window.set_quota)
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None:
            dialog.watch_quota(thread)
        self.window.quota_refresh = thread.refresh
        thread.start()
        return thread

    def _stop(self, thread, timeout=2000):
        if thread is None:
            return True
        thread.requestInterruption()
        if hasattr(thread, "stop"):
            thread.stop()
        return thread.wait(timeout)

    def _retire(self, thread, timeout=500):
        if thread is None or self._stop(thread, timeout):
            return
        self._retired.append(thread)
        thread.finished.connect(
            lambda: self._retired.remove(thread)
            if thread in self._retired else None)

    def _restart_services(self, values):
        keys = tuple(values)
        if any(key.startswith("mail_") for key in keys):
            self._retire(self._mail_worker)
            self._retire(self.mail_thread)
            self.mail_thread = self._start_mail()
        if any(key.startswith("calendar_") for key in keys):
            self._retire(self.calendar_thread)
            self.calendar_thread = self._start_calendar()
        if any(key.startswith("quota_") for key in keys) or any(
                key in ("codex_online", "claude_online", "workbuddy_online",
                        "trae_online", "copilot_online") for key in keys):
            self._retire(self.quota_thread)
            self.quota_thread = self._start_quota()

    def _clip_changed(self):
        if self._clip_guard:
            return
        text = self.QApplication_clipboard().text()
        if text and self.window.productivity.record_clip(text):
            self.window.update()

    def QApplication_clipboard(self):
        return self.qt.clipboard()

    def _on_fullscreen(self, fullscreen):
        if self.cfg.get("hide_fullscreen", True):
            self.window.set_fullscreen_hidden(fullscreen)

    def _notify_failed(self, why):
        _log(f"notify unavailable: {why}")
        self.window.set_notify_error(why)

    def _log_blur(self):
        supported = blur.supported()
        _log(f"blur hint {'advertised' if supported else 'not advertised by WM'}")

    def update_config(self, values):
        old = dict(self.cfg)
        self.cfg.update(values)
        if "show_monitor" in values:
            self.sampler.set_monitor_enabled(
                bool(self.cfg.get("show_monitor", True)))
        self.window.apply(self.cfg, self.themes[self.cfg["theme"]])
        if "click_through" in values:
            self.window.set_click_through(bool(self.cfg["click_through"]))
        if "hide_fullscreen" in values and not self.cfg["hide_fullscreen"]:
            self.window.set_fullscreen_hidden(False)
        self._restart_services(values)
        if old.get("enable_blur") != self.cfg.get("enable_blur"):
            QTimer.singleShot(100, self.window._apply_blur)
        self.tray.sync(self.cfg)
        config.save(self.cfg)

    def _reposition(self):
        self.window._apply_geometry()

    def set_theme(self, theme_id: str):
        if theme_id not in self.themes:
            return
        self.cfg["theme"] = theme_id
        self.window.apply(self.cfg, self.themes[theme_id])
        self.tray.sync(self.cfg)
        config.save(self.cfg)

    def set_style(self, style: str):
        if style not in config.STYLES:
            return
        self.cfg["style"] = style
        self.window.apply(self.cfg, self.themes[self.cfg["theme"]])
        self.tray.sync(self.cfg)
        config.save(self.cfg)

    def set_option(self, key: str, value):
        self.cfg[key] = value
        if key == "show_monitor":
            self.sampler.set_monitor_enabled(bool(value))
        self.window.apply(self.cfg, self.themes[self.cfg["theme"]])
        if key == "click_through":
            self.window.set_click_through(bool(value))
        if key == "hide_fullscreen" and not value:
            self.window.set_fullscreen_hidden(False)
        self.tray.sync(self.cfg)
        config.save(self.cfg)

    def set_weather_city(self, city: str):
        city = city.strip()
        if not city or city == self.cfg["weather_city"]:
            return
        self.cfg["weather_city"] = city
        self.window.set_weather(None)
        self.weather.set_place(city)
        config.save(self.cfg)

    def set_autostart(self, on: bool):
        try:
            autostart.set_enabled(bool(on))
        except OSError as exc:
            _log(f"autostart failed: {exc}")
            if self.settings_dialog is not None:
                QMessageBox.warning(self.settings_dialog, APP_NAME,
                                    f"写入开机自启失败：{exc}")
            return
        self.cfg["autostart"] = bool(on)
        self.tray.sync(self.cfg)
        config.save(self.cfg)

    def open_settings(self, page=None):
        self.window.set_expanded(False, animate=False)
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.select_tab(page)
        self.settings_dialog.show()
        self.settings_dialog.raise_()
        self.settings_dialog.activateWindow()

    def toggle(self):
        self.window.toggle()

    def quit(self):
        self.sampler.requestInterruption()
        self.sampler.wait(1500)
        self.weather.requestInterruption()
        self.weather.wait(4500)
        self.music.requestInterruption()
        self.music.wait(2000)
        self._stop(self.mail_thread)
        self._stop(self.calendar_thread)
        self._stop(self.quota_thread)
        self._stop(self.activity_thread)
        self._stop(self.notify)
        self._stop(self.presence)
        self._stop(self._mail_worker)
        for thread in list(self._retired):
            self._stop(thread, 5000)
        self._retired = []
        self.tray.tray.hide()
        self.qt.quit()


def _self_test(argv) -> int:
    from PySide2.QtCore import QRectF
    from PySide2.QtGui import QGuiApplication, QImage, QPainter
    from island import activity, calendar, geometry, mail, quota, render

    app = QGuiApplication(argv)
    assert app.platformName()
    assert mail.extract_code("验证码 482913") == "482913"
    assert calendar.parse_ics(
        "BEGIN:VEVENT\r\nSUMMARY:测试\r\nDTSTART:20261117T100000\r\n"
        "END:VEVENT\r\n")[0]["summary"] == "测试"
    assert quota.parse_url_payload({"percent": 50})["percent"] == 0.5
    assert quota.parse_codex_limits(
        {"primary": {"used_percent": 25, "window_minutes": 300}}
    )[0]["label"] == "5 小时"
    tick = activity.empty()
    activity.parse_codex(
        tick, {"type": "event_msg", "payload": {"type": "agent_message",
                                                "message": "ok"}}, 1.0)
    assert tick["state"] == "responding" and tick["detail"] == "ok"
    report = {"version": __version__, "themes": [], "rendered": [],
              "modules": ["mail", "calendar", "quota", "activity", "notify"]}
    for tid in theme.list_themes():
        t = theme.load(tid)
        report["themes"].append({"id": t.id, "name": t.name, "kind": t.material.get("kind")})
    for style in config.STYLES:
        shape = geometry.resolve(style, 1920, 100, content_width=128)
        img = QImage(400, 80, QImage.Format_ARGB32_Premultiplied)
        img.fill(0)
        p = QPainter(img)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(20, 10)
        render.paint_surface(p, render.surface_path(shape), theme.load("classic"))
        p.end()
        if img.isNull():
            return 2
        report["rendered"].append(style)
    print(json.dumps(report, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    argv = list(sys.argv if argv is None else argv)
    if "--version" in argv:
        print(f"{APP_NAME} {__version__}")
        return 0
    if "--self-test" in argv:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        return _self_test([sys.argv[0]])

    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    qt_app = QApplication(sys.argv[:1])
    qt_app.setApplicationName(APP_ID)
    qt_app.setApplicationDisplayName(APP_NAME)
    qt_app.setWindowIcon(app_icon())
    qt_app.setQuitOnLastWindowClosed(False)

    instance = SingleInstance(qt_app)
    if not instance.acquire():
        return 0

    def excepthook(exc_type, exc, tb):
        _log("".join(traceback.format_exception(exc_type, exc, tb)))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook
    app = None
    try:
        app = IslandApp(qt_app)
        instance.activated.connect(app.toggle)
        return qt_app.exec_()
    except Exception:
        _log(traceback.format_exc())
        raise
    finally:
        if app is not None:
            app.sampler.requestInterruption()
            app.sampler.wait(1500)
            app.weather.requestInterruption()
            app.weather.wait(4500)
            app.music.requestInterruption()
            app.music.wait(2000)
            for name in ("mail_thread", "calendar_thread", "quota_thread",
                         "activity_thread", "notify", "presence"):
                app._stop(getattr(app, name, None))
