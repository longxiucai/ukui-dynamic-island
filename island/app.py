"""Application wiring: window, sampler, tray, settings, logging."""
import json
import os
import sys
import traceback
from datetime import datetime

from PySide2.QtCore import QBuffer, QIODevice, Qt, QTimer
from PySide2.QtGui import QImage, QImageReader
from PySide2.QtWidgets import QApplication, QMessageBox

from island import (APP_ID, APP_NAME, __version__, autostart, blur, config,
                    inputmethod, theme)
from island.activity import Activity
from island.calendar import Calendar
from island.mail import MailAction, MailFetcher
from island.music import Music
from island.notify import NotifyWatcher
from island.presence import Presence
from island.productivity import MAX_CLIP_BYTES
from island.quota import Quota
from island.settings_window import SettingsDialog
from island.single_instance import SingleInstance
from island.sources import Sampler
from island.stock import Stock
from island.tray import Tray, app_icon
from island.weather import Weather
from island.window import IMAGE_SUFFIXES, IslandWindow


LOG_LIMIT = 1_000_000


def _log_path():
    return config.state_dir() / "island.log"


def _log(message: str, level="INFO") -> None:
    try:
        path = _log_path()
        if path.exists() and path.stat().st_size >= LOG_LIMIT:
            os.replace(path, path.with_name("island.log.1"))
    except OSError:
        return
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{stamp}] [{level}] [{__version__}] {message}\n"
    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


class IslandApp:
    def __init__(self, qt_app: QApplication):
        self.qt = qt_app
        self._issues = {}
        self.cfg = config.load()
        if config.LOAD_ERROR:
            _log("config load failed, using defaults: " + config.LOAD_ERROR,
                 "ERROR")
        self.theme_ids = theme.list_themes()
        self.themes = {tid: theme.load(tid) for tid in self.theme_ids}
        if self.cfg["theme"] not in self.themes:
            self.cfg["theme"] = "classic" if "classic" in self.themes else self.theme_ids[0]

        self.window = IslandWindow(self.cfg, self.active_theme)
        if self.window.productivity.load_error:
            _log("productivity load failed: "
                 + self.window.productivity.load_error, "ERROR")
        self.window.show()
        self.window.open_settings.connect(self.open_settings)
        self.window.option_change.connect(self.set_option)
        self.window.mail_action.connect(self._mail_operation)
        self.sampler = Sampler(
            monitor_enabled=self.cfg.get("show_monitor", True))
        self.window.monitor_focus.connect(self.sampler.set_monitor_enabled)
        self.sampler.sampled.connect(self.window.set_data)
        self.sampler.start()
        self.weather = Weather(self.cfg)
        self.weather.updated.connect(self._on_weather)
        self.weather.start()
        self.music = Music()
        self.music.updated.connect(self.window.set_music)
        self.window.music_command.connect(self.music.command)
        self.window.music_seek.connect(self.music.seek)
        self.music.start()

        self.mail_thread = self._start_mail()
        self.calendar_thread = self._start_calendar()
        self.quota_thread = self._start_quota()
        self.stock_thread = self._start_stock()
        self.activity_thread = self._start_activity()
        self.notify = NotifyWatcher()
        self.notify.notified.connect(self.window.add_notification)
        self.notify.failed.connect(self._notify_failed)
        self.notify.start()
        self.presence = Presence()
        self.presence.fullscreen.connect(self._on_fullscreen)
        self.presence.start()
        self._clip_guard = False
        self._mail_worker = None
        self._mail_pending_op = None
        self._retired = []
        qt_app.clipboard().dataChanged.connect(self._clip_changed)

        self.settings_dialog = None
        self.tray = Tray(self, self.themes, self.open_settings)
        self.tray.sync(self.cfg)
        if self.cfg.get("autostart"):
            try:
                if autostart.ensure():
                    _log(f"autostart entry repaired: {autostart.command()}")
            except OSError as exc:
                _log(f"autostart repair failed: {exc}", "ERROR")
        self._reposition()
        if self.cfg.get("click_through"):
            QTimer.singleShot(300, lambda: self.window.set_click_through(True))
        QTimer.singleShot(900, self._log_blur)
        _log(f"started theme={self.cfg['theme']} style={self.cfg['style']}")

    def _start_mail(self):
        thread = MailFetcher(self.cfg)
        thread.updated.connect(self._on_mail)
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None:
            dialog.watch_mail(thread)
        self.window.mail_refresh = thread.refresh
        thread.start()
        return thread

    def _mail_operation(self, action, uid=None):
        if self._mail_worker is not None and self._mail_worker.isRunning():
            # 上一条 IMAP 写操作还在跑：记下这一次，跑完立刻补做，不能悄悄丢掉
            self._mail_pending_op = (action, uid)
            return
        worker = MailAction(self.cfg, action, uid)
        worker.done.connect(self._on_mail_operation)
        worker.finished.connect(lambda: setattr(self, "_mail_worker", None))
        worker.finished.connect(self._run_pending_mail_op)
        self._mail_worker = worker
        worker.start()

    def _run_pending_mail_op(self):
        pending, self._mail_pending_op = self._mail_pending_op, None
        if pending:
            self._mail_operation(*pending)

    def _start_calendar(self):
        thread = Calendar(self.cfg)
        thread.updated.connect(self._on_calendar)
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None:
            dialog.watch_calendar(thread)
        self.window.calendar_refresh = thread.refresh
        thread.start()
        return thread

    def _start_quota(self):
        thread = Quota(self.cfg)
        thread.updated.connect(self._on_quota)
        dialog = getattr(self, "settings_dialog", None)
        if dialog is not None:
            dialog.watch_quota(thread)
        self.window.quota_refresh = thread.refresh
        thread.start()
        return thread

    def _start_stock(self):
        thread = Stock(self.cfg)
        thread.updated.connect(self._on_stock)
        self.window.stock_refresh = thread.refresh
        thread.start()
        return thread

    def _start_activity(self):
        if not self.cfg.get("show_activity", True):
            return None
        thread = Activity()
        thread.updated.connect(self.window.set_activity)
        thread.start()
        return thread

    def _set_activity_enabled(self, enabled):
        if enabled:
            if self.activity_thread is None:
                self.activity_thread = self._start_activity()
            return
        self._retire(self.activity_thread)
        self.activity_thread = None
        self.window.clear_activity()

    def _report_issue(self, key, message):
        message = " ".join(str(message).splitlines()).strip()
        if not message or self._issues.get(key) == message:
            return
        self._issues[key] = message
        _log(f"{key}: {message}", "WARN")

    def _clear_issue(self, key):
        if self._issues.pop(key, None) is not None:
            _log(f"{key}: recovered")

    def _on_weather(self, weather):
        self.window.set_weather(weather)
        if weather is None:
            return
        if weather.get("error"):
            self._report_issue("weather", weather["error"])
        elif not weather.get("stale") and weather.get("temp") is not None:
            self._clear_issue("weather")
        if weather.get("cache_error"):
            self._report_issue("weather:cache", weather["cache_error"])
        elif not weather.get("stale"):
            self._clear_issue("weather:cache")

    def _on_mail(self, result):
        self.window.set_mail(result)
        self._source_status("mail", result)

    def _on_mail_operation(self, result):
        self.window.set_mail_operation(result)
        self._source_status("mail:operation", result)

    def _on_calendar(self, result):
        self.window.set_calendar(result)
        self._source_status("calendar", result)

    def _on_stock(self, result):
        self.window.set_stock(result)
        result = result or {}
        code = result.get("code") or self.cfg.get("stock_code", "")
        self._source_status("stock", result, code)

    def _on_quota(self, result):
        self.window.set_quota(result)
        providers = (result or {}).get("providers") or []
        seen = set()
        for item in providers:
            key = "quota:" + str(item.get("id") or item.get("label") or "?")
            seen.add(key)
            self._source_status(key, item)
        for key in [key for key in self._issues
                    if key.startswith("quota:") and key not in seen]:
            self._clear_issue(key)

    def _source_status(self, key, result, label=""):
        result = result or {}
        status = result.get("status")
        if status == "error":
            prefix = f"{label}: " if label else ""
            self._report_issue(
                key, prefix + (result.get("error") or "读取失败"))
        elif status in ("ok", "unconfigured"):
            self._clear_issue(key)

    def _save_config(self):
        try:
            config.save(self.cfg)
        except Exception as exc:
            self._report_issue(
                "config:save", f"{type(exc).__name__}: {exc}")
        else:
            self._clear_issue("config:save")

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
        if "stock_code" in keys:
            self._retire(self.stock_thread)
            self.stock_thread = self._start_stock()

    def _clip_changed(self):
        if self._clip_guard:
            return
        clipboard = self.QApplication_clipboard()
        mime = clipboard.mimeData()
        text = clipboard.text()
        if mime is not None and mime.hasUrls() and self._record_clip_files(mime):
            self.window.update()
            return
        if text:
            recorded = bool(self.window.productivity.record_clip(text))
            if self.window.offer_meeting(text):
                return
        else:
            recorded = self._record_clip_image(mime)
        if recorded:
            self.window.update()

    def _record_clip_files(self, mime):
        """文件管理器复制图片只给 text/uri-list，没有图片数据，得按路径读字节。"""
        added = False
        for url in mime.urls():
            path = url.toLocalFile()
            if not path.lower().endswith(IMAGE_SUFFIXES):
                continue
            try:
                if os.path.getsize(path) > MAX_CLIP_BYTES:
                    continue
                with open(path, "rb") as handle:
                    blob = handle.read()
            except OSError:
                continue
            added = self._record_clip_png(blob) or added
        return added

    def _record_clip_image(self, mime):
        """复制的图片（截图最常见）进剪贴历史，只留内存字节，上架才落盘。

        Linux 剪贴板一般直接给 image/png，先照抄字节，省掉 UI 线程上的一次解码再编码。
        """
        if mime is None or not mime.hasImage():
            return False
        if "image/png" in (mime.formats() or []):
            return self._record_clip_png(bytes(mime.data("image/png")))
        image = QImage(mime.imageData())
        if image.isNull():
            return False
        buffer = QBuffer()
        buffer.open(QIODevice.WriteOnly)
        try:
            if not image.save(buffer, "PNG"):
                return False
            blob = bytes(buffer.data())
        finally:
            buffer.close()
        return self.window.productivity.record_clip_image(
            blob, image.width(), image.height())

    def _record_clip_png(self, blob):
        """PNG 字节先验尺寸再入历史；解不了的不收。"""
        if not blob:
            return False
        probe = QBuffer()
        probe.setData(blob)
        probe.open(QIODevice.ReadOnly)
        size = QImageReader(probe).size()
        probe.close()
        if not size.isValid():
            return False
        return self.window.productivity.record_clip_image(
            blob, size.width(), size.height())

    def QApplication_clipboard(self):
        return self.qt.clipboard()

    def _on_fullscreen(self, fullscreen):
        if self.cfg.get("hide_fullscreen", True):
            self.window.set_fullscreen_hidden(fullscreen)

    def _notify_failed(self, why):
        _log(f"notify unavailable: {why}", "WARN")
        self.window.set_notify_error(why)

    def _log_blur(self):
        supported = blur.supported()
        _log(f"blur hint {'advertised' if supported else 'not advertised by WM'}")

    @property
    def active_theme(self):
        """当前皮肤，玻璃皮肤会带上用户设定的透明度。"""
        current = self.themes[self.cfg["theme"]]
        alpha = self.cfg.get("glass_alpha")
        if alpha is None or current.material.get("kind") != "glass":
            return current
        return current.with_alpha(max(20, min(100, int(alpha))) / 100.0)

    def update_config(self, values):
        old = dict(self.cfg)
        self.cfg.update(values)
        self.window.apply(self.cfg, self.active_theme)
        if "click_through" in values:
            self.window.set_click_through(bool(self.cfg["click_through"]))
        if "hide_fullscreen" in values and not self.cfg["hide_fullscreen"]:
            self.window.set_fullscreen_hidden(False)
        self._restart_services(values)
        if old.get("enable_blur") != self.cfg.get("enable_blur"):
            QTimer.singleShot(100, self.window._apply_blur)
        self.tray.sync(self.cfg)
        self._save_config()

    def _reposition(self):
        self.window._apply_geometry()

    def set_theme(self, theme_id: str):
        if theme_id not in self.themes:
            return
        self.cfg["theme"] = theme_id
        self.window.apply(self.cfg, self.active_theme)
        self.tray.sync(self.cfg)
        self._save_config()

    def set_style(self, style: str):
        if style not in config.STYLES:
            return
        self.cfg["style"] = style
        self.window.apply(self.cfg, self.active_theme)
        self.tray.sync(self.cfg)
        self._save_config()

    def set_option(self, key: str, value):
        self.cfg[key] = value
        if key == "show_activity":
            self._set_activity_enabled(bool(value))
        self.window.apply(self.cfg, self.active_theme)
        if key == "click_through":
            self.window.set_click_through(bool(value))
        if key == "hide_fullscreen" and not value:
            self.window.set_fullscreen_hidden(False)
        self.tray.sync(self.cfg)
        self._save_config()

    def set_weather_city(self, city: str, lat=None, lon=None):
        city = city.strip()
        if not city:
            return
        self.cfg.update({"weather_city": city, "weather_auto": False,
                         "weather_lat": lat, "weather_lon": lon})
        self.window.set_weather(None)
        self.weather.set_place(city, lat, lon)
        self._save_config()

    def set_weather_auto(self):
        self.cfg["weather_auto"] = True
        self.window.set_weather(None)
        self.weather.set_auto()
        self._save_config()

    def set_stock_code(self, code: str):
        if not code or code == self.cfg["stock_code"]:
            return
        self.update_config({"stock_code": code})

    def set_autostart(self, on: bool):
        try:
            autostart.set_enabled(bool(on))
        except OSError as exc:
            _log(f"autostart failed: {exc}", "ERROR")
            if self.settings_dialog is not None:
                QMessageBox.warning(self.settings_dialog, APP_NAME,
                                    f"写入开机自启失败：{exc}")
            return
        self.cfg["autostart"] = bool(on)
        self.tray.sync(self.cfg)
        self._save_config()

    def open_settings(self, page=None):
        self.window.set_expanded(False, animate=False)
        if self.settings_dialog is None:
            self.settings_dialog = SettingsDialog(self)
            for thread, watch in (
                    (self.weather, self.settings_dialog.watch_weather),
                    (self.mail_thread, self.settings_dialog.watch_mail),
                    (self.calendar_thread, self.settings_dialog.watch_calendar),
                    (self.quota_thread, self.settings_dialog.watch_quota)):
                if thread is not None:
                    watch(thread)
        if self.quota_thread is not None:
            self.quota_thread.refresh()
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
        self._stop(self.stock_thread)
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
    from island import (activity, calendar, geometry, mail, meeting, quota,
                        render, stock)

    app = QGuiApplication(argv)
    assert app.platformName()
    assert mail.extract_code("验证码 482913") == "482913"
    assert meeting.parse_meeting(
        "会议主题：交付评审\n会议时间：2099-01-01 09:20-09:50\n"
        "#腾讯会议：902-631-704")["code"] == "902631704"
    assert calendar.parse_ics(
        "BEGIN:VEVENT\r\nSUMMARY:测试\r\nDTSTART:20261117T100000\r\n"
        "END:VEVENT\r\n")[0]["summary"] == "测试"
    assert quota.parse_url_payload({"percent": 50})["percent"] == 0.5
    assert stock.normalize_code("600519") == "sh600519"
    assert quota.parse_codex_limits(
        {"primary": {"used_percent": 25, "window_minutes": 300}}
    )[0]["label"] == "5 小时"
    tick = activity.empty()
    activity.parse_codex(
        tick, {"type": "event_msg", "payload": {"type": "agent_message",
                                                "message": "ok"}}, 1.0)
    assert tick["state"] == "responding" and tick["detail"] == "ok"
    report = {"version": __version__, "themes": [], "rendered": [],
              "modules": ["mail", "calendar", "quota", "stock", "activity",
                          "meeting", "notify"]}
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

    inputmethod.ensure(_log)
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
        _log("".join(traceback.format_exception(exc_type, exc, tb)), "ERROR")
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = excepthook
    app = None
    try:
        app = IslandApp(qt_app)
        instance.activated.connect(app.toggle)
        return qt_app.exec_()
    except Exception:
        _log(traceback.format_exc(), "ERROR")
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
                         "stock_thread", "activity_thread", "notify",
                         "presence"):
                app._stop(getattr(app, name, None))
