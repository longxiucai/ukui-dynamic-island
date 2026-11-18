"""Render every (style, theme) pair through the real widget. No desktop needed.

    QT_QPA_PLATFORM=offscreen .build-venv/bin/python tests/smoke_offscreen.py
"""
import os
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = tempfile.mkdtemp(prefix="island-smoke-")
os.environ["UKUI_ISLAND_CONFIG_DIR"] = tmp + "/config"
os.environ["UKUI_ISLAND_STATE_DIR"] = tmp + "/state"

from PySide2.QtCore import (QEvent, QMimeData, QObject, QPoint, QPointF,
                            QUrl, Qt, Signal)  # noqa: E402
from PySide2.QtGui import (QDragEnterEvent, QDropEvent, QImage,
                           QMouseEvent, QPainter, QWheelEvent)  # noqa: E402
from PySide2.QtWidgets import QApplication  # noqa: E402

from island import config, sources, theme  # noqa: E402
from island.window import LYRIC_FADE, PAGES, IslandWindow  # noqa: E402


def check_ring_gauge() -> None:
    from island import render
    t = theme.load("classic")
    image = QImage(48, 48, QImage.Format_ARGB32)
    image.fill(t.color("surface"))
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing, False)
    p.setRenderHint(QPainter.TextAntialiasing, False)
    render.paint_ring_gauge(p, 4, 24, 40, 0.25, "50", t, "accent")
    p.end()
    accent = t.color("accent").name()
    assert image.pixelColor(24, 6).name() == accent
    assert image.pixelColor(43, 24).name() == accent
    assert image.pixelColor(24, 42).name() != accent
    assert image.pixelColor(5, 24).name() != accent
    assert any(image.pixelColor(x, y).name() == t.color("textPrimary").name()
               for x in range(12, 37) for y in range(12, 37))

    for level in (0.8, 0.85, 0.92):
        image = QImage(48, 48, QImage.Format_ARGB32)
        image.fill(t.color("surface"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setRenderHint(QPainter.TextAntialiasing, False)
        render.paint_ring_gauge(p, 4, 24, 40, level, "90", t, "accent")
        p.end()
        color = render.ring_color(t, level, "accent").name()
        assert image.pixelColor(43, 24).name() == color
        assert any(image.pixelColor(x, y).name() == color
                   for x in range(12, 37) for y in range(12, 37))


def check_music_states() -> None:
    cfg = dict(config.DEFAULTS)
    data = {"battery": 0.82, "charging": False, "volume": 0.46,
            "memory": 0.37, "cpu": 0.23, "net_down": 1_240_000,
            "net_up": 320_000, "online": True,
            "weather": {"temp": 12, "text": "多云", "place": "北京"}}
    music = {"title": "晴天", "artist": "周杰伦", "album": "叶惠美",
             "status": "Playing", "position": 42, "length": 215,
             "art_path": "", "player": "org.mpris.MediaPlayer2.spotify",
             "lyric": [(0.0, "故事的小黄花")]}
    for expanded in (False, True):
        for state in (None, music, {**music, "status": "Paused"}):
            win = IslandWindow(dict(cfg), theme.load("classic"))
            win.set_data(data)
            win.set_music(state)
            win.set_expanded(expanded, animate=False)
            pix = win.grab()
            assert not pix.isNull() and pix.width() > 0
            win.close()
            win.deleteLater()


def check_seek_drag() -> None:
    music = {"title": "晴天", "artist": "周杰伦", "status": "Playing",
             "position": 40, "length": 200, "can_seek": True,
             "player": "org.mpris.MediaPlayer2.spotify"}
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_music(music)
    win.set_expanded(True, animate=False)
    seen = []
    win.music_seek.connect(seen.append)
    bar = win._music_layout()["progress"]

    def event(kind, x):
        return QMouseEvent(kind,
                           QPointF(x - win._window_rect.left(),
                                   bar.center().y() - win._window_rect.top()),
                           Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)

    win.mousePressEvent(event(QEvent.MouseButtonPress, bar.left() + bar.width() * 0.25))
    win.mouseMoveEvent(event(QEvent.MouseMove, bar.left() + bar.width() * 0.75))
    win.mouseReleaseEvent(event(QEvent.MouseButtonRelease, bar.left() + bar.width() * 0.75))
    assert abs(win._seek_preview - 150) < 1
    assert len(seen) == 1 and abs(seen[0] - 150) < 1
    win.close()
    win.deleteLater()


def check_lyrics_motion() -> None:
    lines = [(0.0, "故事的小黄花"), (3.0, "从出生那年就飘着"),
             (6.0, "童年的荡秋千"), (9.0, "随记忆一直晃到现在")]
    base = {"title": "晴天", "artist": "周杰伦", "album": "叶惠美",
            "status": "Playing", "length": 215, "art_path": "",
            "lyric": lines, "player": True}
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_music(dict(base, position=7.0))
    win.set_expanded(True, animate=False)
    win.grab()
    on_size = win._music_layout()["cover"].width()
    win._show_lyrics = False
    assert win._music_layout()["cover"].width() == on_size
    win._show_lyrics = True
    win._lyrics_on = False
    win._lyrics_at = time.monotonic()
    win.grab()
    assert 0.0 <= win._lyrics_mix() < 0.2
    win._lyrics_at = time.monotonic() - LYRIC_FADE - 0.01
    assert win._lyrics_mix() == 1.0
    win.set_music(dict(base, position=10.0))
    assert win._lyric_ease() < 0.2
    win._lyric_at = time.monotonic() - LYRIC_FADE - 0.01
    assert win._lyric_ease() == 1.0
    win.close()
    win.deleteLater()


def check_mail_timeout() -> None:
    import socket

    from island import mail

    seen = []
    original = socket.create_connection

    def fake(addr, timeout=None):
        seen.append(timeout)
        raise OSError("test")

    socket.create_connection = fake
    try:
        for cls in (mail._TimeoutIMAP4, mail._TimeoutIMAP4SSL):
            seen.clear()
            try:
                cls("example.com", 993)
            except OSError:
                pass
            assert seen == [5], cls
    finally:
        socket.create_connection = original


def check_mail_badge() -> None:
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    item = {"sender": "a@example.com", "subject": "新邮件", "date": "13:31",
            "seen": False}
    key = win._mail_key(item)
    win._mail_new[key] = time.monotonic() + 600
    win._mail_mark_read(item)
    assert key not in win._mail_new and not win._mail_unread(item)
    win.mail["unread"] = 0
    assert win._mail_badge() == ""
    win.mail["unread"] = 7
    assert win._mail_badge() == "7"
    win.mail["unread"] = 3647
    assert win._mail_badge() == "99+"
    win.close()
    win.deleteLater()


def check_compact_width() -> None:
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": None, "cpu": 0.16, "memory": 0.68})
    idle_width = win.base.rect.width()
    win.productivity.add_todo("紧凑宽度")
    win._apply_geometry()
    assert win.base.rect.width() > idle_width
    win.set_data({"battery": 0.82, "charging": False, "cpu": 0.16, "memory": 0.68})
    assert win.base.rect.width() > idle_width + 20
    win.set_data({"battery": None, "cpu": 0.16, "memory": 0.68})
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 40, "length": 200})
    short_width = win.base.rect.width()
    win.set_music({"title": "A Very Long Song Title That Needs Room",
                   "artist": "Artist", "status": "Playing",
                   "position": 40, "length": 200})
    assert idle_width < short_width < win.base.rect.width()
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 1, "length": 200,
                   "lyric": [(0.0, "短"), (2.0, "这一句歌词特别长特别长特别长特别长")]})
    lyric_width = win.base.rect.width()
    win.set_music({**win.music, "position": 3})
    assert win.base.rect.width() == lyric_width
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 0, "length": 200,
                   "lyric": [(5.0, "这一句歌词特别长特别长特别长特别长")]})
    prelude_width = win.base.rect.width()
    win.set_music({**win.music, "position": 6})
    assert win.base.rect.width() == prelude_width
    win.set_music(None)
    win.focus["running"] = True
    win.mail["unread"] = 2
    win._apply_geometry()
    assert win.base.rect.width() > idle_width
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 3, "length": 200,
                   "lyric": [(0.0, "这一句歌词特别长特别长特别长特别长")]})
    win.set_data({"battery": 0.82, "charging": False, "cpu": 0.16,
                  "memory": 0.68,
                  "weather": {"temp": 12, "text": "多云", "place": "北京"}})
    assert win._content_width() <= win._compact_capacity(1.0) + 0.01
    assert win.base.rect.width() <= win.open_shape.rect.width()
    win.close()
    win.deleteLater()


def check_compact_motion() -> None:
    import time

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": 0.8, "cpu": 0.2, "memory": 0.3})
    win.set_music(None)
    win._apply_geometry()
    rest = win.base.rect.width()
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 1, "length": 200,
                   "lyric": [(0.0, "故事的小黄花")]})
    target = win._w.target
    assert target > rest and win._frame.isActive()
    peak = win._w.value
    for _ in range(40):
        win._last_frame = time.monotonic() - 1 / 60
        win._advance()
        peak = max(peak, win._w.value)
    assert peak > target, (peak, target)
    assert abs(win._w.value - target) < 0.6, (win._w.value, target)

    win.set_music(None)
    target = win._w.target
    low = win._w.value
    for _ in range(40):
        win._last_frame = time.monotonic() - 1 / 60
        win._advance()
        low = min(low, win._w.value)
    assert low >= target - 0.01, (low, target)
    win.close()
    win.deleteLater()


def check_reminders() -> None:
    import time

    import island.window as window_module

    cfg = dict(config.DEFAULTS)
    cfg.update({"focus_remind": True, "water_remind": True,
                "water_minutes": 45, "mail_remind": True})
    win = IslandWindow(cfg, theme.load("classic"))
    win.set_data({"battery": 0.8, "cpu": 0.2, "memory": 0.3})
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 1, "length": 200,
                   "lyric": [(0.0, "故事的小黄花")]})

    win.focus.update({"phase": "focus", "running": True, "remaining": 1,
                      "total": 25 * 60})
    win._tick()
    assert win._focus_done and win.focus["phase"] == "rest"
    assert win._notice and win._notice["kind"] == "focus"
    assert any(part[0] == "notice" for part in win._compact_parts(1.0))
    assert win._content_width() <= win._compact_capacity(1.0) + 0.01
    assert not win.grab().isNull()
    win._notice_until = time.monotonic() - 1
    win._tick()
    assert win._notice is None
    assert any(part[0] == "focus" for part in win._compact_parts(1.0))

    original_hours = window_module.WATER_HOURS
    window_module.WATER_HOURS = (0, 24)
    try:
        win._water_pending = False
        win._water_due = time.monotonic() - 1
        win._water_tick()
        assert win._water_pending and win._notice
        assert win._notice["kind"] == "water"
        win._notice_until = time.monotonic() - 1
        win._tick()
        assert any(part[0] == "water" for part in win._compact_parts(1.0))
        win.set_page("water")
        win.set_expanded(True, animate=False)
        win.grab()
        assert any(action in ("water_ack", "water_drink")
                   for _, action, _ in win._hits)
        win.set_expanded(False, animate=False)
        before = win.productivity.water_ml
        win._do_action("water_ack", None)
        assert not win._water_pending
        assert win.productivity.water_ml == before
        win._water_due = time.monotonic() - 1
        win._water_tick()
        assert win._water_pending
        win._do_action("water_drink", None)
        assert not win._water_pending
        assert win.productivity.water_ml == before + 250
    finally:
        window_module.WATER_HOURS = original_hours

    old = {"sender": "王工", "subject": "本周评审", "date": "12:10",
           "code": "", "preview": ""}
    fresh = {"sender": "GitHub", "subject": "code 482913", "date": "12:20",
             "code": "482913", "preview": ""}
    win.set_mail({"status": "ok", "items": [old]})
    win._notice = None
    win._alerts = []
    win._notice_until = 0
    win.set_mail({"status": "ok", "items": [fresh, old]})
    assert win._notice and win._notice["kind"] == "mail"
    assert "482913" not in win._notice_text(win._notice)

    seen = []
    original_paint_text = window_module.render.paint_text

    def spy(painter, rect, text, *args, **kwargs):
        seen.append(str(text))
        return original_paint_text(painter, rect, text, *args, **kwargs)

    window_module.render.paint_text = spy
    try:
        win.set_expanded(False, animate=False)
        win.grab()
    finally:
        window_module.render.paint_text = original_paint_text
    assert "482913" not in " ".join(seen)
    assert any("验证码邮件" in text for text in seen)

    win._open_notice()
    assert win.expanded and win.page == "mail" and win._mail_detail == 0
    win.grab()
    assert any(action == "copy" and arg == "482913"
               for _, action, arg in win._hits)
    win._do_action("copy", "482913")
    assert QApplication.clipboard().text() == "482913"
    seen = []
    window_module.render.paint_text = spy
    try:
        win.grab()
    finally:
        window_module.render.paint_text = original_paint_text
    assert any("已复制" in text for text in seen)

    win.set_expanded(False, animate=False)
    win._notice = None
    win._alerts = []
    win.set_fullscreen_hidden(True)
    win._enqueue_alert("focus", "全屏时排队", "", "focus")
    assert win._notice is None and len(win._alerts) == 1
    win.set_fullscreen_hidden(False)
    assert win._notice and win._notice["title"] == "全屏时排队"
    win.close()
    win.deleteLater()


def check_notice_pet_clip() -> None:
    import island.window as window_module

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": 0.8, "cpu": 0.2, "memory": 0.3})
    win._enqueue_alert("water", "喝水时间到了", "", "water")
    win.set_expanded(False, animate=False)
    win._apply_geometry(animate=False)
    seen = []
    original = window_module.render.paint_pet

    def spy(painter, x, cy, size, *args, **kwargs):
        clip = painter.clipBoundingRect()
        seen.append((x, size, clip.left(), clip.right()))
        return original(painter, x, cy, size, *args, **kwargs)

    window_module.render.paint_pet = spy
    try:
        win.grab()
    finally:
        window_module.render.paint_pet = original
    assert seen, "compact notice did not paint the pet"
    for x, size, clip_left, clip_right in seen:
        assert clip_left <= x and clip_right >= x + size, (x, size, clip_right)
    win.close()
    win.deleteLater()


def check_refresh_feedback() -> None:
    import island.window as window_module

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_expanded(True, animate=False)
    win.set_page("mail")
    calls = []
    win.mail_refresh = lambda: calls.append("mail")
    win._do_action("mail_refresh")
    assert calls == ["mail"] and win._refreshing("mail")
    seen = []
    original_paint_text = window_module.render.paint_text

    def spy(painter, rect, text, *args, **kwargs):
        seen.append(str(text))
        return original_paint_text(painter, rect, text, *args, **kwargs)

    window_module.render.paint_text = spy
    try:
        win.grab()
    finally:
        window_module.render.paint_text = original_paint_text
    assert "刷新中" in seen
    win.set_mail({"status": "ok", "items": [], "unread": 0})
    assert not win._refreshing("mail")

    win.set_page("calendar")
    calls = []
    win.calendar_refresh = lambda: calls.append("calendar")
    win._do_action("calendar_refresh")
    assert calls == ["calendar"] and win._refreshing("calendar")
    win.set_calendar({"status": "ok", "items": []})
    assert not win._refreshing("calendar")
    win.close()
    win.deleteLater()


def check_clock_text() -> None:
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    now = datetime(2026, 11, 17, 14, 5, 9)
    win.cfg.update({"clock_12h": True, "clock_period": 1, "show_weekday": True})
    assert win._clock_text(now) == "下午 2:05 周二"
    win.cfg["clock_english"] = True
    assert win._clock_text(now) == "Tue 2:05 PM"
    win.cfg.update({"clock_12h": False, "show_seconds": True, "clock_period": 2})
    assert win._clock_text(now) == "Tue 14:05:09"
    win.cfg.update({"clock_english": False, "show_weekday": False,
                    "clock_period": 1})
    assert win._clock_text(now) == "14:05:09"
    assert win._panel_clock(now) == "14:05:09"
    win.cfg["clock_12h"] = True
    win.cfg["clock_period"] = 2
    for hour, label in ((5, "凌晨"), (6, "上午"), (11, "中午"),
                        (13, "下午"), (17, "傍晚"), (19, "晚上")):
        assert win._clock_text(now.replace(hour=hour)).startswith(label + " ")
    opened = []
    win.open_settings.connect(opened.append)
    win.page = "mail"
    win._do_action("settings")
    win._do_action("settings", "calendar")
    assert opened == ["mail", "calendar"]
    win.close()
    win.deleteLater()


def check_weather_slot() -> None:
    from PySide2.QtGui import QImage, QPainter
    from island import render

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": None, "cpu": 0.16, "memory": 0.68})
    plain_width = win.base.rect.width()
    win.set_data({"battery": None, "cpu": 0.16, "memory": 0.68,
                  "weather": {"place": "长沙", "text": "小雨", "temp": 13}})
    slot = win._weather_slot(1.0)
    assert slot["text"] == "13°" and slot["kind"] == "rain"
    assert win.base.rect.width() > plain_width

    # The weather stays pinned to the clock: a wider activity label must not
    # move it or push it under the clock before the pill has grown.
    def painted_weather_x(label):
        win.set_activity({"provider": "Codex", "state": "working",
                          "label": label, "detail": "", "active": True,
                          "at": time.time()})
        seen = []

        def capture(painter, x, cy, size, kind, t):
            seen.append(x)
            original(painter, x, cy, size, kind, t)

        original = render.paint_weather_icon
        render.paint_weather_icon = capture
        try:
            win.grab()
        finally:
            render.paint_weather_icon = original
        return seen[-1]

    narrow = painted_weather_x("正在执行")
    wide = painted_weather_x("正在改文件")
    assert narrow == wide, (narrow, wide)
    win.set_activity({"provider": "Codex", "state": "idle", "label": "空闲",
                      "detail": "", "active": False, "at": 0.0})

    t = theme.load("classic")
    for kind in ("sun", "cloud", "rain", "snow", "thunder", "fog"):
        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(t.color("surface"))
        p = QPainter(image)
        render.paint_weather_icon(p, 4, 12, 16, kind, t)
        p.end()
        assert any(image.pixelColor(x, y).name() != t.color("surface").name()
                   for x in range(24) for y in range(24)), kind

    win.cfg["show_weather"] = False
    win._apply_geometry()
    assert win.base.rect.width() == plain_width
    win.close()
    win.deleteLater()


def check_lyric_wrap() -> None:
    from island import lyrics, render

    text = "这一行歌词很长很长需要按照参考项目的方式自动折行并且随着播放进度翻页显示"
    rows = render.wrap_text(text, 10.5, 90)
    assert len(rows) > 2 and "".join(rows) == text
    lines = [(0.0, text), (20.0, "下一句")]
    info = lyrics.current(lines, 10.0)
    assert info["text"] == text and info["start"] == 0.0 and info["end"] == 20.0

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    visible, first = win._lyric_page(rows, 2, info, 1.0)
    assert visible == rows[:2] and first == 0
    visible, first = win._lyric_page(rows, 2, info, 19.0)
    assert visible == rows[-2:] and first == len(rows) - 2
    win.close()
    win.deleteLater()


def check_shelf_press() -> None:
    import island.window as window_module

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.productivity.add_shelf("/etc/hosts")
    win.set_expanded(True, animate=False)
    win.set_page("tools")
    win.set_tools_page("shelf")
    win.grab()
    rect = next(rect for rect, action, _ in win._hits if action == "shelf_open")
    point = rect.center() - QPointF(win._window_rect.left(),
                                    win._window_rect.top())
    win.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, point,
                                    Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
    assert win._shelf_press and win._shelf_press[0] == "/etc/hosts"
    captured = {}

    class FakeDrag:
        def __init__(self, parent):
            captured["parent"] = parent

        def setMimeData(self, mime):
            captured["mime"] = mime

        def exec_(self, action):
            captured["action"] = action

    original = window_module.QDrag
    window_module.QDrag = FakeDrag
    try:
        win.mouseMoveEvent(QMouseEvent(
            QEvent.MouseMove, point + QPointF(12, 0), Qt.LeftButton,
            Qt.LeftButton, Qt.NoModifier))
    finally:
        window_module.QDrag = original
    assert captured["parent"] is win
    assert captured["mime"].urls()[0].toLocalFile() == "/etc/hosts"
    assert not win._shelf_press and not win._shelf_dragging
    win.close()
    win.deleteLater()


def check_pages() -> None:
    from island import render

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": 0.82, "charging": False, "volume": 0.46,
                  "memory": 0.37, "cpu": 0.83, "disk": 0.62, "temperature": 54,
                  "gpu": None, "net_down": 1_240_000, "net_up": 320_000,
                  "online": True,
                  "weather": {"temp": 13, "text": "小雨", "place": "长沙"}})
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 42, "length": 215, "can_seek": True,
                   "player": "org.mpris.MediaPlayer2.spotify",
                   "lyric": [(0.0, "故事的小黄花")]})
    win.productivity.add_todo("买牛奶")
    win.productivity.add_water(750)
    win.productivity.record_clip("剪贴板测试")
    win.productivity.add_shelf("/etc/hosts")
    win.set_mail({"status": "ok", "error": "", "at": "12:30", "items": [
        {"sender": "GitHub", "subject": "code 482913", "date": "12:20",
         "code": "482913", "preview": ""},
        {"sender": "王工", "subject": "本周评审", "date": "12:10",
         "code": "", "preview": "明天下午三点开会"}]})
    win.set_calendar({"status": "ok", "error": "", "at": "12:30", "items": []})
    win.set_quota({"providers": [
        {"id": "codex", "label": "Codex", "plan": "Free", "status": "ok",
         "error": "", "updated": 1_700_000_000,
         "metrics": [
             {"label": "30 天", "used": 0.74, "remaining": 0.26,
              "text": "26%", "kind": "percent", "reset": 1_800_000_000,
              "reset_text": "12月3日 09:15 重置"},
             {"label": "5 小时", "used": 0.2, "remaining": 0.8,
              "text": "80%", "kind": "percent", "reset": None,
              "reset_text": "等待刷新"}],
         "usage": {"today": 1_240_000, "sessions": 3},
         "note": "本机官方配额快照"},
        {"id": "claude", "label": "Claude", "plan": "本地记录",
         "status": "ok", "error": "", "updated": 1_700_000_000,
         "metrics": [
             {"label": "今日 Token", "used": 0.44, "remaining": 0.56,
              "text": "2.20M / 5M", "kind": "tokens", "reset": None,
              "reset_text": "预算回退"}],
         "usage": {"today": 2_200_000, "sessions": 4},
         "note": "未找到桌面版额度缓存"},
        {"id": "remote", "label": "远程", "plan": "通用 JSON",
         "status": "unconfigured", "error": "", "updated": 0,
         "metrics": [], "usage": None, "note": "未配置"}]})
    win.add_notification({"app": "微信", "summary": "在吗", "body": "",
                          "at": "12:28"})
    win.set_expanded(True, animate=False)
    assert win.open_shape.rect.height() == 140
    for page, _ in PAGES:
        win.set_page(page)
        pix = win.grab()
        assert not pix.isNull() and pix.width() > 0, page
        assert not win._tab_hits, page
        assert any(action == "nav" for _, action, _ in win._hits), page
        assert any(action == "page" for _, action, _ in win._hits), page
    pager = [rect for rect, action, _ in win._hits if action == "page"]
    assert len(pager) == len(PAGES)
    assert all(abs(rect.width() - 10) < 0.01 for rect in pager)
    win.cfg["show_monitor"] = False
    win.apply(win.cfg, win.theme)
    assert win.page == "music"
    win.set_page("monitor")
    assert win.page == "music"
    win.grab()
    pager = [rect for rect, action, _ in win._hits if action == "page"]
    assert len(pager) == len(PAGES) - 1
    win.cfg["show_monitor"] = True
    win.apply(win.cfg, win.theme)
    win.set_page("quota")
    win.grab()
    assert any(action == "quota_refresh" for _, action, _ in win._hits)
    assert any(action == "quota_pick" for _, action, _ in win._hits)
    win._do_action("quota_pick", "claude")
    assert win.quota_selected == "claude"
    win._do_action("quota_pick", "codex")
    win.set_activity({"provider": "Codex", "state": "responding",
                      "label": "正在回答", "detail": "正在修改窗口渲染",
                      "active": True, "at": time.time()})
    assert any(kind == "activity" for kind, _, _ in win._compact_parts(1.0))
    assert not win.grab().isNull()
    win.set_expanded(False, animate=False)
    win.grab()
    assert any(page == "quota" for _, page in win._compact_hits)
    win.set_activity({"provider": "Codex", "state": "completed",
                      "label": "任务完成", "detail": "已修改窗口渲染",
                      "active": False, "at": time.time()})
    assert win._activity_visible()
    assert not win.grab().isNull()
    win.set_activity({"provider": "Codex", "state": "completed",
                      "label": "任务完成", "detail": "旧任务",
                      "active": False, "at": time.time() - 3600})
    assert not win._activity_visible()
    win.set_expanded(True, animate=False)
    win.set_page("quota")
    assert not win.grab().isNull()
    win.set_page("tools")
    for tool in ("shelf", "clips", "notify"):
        win.set_tools_page(tool)
        assert not win.grab().isNull(), tool

    win.set_tools_page("clips")
    for index in range(7):
        win.productivity.record_clip(f"滚动剪贴 {index}")
    assert win._scroll_by("clips", 1, len(win.productivity.clips), 2)
    assert win._scroll["clips"] == 1
    assert not win.grab().isNull()
    win._scroll["clips"] = 0

    win.set_page("mail")
    win._do_action("mail_open", 1)
    assert win._mail_detail == 1
    assert not win.grab().isNull()
    win._do_action("mail_open", 0)
    assert win._mail_detail == 0
    assert not win.grab().isNull()
    win._do_action("mail_back", None)
    assert win._mail_detail is None

    win.set_page("tools")
    win.set_tools_page("shelf")
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/etc/hostname")])
    win.dragEnterEvent(QDragEnterEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert win.expanded and win.page == "tools" and win.tools_page == "shelf"
    assert win._drag_active
    win.dropEvent(QDropEvent(
        QPointF(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert "/etc/hostname" in win.productivity.shelf
    assert not win._drag_active

    win.set_page("music")
    win._do_action("nav", 1)
    assert win.page == "focus"
    win._do_action("nav", -1)
    assert win.page == "music"

    win.set_page("todo")
    win._do_action("todo_add")
    win.todo_input.setText("写周报")
    win._todo_submit()
    assert win.productivity.todos[0]["text"] == "写周报"
    win._do_action("todo_edit")
    assert win._todo_choosing
    win._do_action("todo_pick", 0)
    assert win._todo_editing == 0
    win.todo_input.setText("写日报")
    win._do_action("todo_repeat", 0)
    win._do_action("todo_save")
    assert win.productivity.todos[0]["text"] == "写日报"
    assert win.productivity.todos[0]["repeat"] == [0]
    win.set_page("water")
    before = win.productivity.water_ml
    win._do_action("water", 250)
    assert win.productivity.water_ml == before + 250
    win.set_page("focus")
    win._do_action("focus_toggle")
    assert win.focus["running"] is True
    win._do_action("focus_toggle")
    assert win.focus["running"] is False
    win.set_click_through(True)
    win.set_click_through(False)
    win._hovered = True
    win._inside = lambda: False
    win.set_expanded(True, animate=False)
    win._poll_hover()
    assert win._leaving.isActive()
    win._inside = lambda: True
    win._poll_hover()
    assert not win._leaving.isActive()
    win.set_expanded(False, animate=False)

    t = theme.load("classic")
    for mood in ("awake", "music", "focus", "happy"):
        image = QImage(24, 24, QImage.Format_ARGB32)
        image.fill(t.color("surface"))
        p = QPainter(image)
        render.paint_pet(p, 3, 12, 18, t, mood, 1.0)
        p.end()
        assert any(image.pixelColor(x, y).name() != t.color("surface").name()
                   for x in range(24) for y in range(24)), mood
    win.close()
    win.deleteLater()


def check_scroll_areas() -> None:
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_expanded(True, animate=False)
    win.set_mail({"status": "ok", "error": "", "at": "12:30", "items": [
        {"sender": "a", "subject": f"s{i}", "date": "", "code": "",
         "preview": ""} for i in range(8)]})
    win.set_page("mail")
    win.grab()
    assert win._list_rect is not None

    def wheel(point, dy=-120):
        pos = QPointF(point.x() - win._window_rect.left(),
                      point.y() - win._window_rect.top())
        win.wheelEvent(QWheelEvent(pos, pos, QPoint(), QPoint(0, dy),
                                   Qt.NoButton, Qt.NoModifier,
                                   Qt.NoScrollPhase, False))

    wheel(win._list_rect.center())
    assert win._scroll["mail"] == 1 and win.page == "mail"
    wheel(QPointF(2, 2))
    assert win.page == "quota"

    win.set_page("tools")
    win.set_tools_page("clips")
    for index in range(6):
        win.productivity.record_clip(f"滚动区域 {index}")
    win.grab()
    wheel(win._list_rect.center())
    assert win._scroll["clips"] == 1 and win.page == "tools"
    wheel(QPointF(2, 2))
    assert win.page == "todo"
    win.close()
    win.deleteLater()


def check_settings_dialog() -> None:
    from island.settings_window import SettingsDialog

    class FakeApp:
        def __init__(self):
            self.cfg = dict(config.DEFAULTS)
            self.theme_ids = theme.list_themes()
            self.themes = {tid: theme.load(tid) for tid in self.theme_ids}

        def set_theme(self, value):
            self.cfg["theme"] = value

        def set_style(self, value):
            self.cfg["style"] = value

        def set_option(self, key, value):
            self.cfg[key] = value

        def set_weather_city(self, value):
            pass

        def set_autostart(self, value):
            pass

        def update_config(self, values):
            self.cfg.update(values)

    dialog = SettingsDialog(FakeApp())
    assert dialog.windowType() == Qt.Window
    dialog.select_tab("mail")
    assert dialog.tabs.currentIndex() == 2
    dialog.select_tab("unknown")
    assert dialog.tabs.currentIndex() == 0
    dialog.show()
    assert not dialog.grab().isNull()
    assert dialog.material_box.isHidden()
    dialog.theme.setCurrentIndex(dialog.theme.findData("glass-dark"))
    assert not dialog.material_box.isHidden()
    dialog.theme.showPopup()
    popup = dialog.theme.view().window()
    assert "border: 0px" in popup.styleSheet()
    image = popup.grab().toImage()
    for x, y in ((1, 1), (image.width() - 2, 1),
                 (1, image.height() - 2),
                 (image.width() - 2, image.height() - 2)):
        assert image.pixelColor(x, y).lightness() < 120, (x, y)
    dialog.theme.hidePopup()
    dialog._mail_result({"status": "ok", "at": "12:30", "unread": 3})
    assert dialog.mail_status.text() == "已连接 12:30 · 3 封未读"
    assert not dialog.mail_status.isHidden()
    dialog._calendar_result({"status": "error", "error": "网络中断"})
    assert dialog.calendar_status.text() == "读取失败：网络中断"

    class FakeQuota(QObject):
        updated = Signal(dict)

    thread = FakeQuota()
    dialog.watch_quota(thread)
    thread.updated.emit({"at": "12:31", "providers": [
        {"label": "Codex", "status": "ok"},
        {"label": "Claude", "status": "ok"}]})
    assert dialog.quota_status.text() == "已刷新 12:31 · Codex、Claude"
    thread.updated.emit({"at": "12:32", "providers": [
        {"label": "Codex", "status": "error", "error": "网络中断"}]})
    assert dialog.quota_status.text() == "刷新完成 12:32 · Codex 失败：网络中断"
    dialog.close()
    dialog.deleteLater()


def check_monitor_off() -> None:
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.data.update(cpu=0.5, memory=0.6, disk=0.7, temperature=60,
                    gpu={"util": 0.3}, net_down=1.0, net_up=2.0,
                    online=True)
    win.set_page("monitor")
    win.cfg["show_monitor"] = False
    win.apply(win.cfg, win.theme)
    assert win.page == "music"
    assert all(kind not in ("cpu", "mem")
               for kind, _, _ in win._compact_parts(1.0))
    assert all(win.data[key] is None for key in (
        "cpu", "memory", "disk", "temperature", "gpu", "net_down",
        "net_up", "online"))
    win.close()
    win.deleteLater()

    names = ("read_memory", "read_cpu", "read_disk", "read_temperature",
             "read_gpu", "read_net", "read_network", "read_battery",
             "read_volume", "read_muted")
    saved = {name: getattr(sources, name) for name in names}

    def fail(*_args):
        raise AssertionError("monitor data sampled while disabled")

    try:
        for name in names[:7]:
            setattr(sources, name, fail)
        sources.read_battery = lambda: (None, False)
        sources.read_volume = lambda: None
        sources.read_muted = lambda: False
        data = sources.Sampler(monitor_enabled=False).sample()
    finally:
        for name, func in saved.items():
            setattr(sources, name, func)
    assert data["cpu"] is None and data["memory"] is None
    assert data["online"] is None and data["battery"] is None


def check_line_status() -> None:
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    assert win._line_status() == (0.38, "accent")
    win.focus.update(running=True, total=100, remaining=25)
    assert win._line_status() == (0.75, "accent")
    win.focus["running"] = False
    win._focus_done = True
    assert win._line_status() == (1.0, "success")
    win._focus_done = False
    win.music = {"title": "Track", "status": "Playing",
                 "position": 30, "length": 120}
    assert win._line_status() == (0.25, "accent")
    win.music["status"] = "Paused"
    assert win._line_status() == (0.25, "equalizer")
    win.music = None
    win.data.update(cpu=0.85, memory=0.2, disk=0.1)
    assert win._line_status() == (0.85, "warning")
    win.cfg["show_monitor"] = False
    assert win._line_status() == (0.38, "accent")
    win.close()
    win.deleteLater()


def check_tray_labels() -> None:
    from island.tray import Tray

    class FakeApp:
        cfg = dict(config.DEFAULTS)

        def set_theme(self, value):
            pass

        def set_style(self, value):
            pass

        def set_option(self, key, value):
            pass

        def set_autostart(self, value):
            pass

        def quit(self):
            pass

    ids = theme.list_themes()
    themes = {theme_id: theme.load(theme_id) for theme_id in ids}
    tray = Tray(FakeApp(), themes, lambda: None)
    assert [action.text() for action in tray.theme_menu.actions()] == [
        themes[theme_id].name for theme_id in ids]
    tray.tray.hide()


def main() -> int:
    app = QApplication(sys.argv[:1])
    check_ring_gauge()
    check_music_states()
    check_seek_drag()
    check_lyrics_motion()
    check_mail_timeout()
    check_mail_badge()
    check_compact_width()
    check_compact_motion()
    check_reminders()
    check_notice_pet_clip()
    check_refresh_feedback()
    check_clock_text()
    check_weather_slot()
    check_lyric_wrap()
    check_shelf_press()
    check_pages()
    check_scroll_areas()
    check_settings_dialog()
    check_monitor_off()
    check_line_status()
    check_tray_labels()
    cfg = dict(config.DEFAULTS)
    cell_w, cell_h = 470, 174
    styles = ["notch", "capsule", "line"]
    ids = theme.list_themes()

    failures = []
    for style in styles:
        for theme_id in ids:
            cfg["style"] = style
            cfg["theme"] = theme_id
            win = IslandWindow(dict(cfg), theme.load(theme_id))
            win.set_data({"battery": 0.82, "charging": False, "volume": 0.46,
                          "memory": 0.37, "cpu": 0.23, "net_down": 1_240_000,
                          "net_up": 320_000, "online": True,
                          "weather": {"temp": 12, "text": "多云", "place": "北京"}})
            win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                           "position": 42, "length": 215, "art_path": ""})
            win.set_expanded(True, animate=False)
            pix = win.grab()
            if pix.isNull() or pix.width() == 0:
                failures.append(f"{style}/{theme_id}")
                continue
            if pix.width() > cell_w - 8 or pix.height() > cell_h - 8:
                failures.append(f"{style}/{theme_id} {pix.width()}x{pix.height()}")
                continue
            win.close()
            win.deleteLater()

    if failures:
        print("FAIL:", ", ".join(failures))
        return 1
    print("OK: 15 widget combinations rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
