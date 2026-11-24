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
                            QRect, QUrl, Qt, Signal)  # noqa: E402
from PySide2.QtGui import (QDragEnterEvent, QDropEvent, QImage,
                           QGuiApplication, QMouseEvent, QPainter,
                           QWheelEvent)  # noqa: E402
from PySide2.QtWidgets import QApplication  # noqa: E402

from island import config, render, sources, theme  # noqa: E402
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
            if expanded and state is None:
                assert any(action == "music_volume"
                           for _, action, _ in win._hits)
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


def _battery_crop(win):
    """The battery gauge body, cropped out of a grab."""
    scale = win.base.scale
    body_w = int((render.BATTERY_W - 3.2) * scale)
    body_h = int(render.BATTERY_H * scale)
    left = int(win.shape.rect.right() - win.base.inset
               - render.BATTERY_W * scale - win._window_rect.left())
    top = int(win.shape.rect.center().y() - body_h / 2 - win._window_rect.top())
    return win.grab().toImage().copy(QRect(left, top, body_w, body_h))


def _crop_pixels(image):
    return (image.pixelColor(x, y) for x in range(image.width())
            for y in range(image.height()))


def check_battery_slot() -> None:
    """The percent sits inside the gauge, so digit count cannot reflow the pill."""
    widths = []
    for level in (0.09, 0.68, 1.0):
        win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
        win.set_data({"battery": level, "charging": False, "volume": 0.5,
                      "cpu": 0.2, "memory": 0.3})
        win.grab()
        widths.append(win.shape.rect.width())
        win.close()
        win.deleteLater()
    assert widths[0] == widths[1] == widths[2], widths

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": 0.68, "charging": False})
    pixels = list(_crop_pixels(_battery_crop(win)))
    assert any(c.red() > 200 and c.green() > 200 and c.blue() > 200
               for c in pixels), "no digits inside the gauge"
    win.set_data({"battery": 0.68, "charging": True})
    pixels = list(_crop_pixels(_battery_crop(win)))
    assert any(c.green() > c.red() + 40 and c.green() > c.blue() + 40
               for c in pixels), "charging is not green"
    win.set_data({"battery": 0.05, "charging": False})
    pixels = list(_crop_pixels(_battery_crop(win)))
    assert any(c.red() > c.green() + 40 and c.red() > c.blue() + 40
               for c in pixels), "low battery is not red"
    win.close()
    win.deleteLater()

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": None})
    win.grab()
    assert not any(action == "battery" for _, action in win._compact_hits)
    win.close()
    win.deleteLater()

    wide = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    wide.set_data({"battery": 0.68, "charging": False})
    wide_width = wide.base.rect.width()
    hidden = IslandWindow(dict(config.DEFAULTS, show_battery=False),
                          theme.load("classic"))
    hidden.set_data({"battery": 0.68, "charging": False})
    hidden.grab()
    assert hidden.base.rect.width() < wide_width
    assert not any(action == "battery" for _, action in hidden._compact_hits)
    wide.close()
    wide.deleteLater()
    hidden.close()
    hidden.deleteLater()


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


def check_meeting_offer() -> None:
    from datetime import datetime, timedelta

    soon = datetime.now() + timedelta(days=2)
    invite = (f"温建春 邀请您参加腾讯会议\n会议主题：交付评审\n"
              f"会议时间：{soon:%Y/%m/%d} 09:20-09:50\n"
              "#腾讯会议：902-631-704")

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    before = len(win.productivity.todos)
    assert win.offer_meeting(invite)
    assert win._notice and win._notice["kind"] == "meeting"
    assert not win.offer_meeting(invite)
    assert win.productivity.record_clip(invite)
    assert win._content_width() <= win._compact_capacity(1.0) + 0.01
    win.grab()

    win._notice_until = time.monotonic() - 1
    win._show_next_notice(force=True)
    assert win._notice is None
    kinds = [part[0] for part in win._compact_parts(1.0)]
    assert "meeting" in kinds, kinds

    win.set_page("todo")
    win.set_expanded(True, animate=False)
    win.grab()
    assert any(action == "meeting_accept" for _, action, _ in win._hits)
    open_today = win.productivity.progress()[1]
    win._do_action("meeting_accept", None)
    assert win._meeting_offer is None and win._notice is None
    assert len(win.productivity.todos) == before + 1
    assert win.productivity.todos[0]["text"].endswith("交付评审")
    assert win.productivity.todos[0]["remind_on"] == soon.date().isoformat(), \
        "非当天的会议要带日期，别混进今日待办"
    assert win.productivity.progress()[1] == open_today, "后天的会议不计今日"
    win.grab()
    # 非当天的 dated 待办不能因为“今天不该做”就勾不掉
    solo = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    solo.productivity.add_todo("11/22 09:20 后天的评审", None, "09:20",
                               soon.date().isoformat())
    solo.set_page("todo")
    solo.set_expanded(True, animate=False)
    solo.grab()
    assert any(action == "todo_toggle" and arg == 0
               for _, action, arg in solo._hits), solo._hits

    # 当天会议会响铃一次、非当天不计今日：这两条在 test_core 里用固定日期断言

    win.offer_meeting(f"会议主题：备份沟通\n"
                      f"会议时间：{soon:%Y/%m/%d} 17:00-17:45\n"
                      "#腾讯会议：370-268-672")
    win._do_action("meeting_reject", None)
    assert win._meeting_offer is None and len(win.productivity.todos) == before + 1
    assert win.offer_meeting(invite), "重新复制同一条要再问一次"
    win._do_action("meeting_reject", None)

    win.offer_meeting(f"会议主题：过期不再问\n会议时间：{soon:%Y/%m/%d} 10:00")
    win._meeting_offer["until"] = time.monotonic() - 1
    win._tick()
    assert win._meeting_offer is None
    assert "meeting" not in [part[0] for part in win._compact_parts(1.0)]

    off = IslandWindow(dict(config.DEFAULTS, meeting_detect=False),
                       theme.load("classic"))
    assert not off.offer_meeting(invite)
    assert off._notice is None and off._meeting_offer is None


def check_stock_session_chip() -> None:
    quote = {"status": "ok", "code": "sh000001", "name": "上证指数",
             "price": 3577.62, "prev_close": 3587.83, "change": -10.21,
             "change_pct": -0.28, "high": 3584.28, "low": 3547.94,
             "date": "20261119", "at": "16:14", "points": []}
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": 0.8, "cpu": 0.2, "memory": 0.3})
    win.set_stock(dict(quote))

    win._stock_chip_visible = lambda: True
    win._stock_shown = True
    assert "stock" in [part[0] for part in win._compact_parts(1.0)]
    wide = win._content_width()

    win._stock_chip_visible = lambda: False
    win._tick()
    assert not win._stock_shown
    assert "stock" not in [part[0] for part in win._compact_parts(1.0)]
    assert win._content_width() < wide

    win._tick()
    assert win._content_width() < wide

    win._stock_chip_visible = lambda: True
    win._tick()
    assert win._stock_shown and win._content_width() == wide

    real = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    real.set_stock(dict(quote, date="20261116"))
    assert not real._stock_chip_visible(), "收盘宽限后应隐藏"
    real.set_stock(dict(quote, date="20261113"))
    assert not real._stock_chip_visible(), "行情日期不是今天应隐藏"
    off = IslandWindow(dict(config.DEFAULTS, stock_hide_closed=False),
                       theme.load("classic"))
    off.set_stock(dict(quote, date="20261113"))
    assert off._stock_chip_visible(), "关掉开关后不隐藏"

    hidden = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    hidden.set_stock(dict(quote))
    hidden._stock_shown = False
    hidden.set_page("stock")
    hidden.set_expanded(True, animate=False)
    hidden.grab()
    assert any("休市" in text for text in _painted_text(hidden))


def _painted_text(win):
    import island.window as window_module

    seen = []
    original = window_module.render.paint_text

    def spy(painter, rect, text, *args, **kwargs):
        seen.append(str(text))
        return original(painter, rect, text, *args, **kwargs)

    window_module.render.paint_text = spy
    try:
        win.grab()
    finally:
        window_module.render.paint_text = original
    return seen




def check_todo_dot_needs_confirm() -> None:
    """询问未确认时，待办页码豆上要亮提醒点（和喝水待确认一致）。"""
    from datetime import datetime, timedelta

    soon = datetime.now() + timedelta(days=2)
    invite = (f"会议主题：交付评审\n会议时间：{soon:%Y/%m/%d} 09:20-09:50")
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    accent = win.theme.color("accent").name()

    def todo_dot():
        # 停在别的页取样，否则待办自己的当前页豆豆本来就是强调色
        win.set_page("music")
        win.set_expanded(True, animate=False)
        image = win.grab().toImage()
        ox, oy = win._window_origin()
        rect = next(rect for rect, action, arg in win._hits
                    if action == "page" and arg == "todo")
        return image.pixelColor(int(rect.center().x()) - ox,
                                int(rect.center().y() - 7) - oy).name()

    assert todo_dot() != accent, "没有待确认时不该亮"
    assert win.offer_meeting(invite)
    assert todo_dot() == accent, "询问中要点亮待办豆豆"
    win._resolve_meeting(False)
    assert todo_dot() != accent, "确认后该熄灭"

    win.offer_meeting(invite)
    assert todo_dot() == accent
    win._meeting_offer["until"] = time.monotonic() - 1
    win._tick()
    assert todo_dot() != accent, "超时后也该熄灭"

    off = IslandWindow(dict(config.DEFAULTS, meeting_detect=False),
                       theme.load("classic"))
    assert not off.offer_meeting(invite)
    assert off._meeting_offer is None


def check_todo_meeting_detail() -> None:
    from datetime import datetime, timedelta

    soon = datetime.now() + timedelta(days=2)
    invite = ("温建春 邀请您参加腾讯会议\n会议主题：交付评审\n"
              f"会议时间：{soon:%Y/%m/%d} 09:20-09:50\n"
              "https://meeting.tencent.com/dm/abc123\n"
              "#腾讯会议：902-631-704\n会议地点：3 楼 302 会议室")
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_data({"battery": 0.8, "cpu": 0.2, "memory": 0.3})
    win.productivity.add_todo("买牛奶")
    win.offer_meeting(invite)
    win.set_page("todo")
    win.set_expanded(True, animate=False)
    win._do_action("meeting_accept", None)
    index = 0
    assert win.productivity.todos[index]["meeting"]["place"] == "3 楼 302 会议室"

    win.grab()
    hits = [(action, arg) for _, action, arg in win._hits]
    assert ("todo_detail", index) in hits, hits
    assert ("todo_toggle", index) in hits, hits
    assert ("todo_detail", 1) not in hits, "普通待办不该有详情入口"

    win._do_action("todo_detail", index)
    win.grab()
    assert any(action == "copy" and arg == "902631704"
               for _, action, arg in win._hits)
    assert any(action == "copy" and arg.endswith("abc123")
               for _, action, arg in win._hits)
    assert any(action == "todo_toggle" and arg == index for _, action, arg
               in win._hits), "详情页要能直接勾完成"
    win._do_action("copy", "902631704")
    assert QApplication.clipboard().text() == "902631704"
    win._do_action("todo_toggle", index)
    assert win.productivity.todos[index]["done"]
    win._do_action("todo_toggle", index)

    win._do_action("todo_back", None)
    assert win._todo_detail is None
    win._do_action("todo_detail", index)
    win._do_action("todo_remove", index)
    assert win._todo_detail is None, "删掉后不能继续显示详情"
    win.grab()

    # 到点横幅点开就是详情
    now = datetime.now()
    win.offer_meeting(f"会议主题：今天的对齐\n会议时间：{now:%Y/%m/%d} 09:00")
    win._do_action("meeting_accept", None)
    item = win.productivity.todos[0]
    item["remind"] = now.strftime("%H:%M")
    item["remind_on"] = now.date().isoformat()
    win._notice = None
    win._alerts = []
    win._todo_remind_day = (now - timedelta(days=1)).date().isoformat()
    win._todo_reminder_tick()
    assert win._notice and win._notice["kind"] == "todo"
    win._open_notice()
    assert win._todo_detail == 0, "点横幅要直接看到会议号"
    assert not win._alerts, "横幅不应重复排队"


def check_tools_default_subpage() -> None:
    """空置物架不值得占默认位，进 tools 先看剪贴。"""
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_expanded(True, animate=False)
    win.productivity.clear_shelf()
    win.productivity.clips = []
    win.productivity.record_clip("剪贴优先")
    assert not win.productivity.shelf
    win.set_page("music")
    win.set_page("tools")
    assert win.tools_page == "clips", win.tools_page
    assert not win.grab().isNull()

    # 显式点置物标签仍然去置物，空状态要能拖文件进去
    win.set_tools_page("shelf")
    assert win.tools_page == "shelf"
    win.grab()
    assert any(action == "shelf_add" for _, action, _ in win._hits)

    win.productivity.add_shelf("/etc/hosts")
    win.set_tools_page("shelf")
    win.set_page("music")
    win.set_page("tools")
    assert win.tools_page == "shelf", "有置物就该优先显示置物"

    # 拖文件进来是明确意图，不能被改写
    win.set_page("music")
    win.productivity.clear_shelf()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("/etc/hostname")])
    win.dragEnterEvent(QDragEnterEvent(
        QPoint(10, 10), Qt.CopyAction, mime, Qt.LeftButton, Qt.NoModifier))
    assert win.tools_page == "shelf", win.tools_page

    # 两边都空时留在置物架，那里有拖拽提示可看
    win.productivity.clips = []
    win.set_page("music")
    win.set_page("tools")
    assert win.tools_page == "shelf", win.tools_page
    win.close()


def check_tools_notify_dot() -> None:
    """页码豆亮起来就该能看出是通知，而不是挨个标签翻。"""
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_expanded(True, animate=False)
    win.productivity.record_clip("一条剪贴")
    danger = win.theme.color("danger").name()

    def paint():
        win._page_at = time.monotonic() - 1  # 翻页位移结束后再取样
        return win.grab().toImage()

    def sample(image, rect, dx=0.0, dy=0.0):
        ox, oy = win._window_origin()
        return image.pixelColor(int(rect.center().x() + dx) - ox,
                                int(rect.center().y() + dy) - oy).name()

    def page_dot():
        win.set_page("music")
        win.set_expanded(True, animate=False)
        image = paint()
        rect = next(rect for rect, action, arg in win._hits
                    if action == "page" and arg == "tools")
        return sample(image, rect, dy=-7)

    def notify_tab_dot():
        image = paint()
        rect = next(rect for rect, action, arg in win._tools_hits
                    if action == "tools" and arg == "notify")
        return sample(image, rect, dx=rect.width() / 2 - 6)

    assert page_dot() != danger, "没通知时页码豆不该亮红点"
    win.set_page("tools")
    win.set_tools_page("shelf")
    assert notify_tab_dot() != danger
    assert page_dot() != danger

    win.set_page("music")
    win.add_notification({"app": "系统", "summary": "更新完成",
                          "body": "", "at": "10:00"})
    assert win._unread == 1
    assert page_dot() == danger, "新通知要点亮 tools 页码豆"

    win.set_page("tools")
    assert win.tools_page == "notify", "亮着就该直接落到通知"
    assert win._unread == 0, "看过通知后豆豆要熄灭"
    assert notify_tab_dot() != danger
    assert page_dot() != danger

    # 停在置物架时来通知，当前页上就要立刻看出是哪个标签
    win.set_page("tools")
    win.set_tools_page("shelf")
    win.add_notification({"app": "系统", "summary": "另一条",
                          "body": "", "at": "10:01"})
    assert win.tools_page == "shelf", "不该把用户从当前标签拽走"
    assert notify_tab_dot() == danger, "通知标签上要有点"
    win.set_tools_page("notify")
    assert win._unread == 0
    assert notify_tab_dot() != danger
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


def check_mail_flag_feedback() -> None:
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.cfg["mail_sync_operations"] = True
    sent = []
    win.mail_action.connect(lambda action, uid: sent.append((action, uid)))
    item = {"sender": "a@x.com", "subject": "登录邮件", "date": "10:00",
            "uid": "7", "seen": True, "code": "", "body": "hi"}
    win.set_mail({"status": "ok", "error": "", "unread": 0,
                  "items": [dict(item)]})
    win.set_page("mail")
    win.set_expanded(True, animate=False)
    win._do_action("mail_open", 0)
    assert not win._mail_unread(win.mail["items"][0])
    win._do_action("mail_unread")
    assert sent == [("unseen", "7")], sent
    # 点完立刻按未读显示，不等服务器回包
    assert win._mail_unread(win.mail["items"][0])
    # 服务器拒绝：回到真实状态，人留在详情页好重试
    win.set_mail_operation({"status": "error",
                            "error": "服务器未接受已读状态修改"})
    assert not win._mail_unread(win.mail["items"][0])
    assert win._mail_detail == 0
    # 服务器接受：状态落到缓存，刷新回来前不闪回
    win._do_action("mail_unread")
    win.set_mail_operation({"status": "ok", "message": "已同步未读状态"})
    assert win._mail_unread(win.mail["items"][0])
    assert win.mail["items"][0]["seen"] is False
    # 验证码卡片优先：状态要么完整、要么短词，不能截成“已同…”
    import island.window as window_module

    texts = []
    original_paint_text = window_module.render.paint_text

    def spy(painter, rect, text, *args, **kwargs):
        texts.append(str(text))
        return original_paint_text(painter, rect, text, *args, **kwargs)

    card = {"sender": "Microsoft", "subject": "安全代码", "date": "17:37",
            "uid": "9", "seen": False, "code": "262432", "body": "hi"}
    win._mail_detail = None
    win.set_mail({"status": "ok", "error": "", "unread": 2,
                  "items": [card, dict(item)]})
    window_module.render.paint_text = spy
    try:
        win.grab()
    finally:
        window_module.render.paint_text = original_paint_text
    assert "262432" in texts, texts
    assert "已同步" in texts, texts
    assert "全部 2" in texts and "未读 1" in texts, texts
    assert not any("已同…" in t for t in texts), texts
    # 报错时借整行显示完整原因，卡片仍然在
    win._mail_op_message = "服务器未接受已读状态修改"
    win._mail_op_token = "danger"
    win._mail_op_until = time.monotonic() + 60
    texts.clear()
    window_module.render.paint_text = spy
    try:
        win.grab()
    finally:
        window_module.render.paint_text = original_paint_text
    assert "服务器未接受已读状态修改" in texts, texts
    assert "262432" in texts, texts
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
                  "weather": {"temp": 13, "text": "小雨", "place": "长沙",
                              "region": "湖南", "feels": 11, "humidity": 78,
                              "wind": 9, "high": 16, "low": 9,
                              "daily": [
                                  {"date": f"2026-11-{19 + i:02d}",
                                   "text": "小雨", "kind": "rain",
                                   "high": 16 - i, "low": 8 + i,
                                   "precip": 10 * i} for i in range(7)]}})
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
    win.set_stock({"status": "ok", "code": "sh000001", "name": "上证指数",
                   "price": 3587.83, "prev_close": 3584.58, "change": 3.25,
                   "change_pct": 0.09, "high": 3596.55, "low": 3560.45,
                   "at": "16:15",
                   "points": [["0930", 3596.55], ["1000", 3580.12],
                              ["1130", 3560.45], ["1400", 3590.20],
                              ["1500", 3587.83]]})
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
    win.grab()
    pager = [rect for rect, action, _ in win._hits if action == "page"]
    assert len(pager) == len(PAGES), "monitor page stays when the slot is off"
    win.cfg["show_monitor"] = True
    win.apply(win.cfg, win.theme)
    win.set_page("quota")
    win.grab()
    assert any(action == "quota_refresh" for _, action, _ in win._hits)
    assert any(action == "quota_pick" for _, action, _ in win._hits)
    win._do_action("quota_pick", "claude")
    assert win.quota_selected == "claude"
    win._do_action("quota_pick", "codex")
    win.set_page("stock")
    assert not win.grab().isNull()
    assert any(action == "stock_refresh" for _, action, _ in win._hits)
    called = []
    win.stock_refresh = lambda: called.append(True)
    win._do_action("stock_refresh")
    assert called
    win.set_stock({"status": "error", "code": "sh000001",
                   "error": "网络中断", "points": []})
    assert not win.grab().isNull()
    win.set_stock({"status": "ok", "code": "sh000001", "name": "上证指数",
                   "price": 3587.83, "prev_close": 3584.58, "change": 3.25,
                   "change_pct": 0.09, "high": 3596.55, "low": 3560.45,
                   "at": "16:15",
                   "points": [["0930", 3596.55], ["1000", 3580.12],
                              ["1500", 3587.83]]})
    # 收起态涨跌格只在交易时段显示，这里关掉开关，让后面的槽位断言与时间无关
    win.cfg["stock_hide_closed"] = False
    win.apply(win.cfg, win.theme)
    win.set_activity({"provider": "Codex", "state": "responding",
                      "label": "正在回答", "detail": "正在修改窗口渲染",
                      "active": True, "at": time.time()})
    assert any(kind == "activity" for kind, _, _ in win._compact_parts(1.0))
    assert not win.grab().isNull()
    win.set_expanded(False, animate=False)
    win.grab()
    assert any(page == "quota" for _, page in win._compact_hits)
    assert any(page == "stock" for _, page in win._compact_hits)
    assert any(kind == "stock" for kind, _, _ in win._compact_parts(1.0))
    win.set_activity({"provider": "Codex", "state": "completed",
                      "label": "任务完成", "detail": "已修改窗口渲染",
                      "active": False, "at": time.time()})
    assert win._activity_visible()
    assert not win.grab().isNull()
    assert any(kind == "activity" for kind, _, _ in win._compact_parts(1.0))
    win.cfg["show_activity"] = False      # feature off: pill slot and quota line
    win.grab()
    assert not win._activity_visible()
    assert not any(kind == "activity" for kind, _, _ in win._compact_parts(1.0))
    win.set_expanded(True, animate=False)
    win.set_page("quota")
    assert not win.grab().isNull()
    win.set_expanded(False, animate=False)
    win.cfg["show_activity"] = True
    win.clear_activity()
    assert not win._activity_visible()
    assert win.activity.get("state") == "idle"
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
    assert win.page == "weather"
    win._do_action("nav", -1)
    assert win.page == "music"

    win.set_page("todo")
    area = win._content_rect()
    card = win._todo_card_rect()
    win.grab()
    add = next(rect for rect, action, _ in win._hits if action == "todo_add")
    edit = next(rect for rect, action, _ in win._hits if action == "todo_edit")
    assert edit.left() == add.left() and edit.top() > add.bottom(), \
        "添加和改一下要上下排列"
    assert edit.bottom() <= area.bottom(), "下移后不能超出内容区"
    assert card.width() > area.width() * 0.7, "按钮腾出的宽度要给列表"
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
    from PySide2.QtGui import QColor

    from island.settings_window import (SettingsDialog, _blend, _body_color,
                                        _ink_on, _preview_stage)

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

        def set_weather_city(self, value, lat=None, lon=None):
            self.cfg.update({"weather_city": value, "weather_auto": False,
                             "weather_lat": lat, "weather_lon": lon})

        def set_weather_auto(self):
            self.cfg["weather_auto"] = True

        def set_stock_code(self, value):
            self.cfg["stock_code"] = value

        @property
        def active_theme(self):
            current = self.themes[self.cfg["theme"]]
            alpha = self.cfg.get("glass_alpha")
            if alpha is None or current.material.get("kind") != "glass":
                return current
            return current.with_alpha(alpha / 100.0)

        def set_autostart(self, value):
            pass

        def update_config(self, values):
            self.cfg.update(values)

    dialog = SettingsDialog(FakeApp())
    assert dialog.windowType() == Qt.Window
    # 预览底色必须和岛本身分得开，否则浅色皮肤下岛框融进背景
    for theme_id in dialog.app.theme_ids:
        th = dialog.app.themes[theme_id]
        for alpha in (None, 35, 100):
            shown = th if alpha is None else th.with_alpha(alpha / 100.0)
            stage = QColor(_preview_stage(shown))
            body = _blend(stage, _body_color(shown))
            assert theme.contrast(stage, body) >= 1.45, (theme_id, alpha)
    dialog.select_tab("mail")
    assert dialog.tabs.currentIndex() == 3
    dialog.select_tab("unknown")
    assert dialog.tabs.currentIndex() == 0
    dialog.show()
    assert not dialog.grab().isNull()
    # QSS 丢弃非整数 px，字号阶梯只能用整数；这里锁住实际渲染值。
    from PySide2.QtWidgets import QLabel
    steps = {name: {label.font().pixelSize()
                    for label in dialog.findChildren(QLabel)
                    if label.objectName() == name}
             for name in ("section", "hint")}
    assert steps == {"section": {11}, "hint": {11}}, steps
    # 开关改动要等后台线程回信号才反映到岛上，只抓一帧预览会停在旧样子
    dialog.weather_on.setChecked(False)
    assert "weather" not in [part[0]
                             for part in dialog._sample._compact_parts(1.0)]
    dialog.stock_on.setChecked(False)
    assert "stock" not in [part[0]
                           for part in dialog._sample._compact_parts(1.0)]
    dialog.stock_on.setChecked(True)
    dialog.weather_on.setChecked(True)
    assert "weather" in [part[0]
                         for part in dialog._sample._compact_parts(1.0)]
    assert not dialog.preview.pixmap().isNull()
    # 鼠标穿透开启后岛点不动，警告必须可见；关闭时不留常驻说明
    dialog.click_through.setChecked(True)
    assert "托盘" in dialog.click_through_warn.text()
    dialog.click_through.setChecked(False)
    assert not dialog.click_through_warn.text()
    # 主按钮文字压在强调色上要够读（12px 粗体按 WCAG 要 4.5:1）
    for theme_id in dialog.app.theme_ids:
        th = dialog.app.themes[theme_id]
        ink = _ink_on(th.color("accent"), th.color("onAccent"))
        assert theme.contrast(ink, th.color("accent")) >= 4.5, theme_id
    # 标签列定宽，否则切 tab 时整列会左右跳（卡片内另有内边距，不计入）
    from PySide2.QtWidgets import QFormLayout

    from island.settings_window import Form
    labels = []
    for index in range(dialog.tabs.count()):
        for form in dialog.tabs.widget(index).findChildren(Form):
            item = form.itemAt(0, QFormLayout.LabelRole)
            if item is not None and item.widget() is not None:
                labels.append(item.widget())
    assert labels, "每一页都该有表单"
    assert all(label.minimumWidth() == Form.LABEL_W for label in labels)
    dialog._weather_result(
        {"place": "北京", "temp": 12.4, "text": "多云"})
    assert dialog.weather_temp.text() == "12°"
    assert dialog.weather_state.text() == "已更新"
    dialog._weather_result(
        {"place": "北京", "temp": 12.4, "text": "多云",
         "stale": True, "error": "网络中断"})
    assert dialog.weather_state.text() == "离线 · 上次数据"
    assert "网络中断" in dialog.weather_note.text()
    dialog.city_search.setText("长沙")
    dialog._city_found("长沙", [{"name": "长沙", "region": "湖南",
                                 "lat": 28.2282, "lon": 112.9388}])
    assert dialog.city_results.count() == 1
    assert dialog.city_add.isEnabled()
    assert not dialog.city_result_row.isHidden()
    dialog._add_picked_city()
    assert dialog.city_result_row.isHidden()
    assert dialog.app.cfg["weather_saved"][-1]["name"] == "长沙"
    assert dialog.app.cfg["weather_lat"] == 28.2282
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
    dialog.stock_code.setText("600519")
    dialog._save_stock_code()
    assert dialog.stock_code.text() == "sh600519"
    assert dialog.stock_status.text() == "已保存 sh600519"
    assert dialog.stock_hide_closed.isChecked()
    assert dialog.stock_grace_minutes.value() == 15
    assert dialog.stock_grace_minutes.isEnabled()
    dialog.stock_grace_minutes.setValue(30)
    assert dialog.app.cfg["stock_grace_minutes"] == 30
    dialog.stock_hide_closed.setChecked(False)
    assert not dialog.stock_grace_minutes.isEnabled()
    assert dialog.app.cfg["stock_hide_closed"] is False

    # 玻璃透明度：跟随皮肤默认 / 改成自己的值 / 恢复默认
    dialog.theme.setCurrentIndex(dialog.theme.findData("glass-light"))
    assert dialog.material_box.isVisible()
    assert dialog.glass_alpha.value() == 62
    assert dialog.glass_alpha_value.text() == "62%"
    assert not dialog.glass_reset.isEnabled()
    dialog.glass_alpha.setValue(30)
    assert dialog.glass_alpha_value.text() == "30%"
    assert dialog.app.cfg["glass_alpha"] is None, "拖动中不该每像素写一次配置"
    dialog.glass_alpha.sliderReleased.emit()
    assert dialog.app.cfg["glass_alpha"] == 30
    assert dialog.app.active_theme.material["alpha"] == 0.30
    assert dialog.glass_reset.isEnabled()
    # 键盘/点击改值没有 sliderReleased，靠防抖定时器落盘
    dialog.glass_alpha.setValue(75)
    deadline = time.monotonic() + 1.0
    while (time.monotonic() < deadline
           and dialog.app.cfg["glass_alpha"] != 75):
        QApplication.processEvents()
        time.sleep(0.02)
    assert dialog.app.cfg["glass_alpha"] == 75, "防抖后必须落盘"
    dialog.glass_reset.click()
    assert dialog.app.cfg["glass_alpha"] is None
    assert dialog.glass_alpha.value() == 62
    assert dialog.app.active_theme.material["alpha"] == 0.62
    assert not dialog.glass_reset.isEnabled()
    dialog.theme.setCurrentIndex(dialog.theme.findData("classic"))
    assert not dialog.material_box.isVisible()
    dialog.theme.setCurrentIndex(dialog.theme.findData("glass-dark"))
    assert dialog.glass_alpha.value() == 58, "换皮肤要跟着该皮肤的默认值"
    dialog.theme.setCurrentIndex(dialog.theme.findData("glass-light"))
    dialog.glass_alpha.setValue(45)
    dialog.glass_alpha.sliderReleased.emit()
    dialog.theme.setCurrentIndex(dialog.theme.findData("classic"))
    dialog.theme.setCurrentIndex(dialog.theme.findData("glass-light"))
    assert dialog.glass_alpha.value() == 45, "共享设置要保留"

    def scroll(widget, dy=-120):
        point = QPointF(10, 10)
        global_point = QPointF(widget.mapTo(None, point.toPoint()))
        event = QWheelEvent(point, global_point, QPoint(), QPoint(0, dy),
                            Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase,
                            False)
        widget.wheelEvent(event)
        return event

    # 滚轮掠过数字框/下拉框：只翻页，不改值
    value_before = dialog.stock_grace_minutes.value()
    index_before = dialog.theme.currentIndex()
    dialog.resize(560, 300)
    page = dialog.tabs.widget(0)
    bar = page.verticalScrollBar()
    bar.setValue(0)
    assert bar.maximum() > 120, bar.maximum()
    event = scroll(dialog.stock_grace_minutes)
    assert event.isAccepted() and bar.value() > 0
    assert dialog.stock_grace_minutes.value() == value_before
    bar.setValue(0)
    assert scroll(dialog.theme).isAccepted() and bar.value() > 0
    assert dialog.theme.currentIndex() == index_before
    alpha_before = dialog.glass_alpha.value()
    bar.setValue(0)
    assert scroll(dialog.glass_alpha).isAccepted() and bar.value() > 0
    assert dialog.glass_alpha.value() == alpha_before, "滚轮掠过滑块不能改值"
    assert dialog.app.cfg["glass_alpha"] == alpha_before, "滑块滚轮不能写配置"

    # 误删行情代码后直接关框：不保存半成品，重新打开显示已保存的代码
    dialog.stock_code.setText("")
    dialog.close()
    dialog.show()
    assert dialog.stock_code.text() == "sh600519"
    assert dialog.app.cfg["stock_code"] == "sh600519"
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
    win.set_expanded(True, animate=False)
    win.set_page("monitor")
    win.cfg["show_monitor"] = False
    seen = []
    win.monitor_focus.connect(seen.append)
    win.apply(win.cfg, win.theme)
    assert win.page == "monitor", "the page stays reachable"
    assert win.expanded and seen[-1] is True, "open page keeps sampling"
    assert all(kind not in ("cpu", "mem")
               for kind, _, _ in win._compact_parts(1.0))
    assert win.data["cpu"] == 0.5, "readings are not wiped"
    win.set_expanded(False, animate=False)
    assert seen[-1] is False, "collapsed pill without slots stops sampling"
    win.set_expanded(True, animate=False)
    win.set_page("music")
    assert seen[-1] is True, "the idle music page shows the status cells"
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 42, "length": 215, "player": "x"})
    assert seen[-1] is False, "a playing track has no status cells"
    win.set_music(None)
    assert seen[-1] is True, "the idle music page shows the status cells"
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 42, "length": 215, "player": "x"})
    win.set_page("todo")
    win.set_page("music")
    assert seen[-1] is False, "still no strip while playing"
    win.set_music(None)
    win.set_page("music")
    assert seen[-1] is True
    win.cfg["show_monitor"] = True
    win.apply(win.cfg, win.theme)
    assert seen[-1] is True, "the collapsed slots need the readings back"
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


def check_button_ink_centered() -> None:
    """Button labels centre on their ink, not on the font line box."""
    from PySide2.QtCore import QRectF
    from PySide2.QtGui import QFont, QImage, QPainter

    t = theme.load("classic")
    ink = t.color("textSecondary")
    k = 10  # 10x size, so drift is readable at 0.1px of real size
    for text in ("刷新", "全部已读", "专注"):
        rect = QRectF(50, 100, 40 * k, 19 * k)
        image = QImage(600, 400, QImage.Format_ARGB32)
        image.fill(t.color("surface"))
        painter = QPainter(image)
        render.paint_button(painter, rect, text, t, px=9 * k)
        painter.end()
        rows = [y for y in range(400)
                if sum(abs(image.pixelColor(x, y).red() - ink.red()) +
                       abs(image.pixelColor(x, y).green() - ink.green()) +
                       abs(image.pixelColor(x, y).blue() - ink.blue()) < 30
                       for x in range(int(rect.left()), int(rect.right()))) > 3]
        drift = abs((min(rows) + max(rows)) / 2 - rect.center().y()) / k
        assert drift <= 0.15, (text, drift)


def check_mail_status_centered() -> None:
    """The short 同步中/已同步 status sits between the filters and 刷新."""
    import island.window as window_module

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_expanded(True, animate=False)
    win.set_page("mail")
    win.set_mail({"status": "ok", "error": "", "unread": 3, "items": [
        {"uid": "1", "sender": "a@x.com", "subject": "验证码 262432",
         "date": "10:00", "code": "262432", "seen": False},
        {"uid": "2", "sender": "b@x.com", "subject": "登录邮件",
         "date": "10:00", "code": "", "seen": False}]})
    win._mail_op_message = "正在同步已读…"
    win._mail_op_until = time.monotonic() + 15
    win._mail_op_token = "textTertiary"
    seen = []
    original = window_module.render.paint_text

    def spy(painter, rect, text, *args, **kwargs):
        seen.append((str(text), rect))
        return original(painter, rect, text, *args, **kwargs)

    window_module.render.paint_text = spy
    try:
        win.grab()
    finally:
        window_module.render.paint_text = original
    status = [rect for text, rect in seen if text == "同步中"]
    assert len(status) == 1, seen
    tabs = [rect for rect, action, _ in win._hits if action == "mail_filter"]
    refresh = [rect for rect, action, _ in win._hits
               if action == "mail_refresh"][0]
    assert tabs and refresh
    middle = (tabs[-1].right() + refresh.left()) / 2.0
    assert abs(status[0].center().x() - middle) <= 0.5, (status[0], middle)
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


def check_click_through_keeps_window() -> None:
    """穿透不能重建原生窗口：重建时改尺寸会丢，岛会被裁断。"""
    from island import x11

    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    win.set_expanded(True, animate=False)
    winid = int(win.winId())
    calls = []
    real_drop, real_clear = x11.drop_input_region, x11.clear_input_shape
    real_platform = QGuiApplication.platformName
    x11.drop_input_region = lambda wid: calls.append(("drop", wid)) or True
    x11.clear_input_shape = lambda wid: calls.append(("clear", wid)) or True
    QGuiApplication.platformName = staticmethod(lambda: "xcb")
    try:
        win.set_click_through(True)
        assert win.windowFlags() & Qt.WindowTransparentForInput == 0, \
            "穿透不能再走 Qt flag，它会销毁并重建原生窗口"
        assert int(win.winId()) == winid, "同一个 X 窗口，没有被重建"
        assert calls[-1] == ("drop", winid), calls
        width = win.width()
        win.set_click_through(False)
        assert calls[-1] == ("clear", winid), calls
        assert win.width() == width, "关闭穿透不能改变岛的大小"
        win.set_expanded(False, animate=False)
        QGuiApplication.platformName = staticmethod(lambda: "wayland")
        del calls[:]
        win.set_click_through(True)
        assert not calls, "非 X11 平台不碰 XShape"
        assert win._click_through
        win.set_click_through(False)
    finally:
        x11.drop_input_region, x11.clear_input_shape = real_drop, real_clear
        QGuiApplication.platformName = real_platform
    win.close()
    win.deleteLater()


def main() -> int:
    app = QApplication(sys.argv[:1])
    check_ring_gauge()
    check_music_states()
    check_battery_slot()
    check_seek_drag()
    check_lyrics_motion()
    check_mail_timeout()
    check_mail_badge()
    check_compact_width()
    check_compact_motion()
    check_reminders()
    check_meeting_offer()
    check_stock_session_chip()
    check_todo_meeting_detail()
    check_todo_dot_needs_confirm()
    check_tools_default_subpage()
    check_tools_notify_dot()
    check_notice_pet_clip()
    check_refresh_feedback()
    check_mail_flag_feedback()
    check_clock_text()
    check_weather_slot()
    check_lyric_wrap()
    check_shelf_press()
    check_pages()
    check_scroll_areas()
    check_settings_dialog()
    check_monitor_off()
    check_line_status()
    check_button_ink_centered()
    check_mail_status_centered()
    check_tray_labels()
    check_click_through_keeps_window()
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
