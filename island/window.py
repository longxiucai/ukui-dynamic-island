"""The island window: one surface morphing from the pill into the details panel."""
import math
import os
import re
import subprocess
import time
from datetime import datetime, timedelta

from PySide2.QtCore import (QEvent, QMimeData, QPoint, QPointF,
                            QRectF, Qt, QTimer, QUrl)
from PySide2.QtCore import Signal
from PySide2.QtGui import (QColor, QDrag, QFont, QCursor, QGuiApplication,
                           QFontMetricsF, QLinearGradient, QPainter, QPainterPath, QPen,
                           QPixmap)
from PySide2.QtWidgets import QFileDialog, QLineEdit, QWidget

from island import (blur, geometry, lyrics, mail, meeting, render, stock as
                    stock_module, weather, x11)
from island.mail_reader import MailReader
from island.motion import Spring
from island.music import format_time
from island.productivity import WATER_GOAL, Productivity, repeat_tag
from island.sources import format_rate, set_muted, set_volume


HOVER_INTENT = 200
LEAVE_DELAY = 140
OPEN_W, OPEN_H = (330.0, 0.70), (290.0, 0.74)
CLOSE = (620.0, 1.0)
CONTENT_GROW_W = (300.0, 0.70)
CONTENT_SHRINK_W = (560.0, 1.0)
SWELL_W, SWELL_H = 1.075, 1.13
LYRIC_FADE = 0.18
NOTICE_FADE = 0.16
NOTICE_SECONDS = 8.0
MEETING_OFFER_SECONDS = 60.0
WATER_HOURS = (9, 22)
MAIL_NEW_SECONDS = 600.0
WEEKDAYS_ZH = "一二三四五六日"
WEEKDAYS_EN = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS_EN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
             "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
PAGES = (("music", "音乐"), ("weather", "天气"), ("focus", "专注"),
         ("water", "健康"), ("tools", "置物架"), ("todo", "待办"),
         ("mail", "邮箱"), ("quota", "AI 额度"), ("stock", "股票"),
         ("calendar", "日程"), ("monitor", "监控"))
TOOLS = (("shelf", "置物"), ("clips", "剪贴"), ("notify", "通知"))
PAGE_TITLE = {
    "music": "音乐",
    "focus": "专注",
    "water": "喝水",
    "tools": "置物架",
    "todo": "待办",
    "mail": "邮箱",
    "quota": "额度",
    "stock": "股票",
    "weather": "天气",
    "calendar": "日程",
    "monitor": "监控",
}
ACTIVITY_HOLD = 20.0


def _quota_when(stamp):
    try:
        at = datetime.fromtimestamp(float(stamp))
    except (OSError, OverflowError, TypeError, ValueError):
        return ""
    now = datetime.now()
    if at.date() == now.date():
        return at.strftime("%H:%M 更新")
    return at.strftime("%m-%d 更新")


def _quota_token(used):
    if used >= 0.92:
        return "danger"
    if used >= 0.8:
        return "warning"
    return "accent"


def _cover_colors(title):
    digest = 1469598103934665603
    for byte in str(title or "").encode("utf-8"):
        digest = ((digest ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    palette = (("#FF5E62", "#FF9966"), ("#56CCF2", "#2F80ED"),
               ("#A855F7", "#EC4899"), ("#34D399", "#1078C8"),
               ("#FBBF24", "#EF4444"))
    return palette[digest % len(palette)]


def _meter_token(value):
    if value is None:
        return "textTertiary"
    if value >= 0.92:
        return "danger"
    return "warning" if value >= 0.8 else "textPrimary"


class IslandWindow(QWidget):
    music_command = Signal(str)
    music_seek = Signal(float)
    open_settings = Signal(str)
    option_change = Signal(str, object)
    monitor_focus = Signal(bool)
    mail_action = Signal(str, object)

    def __init__(self, cfg, theme):
        super().__init__()
        self.cfg = cfg
        self.theme = theme
        self.data = {"battery": None, "charging": False, "volume": None,
                     "memory": None, "cpu": None, "disk": None,
                     "temperature": None, "gpu": None,
                     "net_down": None, "net_up": None, "online": None,
                     "weather": None}
        self.sample_at = datetime.now()
        self.expanded = False
        self.base = None
        self.open_shape = None
        self.shape = None
        self.progress = 0.0
        self.music = None
        self.productivity = Productivity()
        self.focus = {"phase": "focus", "running": False, "remaining": 0,
                      "total": 0}
        self._focus_reset()
        self.page = "music"
        self.tools_page = "shelf"
        self.mail = {"status": "idle", "error": "", "items": [], "at": ""}
        self.calendar = {"status": "idle", "error": "", "items": [], "at": ""}
        self.quota = {"providers": [], "at": ""}
        self.quota_selected = ""
        self.quota_refresh = None
        self.stock = {"status": "loading", "code": self.cfg.get("stock_code", ""),
                      "points": []}
        self.stock_refresh = None
        self.activity = {"provider": "", "state": "idle", "label": "",
                         "detail": "", "active": False, "at": 0.0}
        self._activity_shown = False
        self._stock_shown = True
        self.notifications = []
        self._unread = 0
        self.notify_error = ""
        self._hits = []
        self._tab_hits = []
        self._tools_hits = []
        self._list_rect = None
        self._compact_hits = []
        self._drag_active = False
        self._wheel_acc = 0
        self._page_at = 0.0
        self._page_dir = 1
        self._mail_pulse_until = 0.0
        self._mail_refresh_until = 0.0
        self._calendar_refresh_until = 0.0
        self._quota_refresh_until = 0.0
        self._stock_refresh_until = 0.0
        self._last_mail_unread = 0
        self._mail_detail = None
        self._scroll = {"mail": 0, "clips": 0, "todo": 0}
        self._confirm = ("", 0.0)
        self._meeting_offer = None
        self._todo_detail = None
        self._copied_text = ""
        self._copy_until = 0.0
        self._pet_until = 0.0
        self._blur_ok = None
        self._fs_hidden = False
        self._todo_adding = False
        self._todo_editing = None
        self._todo_choosing = False
        self._todo_repeat = []
        self._todo_remind_day = datetime.now().date().isoformat()
        self._todo_reminded = {}
        self._cover_path = ""
        self._cover = None
        self._show_lyrics = True
        self._lyric_line = ""
        self._lyric_at = -10.0
        self._lyric_page_line = ""
        self._lyric_page_index = -1
        self._lyric_page_at = -10.0
        self._lyrics_on = False
        self._lyrics_at = -10.0
        self._alerts = []
        self._notice = None
        self._notice_at = -10.0
        self._notice_until = 0.0
        self._focus_done = False
        self._water_pending = False
        self._water_day = datetime.now().date().isoformat()
        self._water_due = time.monotonic() + self._water_interval()
        self._water_minutes_seen = self._water_interval()
        self._mail_seen = set()
        self._mail_seen_ready = False
        self._mail_new = {}
        self._mail_read = set()
        self._mail_hidden = set()
        self._mail_reader = None
        self._mail_filter = "all"
        self._mail_op_message = ""
        self._mail_op_until = 0.0
        self._mail_op_token = "textTertiary"
        self._mail_op_action = ""
        self._mail_op_key = None
        self._mail_pending_delete = ""
        self._marquee = {}
        self._drag_seek = None
        self._shelf_press = None
        self._shelf_dragging = False
        self._hovered = False
        self._click_through = False
        self._seek_preview = None
        self._seek_title = ""
        self._seek_at = 0.0
        self._volume_open = False
        self._volume_drag = False
        self._w = Spring(1.0, *OPEN_W)
        self._h = Spring(1.0, *OPEN_H)
        self._swell = Spring(0.0, 420.0, 0.8, epsilon=0.002)
        self._last_frame = 0.0

        self._intent = QTimer(self)
        self._intent.setSingleShot(True)
        self._intent.setInterval(HOVER_INTENT)
        self._intent.timeout.connect(self._maybe_expand)
        self._leaving = QTimer(self)
        self._leaving.setSingleShot(True)
        self._leaving.setInterval(LEAVE_DELAY)
        self._leaving.timeout.connect(self._maybe_collapse)
        self._hover = QTimer(self)
        self._hover.setInterval(200)
        self._hover.timeout.connect(self._poll_hover)
        self._hover.start()
        self._desktop_shown = False
        self._desk = QTimer(self)
        self._desk.setInterval(250)
        self._desk.timeout.connect(self._watch_desktop)
        if QGuiApplication.platformName() == "xcb":
            self._desk.start()
        self._frame = QTimer(self)
        self._frame.setInterval(16)
        self._frame.timeout.connect(self._advance)
        self._beat = QTimer(self)
        self._beat.setInterval(100)
        self._beat.timeout.connect(self.update)
        self._page_beat = QTimer(self)
        self._page_beat.setInterval(16)
        self._page_beat.timeout.connect(self._page_advance)

        self.setWindowTitle("UKUI 灵动岛")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
                            | Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.NoFocus)

        self.todo_input = QLineEdit(self)
        self.todo_input.setPlaceholderText("新的待办，回车添加")
        self.todo_input.returnPressed.connect(self._todo_submit)
        self.todo_input.hide()
        self.todo_time_input = QLineEdit(self)
        self.todo_time_input.setPlaceholderText("09:00（可空）")
        self.todo_time_input.returnPressed.connect(self._todo_submit)
        self.todo_input.installEventFilter(self)
        self.todo_time_input.installEventFilter(self)
        self.todo_time_input.hide()
        self.clock = QTimer(self)
        self.clock.timeout.connect(self._tick)
        self.clock.start(1000)
        self._apply_geometry()

    def _screen(self):
        return QGuiApplication.primaryScreen()

    def _apply_geometry(self, animate: bool = False):
        screen = self._screen()
        if screen is None:
            return
        geo = screen.geometry()
        self.base = geometry.resolve(
            self.cfg["style"], float(geo.width()), self.cfg["scale"],
            content_width=self._content_width(), offset_x=self.cfg["offset_x"])
        self.open_shape = geometry.expanded(
            self.cfg["style"], float(geo.width()), self.cfg["scale"],
            offset_x=self.cfg["offset_x"])
        target = self.open_shape if self.expanded else self.base
        if animate:
            self._retarget()
            if not self.expanded:
                if self._w.target > self._w.value + 0.5:
                    self._w.tune(*CONTENT_GROW_W)
                elif self._w.target < self._w.value - 0.5:
                    self._w.tune(*CONTENT_SHRINK_W)
            if (abs(self._w.target - self._w.value) > 0.01
                    or abs(self._h.target - self._h.value) > 0.01):
                self._start_motion()
            return
        self._w.snap(target.rect.width())
        self._h.snap(target.rect.height())
        self._swell.snap(0.0)
        self._sync_geometry()

    def _sync_geometry(self):
        width = max(1.0, self._w.value)
        height = max(1.0, self._h.value)
        self.shape = geometry.morph(self.base, self.open_shape, width, height)
        span = self.open_shape.rect.height() - self.base.rect.height()
        swell = self.base.rect.height() * (SWELL_H - 1.0) * self._swell.value
        if not self.expanded and height <= self.base.rect.height() + swell + 0.5:
            self.progress = 0.0
        else:
            self.progress = (0.0 if span <= 0 else
                             max(0.0, min(1.0, (height - self.base.rect.height()) / span)))
        wr = geometry.window_rect(self.shape)
        screen = self._screen().geometry()
        self._offset = QPoint(int(screen.left() + round(wr.left())),
                              int(screen.top() + round(wr.top())))
        self._window_rect = wr
        rect = (self._offset.x(), self._offset.y(),
                int(round(wr.width())), int(round(wr.height())))
        if rect != (self.x(), self.y(), self.width(), self.height()):
            self.setGeometry(*rect)
        self._sync_overlays()
        self.update()

    def _window_origin(self):
        # Paint from the same integer origin the window was moved to, so a
        # fractional wr.left cannot shift the whole surface on the last frame.
        return (int(round(self._window_rect.left())),
                int(round(self._window_rect.top())))

    def _sync_overlays(self):
        editing = self._todo_adding or self._todo_editing is not None
        show = (self.expanded and self.page == "todo" and editing
                and self.progress > 0.9)
        if not show:
            self.todo_input.hide()
            self.todo_time_input.hide()
            return
        self.todo_input.setPlaceholderText(
            "新的待办，回车添加" if self._todo_editing is None
            else "修改待办，回车保存")
        palette = self.theme
        accent = palette.color("accent")
        style = (
            "QLineEdit{background:%s;color:%s;"
            "border:1px solid rgba(%d,%d,%d,0.55);"
            "border-radius:6px;padding:1px 5px;font-size:11px;}"
            % (palette.color("surface").name(),
               palette.color("textPrimary").name(),
               accent.red(), accent.green(), accent.blue()))
        for widget, rect in ((self.todo_input, self._todo_input_rect()),
                             (self.todo_time_input, self._todo_time_rect())):
            ox, oy = self._window_origin()
            widget.setGeometry(
                int(rect.left()) - ox,
                int(rect.top()) - oy,
                int(rect.width()), int(rect.height()))
            widget.setStyleSheet(style)
            widget.show()
            widget.raise_()

    def _retarget(self):
        if self.expanded:
            self._w.target = self.open_shape.rect.width()
            self._h.target = self.open_shape.rect.height()
            return
        swell = self._swell.value
        self._w.target = self.base.rect.width() * (1.0 + (SWELL_W - 1.0) * swell)
        self._h.target = self.base.rect.height() * (1.0 + (SWELL_H - 1.0) * swell)

    def _start_motion(self):
        if not self._frame.isActive():
            self._last_frame = time.monotonic()
            self._frame.start()

    def _advance(self):
        now = time.monotonic()
        dt = now - self._last_frame
        self._last_frame = now
        self._swell.step(dt)
        self._retarget()
        moving = self._w.step(dt)
        moving = self._h.step(dt) or moving
        moving = self._swell.moving() or moving
        moving = self._lyric_fading() or moving
        moving = self._lyric_page_fading() or moving
        moving = self._lyrics_fading() or moving
        moving = self._notice_fading() or moving
        if not moving:
            self._w.snap(self._w.target)
            self._h.snap(self._h.target)
            self._swell.snap(self._swell.target)
            self._frame.stop()
        self._sync_geometry()

    def _lyric_fading(self):
        return bool(self._lyric_line) and time.monotonic() - self._lyric_at < LYRIC_FADE

    def _lyric_ease(self):
        if not self._lyric_line:
            return 1.0
        t = max(0.0, min(1.0, (time.monotonic() - self._lyric_at)
                         / LYRIC_FADE))
        return 1.0 - (1.0 - t) ** 3

    def _lyric_page_fading(self):
        return time.monotonic() - self._lyric_page_at < LYRIC_FADE

    def _lyric_page_ease(self):
        t = max(0.0, min(1.0, (time.monotonic() - self._lyric_page_at)
                         / LYRIC_FADE))
        return 1.0 - (1.0 - t) ** 3

    def _lyrics_fading(self):
        return time.monotonic() - self._lyrics_at < LYRIC_FADE

    def _lyrics_mix(self):
        t = max(0.0, min(1.0, (time.monotonic() - self._lyrics_at)
                         / LYRIC_FADE))
        if self._lyrics_on:
            return 1.0 - (1.0 - t) ** 3
        return (1.0 - t) ** 3

    def _sync_lyrics_anim(self, state):
        on = bool(self._show_lyrics and state["present"] and state["line"])
        if on != self._lyrics_on:
            self._lyrics_on = on
            self._lyrics_at = time.monotonic()
            self._start_motion()

    def _notice_fading(self):
        return (self._notice is not None
                and time.monotonic() - self._notice_at < NOTICE_FADE)

    def _content_width(self) -> float:
        if self.cfg["style"] == "line":
            return 0.0
        scale = max(80, min(140, self.cfg["scale"])) / 100.0
        parts = self._compact_parts(scale)
        gap = 6 * scale
        left_w = sum(width for _, width, _ in parts)
        if len(parts) > 1:
            left_w += gap * (len(parts) - 1)
        return left_w + self._compact_right_width(scale)

    def _compact_right_width(self, scale):
        gap = 6 * scale
        clock_w = render.text_width(self._clock_text(datetime.now()),
                                    13.5 * scale, QFont.DemiBold)
        level = self._battery_level()
        battery_w = 0.0
        if level is not None:
            battery_w = render.BATTERY_W * scale
        return 8 * scale + clock_w + (gap + battery_w if battery_w else 0.0)

    def _battery_level(self):
        """None when the machine has no battery or the user hid the gauge."""
        if not self.cfg.get("show_battery", True):
            return None
        return self.data.get("battery")

    def _compact_capacity(self, scale):
        screen = self._screen()
        screen_w = float(screen.geometry().width()) if screen else 1920.0
        panel_w = min(geometry.PANEL_W, max(1.0, screen_w - 16.0))
        inset = (geometry.CAPSULE_INSET if self.cfg["style"] == "capsule"
                 else geometry.NOTCH_INSET)
        return panel_w - 2 * inset * scale

    def _compact_parts(self, scale):
        """Left-to-right status slots; the clock/battery group is right-aligned."""
        if self._notice is not None:
            return self._notice_parts(scale)
        gap = 6 * scale
        gauge = 19 * scale
        parts = ([("cpu", gauge, None), ("mem", gauge, None)]
                 if self.cfg.get("show_monitor", True) else [])
        if self.cfg.get("show_pet", True):
            parts.append(("pet", 15 * scale, None))
        if self._activity_visible():
            label = str(self.activity.get("label") or "")
            width = (18 * scale + render.text_width(
                label, 9.5 * scale, QFont.DemiBold) + 10 * scale)
            parts.append(("activity", min(width, 110 * scale), "quota"))
        music_at = len(parts)
        todo_open = sum(1 for item in self.productivity.todos if not item["done"])
        if todo_open:
            parts.append(("todo", 28 * scale, "todo"))
        if self.focus["running"] or self._focus_done:
            parts.append(("focus", 56 * scale, "focus"))
        badge = self._mail_badge()
        if badge:
            parts.append(("mail", (28 + (8 if len(badge) > 2 else 0)) * scale,
                          "mail"))
        if self._water_pending:
            parts.append(("water", 48 * scale, "water"))
        if self._meeting_offer is not None:
            parts.append(("meeting", 60 * scale, "todo"))
        if self.cfg.get("show_stock", True) and self._stock_shown:
            label = self._stock_chip_text()
            parts.append(("stock", 8 * scale + render.text_width(
                label, 9.5 * scale, QFont.DemiBold), "stock"))
        slot = self._weather_slot(scale)
        if slot:
            parts.append(("weather", slot["width"], None))
        if self.music and self.music.get("title"):
            right_w = self._compact_right_width(scale)

            def available():
                fixed = sum(width for _, width, _ in parts)
                return (self._compact_capacity(scale) - fixed
                        - gap * len(parts) - right_w)

            if available() < 96 * scale:
                parts = [part for part in parts if part[0] != "weather"]
            if available() < 96 * scale:
                parts = [part for part in parts if part[0] != "pet"]
                music_at = min(music_at, len(parts))
            width = max(26 * scale, min(self._compact_music_width(scale),
                                        available()))
            parts.insert(music_at, ("music", width, None))
        return parts

    def _notice_text(self, notice):
        body = str(notice.get("body") or "")
        if notice.get("kind") in ("mail", "meeting") and body:
            return f"{notice.get('title', '')} · {body}"
        return str(notice.get("title") or "")

    def _notice_parts(self, scale):
        gap = 6 * scale
        capacity = self._compact_capacity(scale) - self._compact_right_width(scale)
        text = self._notice_text(self._notice)
        width = max(84 * scale, min(
            170 * scale,
            22 * scale + render.text_width(text, 10.5 * scale, QFont.DemiBold)
            + 6 * scale))
        parts = [["notice", width, "notice"]]

        def used():
            return (sum(part[1] for part in parts)
                    + gap * (len(parts) - 1))

        if self.cfg.get("show_pet", True) and not (
                self.music and self.music.get("title")):
            parts.append(["pet", 15 * scale, None])
        if self.focus["running"]:
            parts.append(["focus", 56 * scale, "focus"])
        if self.music and self.music.get("title"):
            room = capacity - used() - gap
            if room < 80 * scale:
                for index in range(1, len(parts)):
                    if parts[index][0] == "focus":
                        removed = parts.pop(index)
                        room += removed[1] + gap
                        break
            if room >= 44 * scale:
                parts.append(["music", max(
                    44 * scale, min(self._compact_music_width(scale), room)), None])
        while len(parts) > 1 and used() > capacity:
            if parts[-1][0] == "music":
                parts.pop()
            elif len(parts) > 2:
                parts.pop(1)
            else:
                parts[0][1] = max(60 * scale,
                                  parts[0][1] - (used() - capacity))
                break
        return [(part[0], part[1], part[2]) for part in parts]

    def _compact_music_text(self):
        if not self.music or not self.music.get("title"):
            return "", None
        info = lyrics.current(self.music.get("lyric"),
                              float(self.music.get("position") or 0))
        return (info["text"] if info else self.music.get("title", "")), info

    def _compact_music_width(self, scale):
        text, info = self._compact_music_text()
        if info or (self.music or {}).get("lyric"):
            return 180 * scale
        measured = render.text_width(text, 11 * scale, QFont.DemiBold)
        return max(64 * scale, min(220 * scale, measured))

    def _lyric_page(self, rows, max_rows, info, position):
        if not rows or len(rows) <= max_rows or not info:
            return rows[:max_rows], 0
        start = float(info.get("start") or 0)
        end = info.get("end")
        if end is None:
            end = (self.music or {}).get("length") or start + 5
        share = 0.0 if end <= start else max(
            0.0, min(1.0, (position - start) / (end - start)))
        total = sum(max(1, len(row)) for row in rows)
        target = share * total
        seen = 0
        focus = len(rows) - 1
        for index, row in enumerate(rows):
            seen += max(1, len(row))
            if target < seen:
                focus = index
                break
        first = max(0, min(focus - max_rows + 1, len(rows) - max_rows))
        return rows[first:first + max_rows], first

    def _mail_badge(self):
        unread = int(self.mail.get("unread") or 0)
        if unread <= 0:
            return ""
        return "99+" if unread > 99 else str(unread)

    def _stock_change_pct(self):
        try:
            return float(self.stock.get("change_pct"))
        except (TypeError, ValueError):
            return None

    def _stock_chip_visible(self):
        """收盘/休市一段时间后收起态不再显示涨跌。"""
        return stock_module.chip_visible(
            self.stock.get("code") or self.cfg.get("stock_code", ""),
            self.stock.get("date", ""), None,
            int(self.cfg.get("stock_grace_minutes", 15)),
            bool(self.cfg.get("stock_hide_closed", True)))

    def _stock_chip_text(self):
        pct = self._stock_change_pct()
        return "--" if pct is None else f"{pct:+.2f}%"

    def _stock_token(self):
        pct = self._stock_change_pct()
        if pct is None or abs(pct) < 0.005:
            return "textTertiary" if pct is None else "textPrimary"
        return "danger" if pct > 0 else "success"

    def _weather_slot(self, scale):
        if not self.cfg.get("show_weather", True):
            return None
        current = self.data.get("weather") or {}
        try:
            temp = int(round(float(current.get("temp"))))
        except (TypeError, ValueError):
            return None
        text = f"{temp}°"
        icon = 15 * scale
        gap = 3 * scale
        text_px = 11.5 * scale
        return {
            "kind": weather.kind(current.get("text")),
            "text": text,
            "icon": icon,
            "gap": gap,
            "text_px": text_px,
            "width": icon + gap + render.text_width(text, text_px, QFont.DemiBold),
        }

    def _clock_text(self, now):
        english = self.cfg["clock_english"]
        twelve = self.cfg["clock_12h"]
        if twelve:
            digits = f"{now.hour % 12 or 12}:{now.strftime('%M')}"
        else:
            digits = now.strftime("%H:%M")
        if self.cfg["show_seconds"]:
            digits += now.strftime(":%S")

        period = ""
        suffix = False
        if twelve and self.cfg["clock_period"] == 1:
            if english:
                period, suffix = ("PM" if now.hour >= 12 else "AM"), True
            else:
                period = "下午" if now.hour >= 12 else "上午"
        elif twelve and self.cfg["clock_period"] == 2:
            if english:
                periods = ("Early morning", "Morning", "Noon", "Afternoon",
                           "Evening", "Night")
            else:
                periods = ("凌晨", "上午", "中午", "下午", "傍晚", "晚上")
            period = periods[0 if now.hour <= 5 else
                             1 if now.hour <= 10 else
                             2 if now.hour <= 12 else
                             3 if now.hour <= 16 else
                             4 if now.hour <= 18 else 5]

        if not period:
            text = digits
        else:
            text = f"{digits} {period}" if suffix else f"{period} {digits}"
        if self.cfg["show_weekday"]:
            text = (WEEKDAYS_EN[now.weekday()] + " " + text if english
                    else text + " 周" + WEEKDAYS_ZH[now.weekday()])
        return text

    def _panel_clock(self, now):
        """Header time: no weekday; AM/PM only when the clock is 12-hour."""
        english = self.cfg["clock_english"]
        twelve = self.cfg["clock_12h"]
        if twelve:
            digits = f"{now.hour % 12 or 12}:{now.strftime('%M')}"
        else:
            digits = now.strftime("%H:%M")
        if self.cfg["show_seconds"]:
            digits += now.strftime(":%S")
        if twelve and self.cfg["clock_period"] == 1:
            if english:
                return digits + (" PM" if now.hour >= 12 else " AM")
            return ("下午 " if now.hour >= 12 else "上午 ") + digits
        return digits

    def _panel_date(self, now):
        """Header date: weekday and day, no year, in the clock's language."""
        if self.cfg["clock_english"]:
            date = f"{MONTHS_EN[now.month - 1]} {now.day}"
            return (WEEKDAYS_EN[now.weekday()] + ", " + date
                    if self.cfg["show_weekday"] else date)
        date = f"{now.month}月{now.day}日"
        return ("周" + WEEKDAYS_ZH[now.weekday()] + " " + date
                if self.cfg["show_weekday"] else date)

    def _focus_reset(self):
        minutes = max(1, int(self.cfg.get("focus_minutes") or 25))
        if self.focus["phase"] != "focus":
            minutes = max(1, int(self.cfg.get("rest_minutes") or 5))
        self.focus["total"] = minutes * 60
        self.focus["remaining"] = minutes * 60
        self.focus["running"] = False

    def _water_interval(self) -> int:
        return max(5, int(self.cfg.get("water_minutes") or 45)) * 60

    def _enqueue_alert(self, kind, title, body="", page="music", key=None):
        for alert in ([self._notice] if self._notice else []) + self._alerts:
            if (alert.get("kind") == kind and alert.get("title") == title
                    and alert.get("body", "") == body):
                return
        self._alerts.append({"kind": kind, "title": title, "body": body,
                             "page": page, "key": key})
        self._alerts = self._alerts[-8:]
        self._show_next_notice()

    def _show_next_notice(self, force=False):
        now = time.monotonic()
        if self._notice is not None and not force and now < self._notice_until:
            return
        had = self._notice is not None
        self._notice = None
        if self._alerts and not self._fs_hidden:
            self._notice = self._alerts.pop(0)
            self._notice_at = now
            self._notice_until = now + NOTICE_SECONDS
        if had or self._notice is not None:
            self._apply_geometry(animate=True)
            self.update()

    def _open_notice(self):
        notice = self._notice
        if not notice:
            return
        page = notice.get("page") or "music"
        self.set_page(page)
        if page == "mail" and notice.get("key") is not None:
            index = self._mail_index(notice["key"])
            if index is not None:
                self._mail_detail = index
        if page == "todo" and notice.get("key") is not None:
            for index, item in enumerate(self.productivity.todos):
                if item is notice["key"] and self._todo_details(item):
                    self._todo_detail = index
                    break
        self.set_expanded(True, animate=False)

    def _ack_water(self, drink):
        if drink:
            self.productivity.add_water(250)
            self._pet_until = time.monotonic() + 2.0
        self._water_pending = False
        self._water_due = time.monotonic() + self._water_interval()
        self._drop_alert("water")
        self._apply_geometry(animate=True)

    def _drop_alert(self, kind):
        self._alerts = [alert for alert in self._alerts
                        if alert.get("kind") != kind]
        if self._notice is not None and self._notice.get("kind") == kind:
            self._show_next_notice(force=True)

    def offer_meeting(self, text):
        """Ask before turning a copied meeting invite into a todo."""
        if not self.cfg.get("meeting_detect", True):
            return False
        offer = meeting.parse_meeting(text)
        if not offer:
            return False
        if self._meeting_offer and self._meeting_offer["text"] == offer["text"]:
            return False
        self._meeting_offer = dict(offer, until=time.monotonic()
                                   + MEETING_OFFER_SECONDS)
        banner = (self.expanded and self.page == "todo"
                  and not (self._todo_adding or self._todo_editing is not None))
        if not banner:
            self._enqueue_alert("meeting", "会议邀请", offer["title"],
                                "todo")
        self._apply_geometry(animate=True)
        self.update()
        return True

    def _resolve_meeting(self, accept):
        offer = self._meeting_offer or {}
        self._meeting_offer = None
        if accept and self.productivity.add_todo(
                offer.get("text"), None, offer.get("remind", ""),
                offer.get("remind_on", ""), offer):
            self._scroll["todo"] = 0
            self._pet_until = time.monotonic() + 2.0
        self._drop_alert("meeting")
        self._apply_geometry(animate=True)

    def _water_tick(self):
        now = datetime.now()
        today = now.date().isoformat()
        interval = self._water_interval()
        if today != self._water_day:
            self._water_day = today
            self._water_pending = False
            self._water_due = time.monotonic() + interval
        if (not self.cfg.get("water_remind", True) or self._water_pending
                or self.productivity.water_percent() >= 1.0):
            return
        if not WATER_HOURS[0] <= now.hour < WATER_HOURS[1]:
            return
        if time.monotonic() < self._water_due:
            return
        self._water_pending = True
        self._enqueue_alert("water", "喝水时间到了", "补充 250 ml 水分", "water")
        self._apply_geometry(animate=True)

    def _todo_reminder_tick(self):
        now = datetime.now()
        today = now.date()
        if self._todo_remind_day != today.isoformat():
            self._todo_remind_day = today.isoformat()
            self._todo_reminded = {}
        minute = now.strftime("%H:%M")
        for item in self.productivity.todos:
            remind = item.get("remind")
            if (not remind or remind != minute
                    or not self.productivity.todo_due(item, today)
                    or self.productivity.todo_done(item, today)):
                continue
            key = (item.get("text", ""), remind)
            if key in self._todo_reminded:
                continue
            self._todo_reminded[key] = True
            self._enqueue_alert("todo", "待办到时间了", item["text"], "todo",
                                key=item)

    def _mail_key(self, item):
        return (item.get("sender", ""), item.get("subject", ""),
                item.get("date", ""))

    def _mail_confirm_key(self, key):
        return "|".join(str(part) for part in key)

    def _mail_index(self, key):
        for index, item in enumerate(self.mail.get("items") or []):
            if self._mail_key(item) == key:
                return index
        return None

    def _mail_unread(self, item):
        if (self._mail_op_key == self._mail_key(item)
                and time.monotonic() < self._mail_op_until):
            # 服务器操作还在路上：先按用户点的意思显示，刷新回来以服务器为准
            return self._mail_op_action == "unseen"
        return (not item.get("seen", False)
                and self._mail_key(item) not in self._mail_read)

    def _mail_mark_read(self, item):
        key = self._mail_key(item)
        self._mail_read.add(key)
        self._mail_new.pop(key, None)

    def _current_mail(self):
        items = self.mail.get("items") or []
        if self._mail_detail is not None and 0 <= self._mail_detail < len(items):
            item = items[self._mail_detail]
            if self._mail_key(item) not in self._mail_hidden:
                return item
        return None

    def _open_mail_reader(self, item):
        if self._mail_reader is not None:
            self._mail_reader.close()
        reader = MailReader(item, self)
        reader.setAttribute(Qt.WA_DeleteOnClose)
        reader.destroyed.connect(lambda: setattr(self, "_mail_reader", None))
        self._mail_reader = reader
        reader.show()
        reader.raise_()
        reader.activateWindow()

    def _mail_sync_enabled(self):
        return bool(self.cfg.get("mail_sync_operations", False))

    def _sender_name(self, value):
        text = str(value or "").split("<", 1)[0].strip().strip('"').strip()
        return text[:18] or "邮箱"

    def _todo_input_rect(self):
        card = self._todo_card_rect()
        return QRectF(card.left() + 7, card.top() + 3,
                      card.width() - 33, 19)

    def _todo_card_rect(self):
        area = self._content_rect()
        return QRectF(area.left() + 84, area.top(), area.width() - 84,
                      area.height())

    def _todo_time_rect(self):
        card = self._todo_card_rect()
        return QRectF(card.left() + 32, card.top() + 41,
                      card.width() - 40, 17)

    def _todo_time_value(self):
        text = self.todo_time_input.text().strip().replace("：", ":")
        match = re.match(r"^([01]?\d|2[0-3]):([0-5]\d)$", text)
        return f"{int(match.group(1)):02d}:{match.group(2)}" if match else ""

    def _todo_submit(self):
        text = self.todo_input.text()
        remind = self._todo_time_value()
        if self._todo_editing is None:
            ok = self.productivity.add_todo(text, self._todo_repeat, remind)
        else:
            ok = self.productivity.update_todo(
                self._todo_editing, text, self._todo_repeat, remind)
        if ok:
            self._scroll["todo"] = 0
            self.todo_input.clear()
            self.todo_time_input.clear()
            self._pet_until = time.monotonic() + 2.0
            self._apply_geometry(animate=True)
        self._todo_adding = False
        self._todo_editing = None
        self._todo_repeat = []
        self.todo_input.hide()
        self.todo_time_input.hide()
        self._sync_overlays()
        self.update()

    def _todo_pick(self, index):
        if not 0 <= index < len(self.productivity.todos):
            return
        item = self.productivity.todos[index]
        self._todo_choosing = False
        self._todo_adding = False
        self._todo_editing = index
        self._todo_repeat = list(item.get("repeat") or [])
        self.todo_input.setText(item["text"])
        self.todo_time_input.setText(item.get("remind") or "")
        self.todo_input.setFocus(Qt.OtherFocusReason)

    def eventFilter(self, obj, event):
        if (obj in (self.todo_input, self.todo_time_input)
                and event.type() == QEvent.KeyPress
                and event.key() == Qt.Key_Escape):
            self._todo_adding = False
            self._todo_editing = None
            self._todo_repeat = []
            self.todo_input.clear()
            self.todo_time_input.clear()
            self.todo_input.clearFocus()
            self._sync_overlays()
            self.update()
            return True
        return super().eventFilter(obj, event)

    def set_page(self, page):
        pages = self._pages()
        if page not in dict(pages):
            return
        names = [item for item, _ in pages]
        if page != self.page:
            old = names.index(self.page) if self.page in names else 0
            self._page_dir = 1 if names.index(page) > old else -1
            self._page_beat.start()
        self.page = page
        self._sync_monitor_sampling()
        if page != "todo":
            self._todo_adding = False
            self._todo_editing = None
            self._todo_choosing = False
            self._todo_repeat = []
            self.todo_input.clear()
            self.todo_time_input.clear()
        if page != "mail":
            self._mail_detail = None
        if page != "todo":
            self._todo_detail = None
        if page != "music":
            self._volume_open = False
        self._page_at = time.monotonic()
        self._confirm = ("", 0.0)
        if page == "tools":
            if self._unread:
                # 页码豆亮只可能是新通知，直接落到通知，省得挨个标签找
                self.tools_page = "notify"
            if self.tools_page == "notify":
                self._unread = 0
            elif (self.tools_page == "shelf" and not self.productivity.shelf
                    and self.productivity.clips):
                # 空置物架没东西可看，优先落到剪贴；两边都空时留在置物架看拖拽提示
                self.tools_page = "clips"
        self._sync_overlays()
        self.update()

    def _page_advance(self):
        if time.monotonic() - self._page_at > 0.3:
            self._page_beat.stop()
        self.update()

    def set_tools_page(self, page):
        if page in dict(TOOLS):
            self.tools_page = page
            if page == "notify":
                self._unread = 0
            self.update()

    def navigate_page(self, step):
        names = [page for page, _ in self._pages()]
        index = (names.index(self.page) + step) % len(names)
        self.set_page(names[index])

    def _pages(self):
        return PAGES

    def _sync_monitor_sampling(self):
        self.monitor_focus.emit(bool(self.cfg.get("show_monitor", True))
                                or self._status_strip())

    def _status_strip(self):
        """Views that draw resource readings regardless of the pill toggle."""
        if not self.expanded:
            return False
        if self.page == "monitor":
            return True
        return self.page == "music" and not (
            self.music and self.music.get("title"))

    def set_mail(self, result):
        self._mail_refresh_until = 0.0
        keep = None
        old = self.mail.get("items") or []
        if self._mail_detail is not None and 0 <= self._mail_detail < len(old):
            keep = self._mail_key(old[self._mail_detail])
        self.mail = dict(result or {})
        items = self.mail.get("items") or []
        self._mail_detail = next(
            (index for index, item in enumerate(items)
             if keep is not None and self._mail_key(item) == keep), None)
        unread = int(self.mail.get("unread") or 0)
        if unread > self._last_mail_unread:
            self._mail_pulse_until = time.monotonic() + 6.0
        self._last_mail_unread = unread
        if self.mail.get("status") == "ok":
            keys = [self._mail_key(item) for item in items]
            fresh = [(index, item) for index, item in enumerate(items)
                     if self._mail_seen_ready
                     and self._mail_key(item) not in self._mail_seen]
            now = time.monotonic()
            for _, item in fresh:
                self._mail_new[self._mail_key(item)] = now + MAIL_NEW_SECONDS
            self._mail_new = {key: until for key, until in self._mail_new.items()
                              if until > now}
            self._mail_seen.update(keys)
            if len(self._mail_seen) > 400:
                self._mail_seen = set(keys)
            if len(self._mail_read) > 400:
                self._mail_read &= set(keys)
            self._mail_seen_ready = True
            if fresh and self.cfg.get("mail_remind", True):
                _, item = fresh[0]
                sender = self._sender_name(item.get("sender"))
                title = "验证码邮件" if item.get("code") else "新邮件"
                self._enqueue_alert("mail", title, sender, "mail",
                                    self._mail_key(item))
        self._apply_geometry(animate=True)
        self.update()

    def set_mail_operation(self, result):
        ok = (result or {}).get("status") == "ok"
        self._mail_op_message = (
            (result or {}).get("message") or (result or {}).get("error")
            or ("操作完成" if ok else "邮件操作失败"))
        self._mail_op_until = time.monotonic() + (5.0 if ok else 9.0)
        self._mail_op_token = "success" if ok else "danger"
        if ok:
            if self._mail_op_action == "trash":
                if self._mail_pending_delete:
                    self._mail_hidden.add(self._mail_pending_delete)
                    self._mail_pending_delete = ""
                self._mail_detail = None
            elif self._mail_op_key:
                # 服务器已确认：直接落到缓存上，等刷新回来前不会闪回旧状态
                for item in self.mail.get("items") or []:
                    if self._mail_key(item) == self._mail_op_key:
                        item["seen"] = self._mail_op_action == "seen"
                        if item["seen"]:
                            self._mail_mark_read(item)
                        else:
                            self._mail_read.discard(self._mail_key(item))
            QTimer.singleShot(400, lambda: self._do_action("mail_refresh"))
        elif self._mail_op_action in ("seen", "unseen"):
            # 服务器没接受：把本地状态改回真实的样子，留在详情页好重试
            key = self._mail_op_key
            if key:
                if self._mail_op_action == "seen":
                    self._mail_read.discard(key)
                else:
                    self._mail_read.add(key)
        self._mail_op_key = None
        self.update()

    def set_calendar(self, result):
        self._calendar_refresh_until = 0.0
        self.calendar = dict(result or {})
        self.update()

    def set_quota(self, result):
        self.quota = dict(result or {})
        providers = self.quota.get("providers") or []
        if not any(item.get("id") == self.quota_selected for item in providers):
            ready = [item for item in providers if item.get("status") == "ok"]
            self.quota_selected = ((ready or providers or [{}])[0].get("id") or "")
        self._quota_refresh_until = 0.0
        self.update()

    def set_stock(self, result):
        code = (result or {}).get("code")
        if code and code != self.cfg.get("stock_code"):
            return
        self.stock = dict(result or {})
        self._stock_refresh_until = 0.0
        self._stock_shown = self._stock_chip_visible()
        self._apply_geometry(animate=True)
        self.update()

    def set_activity(self, result):
        state = dict(result or {})
        keys = ("provider", "state", "label", "detail", "active", "at")
        if all(self.activity.get(key) == state.get(key) for key in keys):
            return
        self.activity = state
        self._activity_shown = self._activity_visible()
        self._apply_geometry(animate=True)
        self.update()

    def clear_activity(self):
        """Turn off the feature: drop the last known turn state."""
        self.set_activity({"provider": "", "state": "idle", "label": "",
                           "detail": "", "active": False, "at": 0.0})

    def _activity_visible(self):
        if not self.cfg.get("show_activity", True):
            return False
        state = self.activity.get("state")
        if state in ("thinking", "working", "responding"):
            return bool(self.activity.get("active"))
        if state in ("completed", "aborted"):
            age = time.time() - float(self.activity.get("at") or 0)
            return 0.0 <= age < ACTIVITY_HOLD
        return False

    def _activity_token(self):
        state = self.activity.get("state")
        if state in ("responding", "completed"):
            return "success"
        return "danger" if state == "aborted" else "accent"

    def _activity_age(self):
        at = float(self.activity.get("at") or 0)
        if not at:
            return ""
        seconds = max(0, int(time.time() - at))
        if seconds < 60:
            return f"{seconds}s"
        if seconds < 3600:
            return f"{seconds // 60}:{seconds % 60:02d}"
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}"

    def add_notification(self, note):
        self.notify_error = ""
        self.notifications.insert(0, dict(note))
        self.notifications = self.notifications[:30]
        if self.page != "tools" or self.tools_page != "notify":
            self._unread += 1
            self._pet_until = time.monotonic() + 2.0
        self.update()

    def set_notify_error(self, message):
        self.notify_error = str(message or "")
        self.update()

    def set_click_through(self, enabled):
        self._click_through = bool(enabled)
        if enabled:
            self.set_expanded(False, animate=False)
        self.show()
        self.raise_()
        self._apply_geometry()
        self._sync_click_through()
        QTimer.singleShot(50, self._keep_above)

    def _sync_click_through(self):
        """穿透靠 XShape 清空输入区域，不用 Qt.WindowTransparentForInput。

        那个 flag 会销毁并重建原生窗口，而且只要它开着，Qt 后续的改尺寸就
        不再下发到 X：X 窗口停在旧宽度，岛被裁断，切桌面时还会露出旧frame。
        """
        if QGuiApplication.platformName() != "xcb":
            return
        winid = int(self.winId())
        if self._click_through:
            x11.drop_input_region(winid)
        else:
            x11.clear_input_shape(winid)

    def _keep_above(self):
        if QGuiApplication.platformName() == "xcb":
            x11.keep_above(int(self.winId()))

    def _watch_desktop(self):
        shown = x11.showing_desktop()
        if not shown and not self._fs_hidden and self.isMinimized():
            # 显示桌面会把岛一起最小化，退出后 WM 不一定帮我们恢复
            self.showNormal()
            x11.remap(int(self.winId()))
        if shown == self._desktop_shown:
            return
        self._desktop_shown = shown
        winid = int(self.winId())
        x11.set_window_type(winid, shown)
        if shown:
            if self.isMinimized():
                self.showNormal()
            if not self._fs_hidden:
                x11.remap(winid)
                self.raise_()
        else:
            self._keep_above()

    def set_fullscreen_hidden(self, hidden):
        self._fs_hidden = bool(hidden)
        if hidden:
            self.hide()
        else:
            self.show()
            self._show_next_notice()

    def _apply_blur(self):
        if self._blur_ok is None:
            self._blur_ok = blur.supported()
        kind = self.theme.material.get("kind")
        if not self.cfg.get("enable_blur", True) or kind != "glass":
            blur.clear(int(self.winId()))
            return
        rect = self.base.rect if not self.expanded else self.open_shape.rect
        blur.apply(int(self.winId()), (rect.left(), rect.top(),
                                       rect.width(), rect.height()))

    def _marquee_elapsed(self, key, text):
        now = time.monotonic()
        entry = self._marquee.get(key)
        if entry is None or entry[0] != text:
            self._marquee[key] = (text, now)
            return 0.0
        return now - entry[1]

    def apply(self, cfg, theme):
        self.cfg = cfg
        self.theme = theme
        if self.page not in dict(self._pages()):
            self.set_page("music")
        self._sync_monitor_sampling()
        if self.stock.get("code") != self.cfg.get("stock_code"):
            self.stock = {"status": "loading", "points": [],
                          "code": self.cfg.get("stock_code", "")}
        if not self.focus["running"]:
            self._focus_reset()
        self._stock_shown = self._stock_chip_visible()
        interval = self._water_interval()
        if interval != self._water_minutes_seen:
            self._water_minutes_seen = interval
            self._water_due = time.monotonic() + interval
        disabled = [kind for kind, key in (
            ("meeting", "meeting_detect"), ("water", "water_remind"),
            ("focus", "focus_remind"),
            ("mail", "mail_remind")) if not self.cfg.get(key, True)]
        if "meeting" in disabled:
            self._meeting_offer = None
        if "water" in disabled:
            self._water_pending = False
        if disabled:
            self._alerts = [alert for alert in self._alerts
                            if alert.get("kind") not in disabled]
            if self._notice is not None and self._notice.get("kind") in disabled:
                self._show_next_notice(force=True)
        self._activity_shown = self._activity_visible()
        self._apply_geometry()
        QTimer.singleShot(50, self._apply_blur)

    def set_data(self, data):
        weather = self.data.get("weather")
        self.data = dict(data)
        if "weather" not in data:
            self.data["weather"] = weather
        self.sample_at = datetime.now()
        self._apply_geometry(animate=True)
        self.update()

    def set_weather(self, weather):
        self.data["weather"] = weather
        self._apply_geometry(animate=True)
        self.update()

    def set_music(self, music):
        had_track = bool(self.music and self.music.get("title"))
        if music and not music.get("title"):
            music = None
        if music is None or music.get("title") != self._seek_title:
            self._seek_preview = None
        self.music = music
        if had_track != bool(music and music.get("title")):
            self._sync_monitor_sampling()
        if music:
            path = music.get("art_path", "")
            if path != self._cover_path:
                self._cover_path = path
                self._cover = None
        text, info = self._compact_music_text()
        line = (info or {}).get("text", "")
        if line != self._lyric_line:
            self._lyric_line = line
            self._lyric_at = time.monotonic()
            if line:
                self._start_motion()
        playing = bool(music and music.get("status") == "Playing")
        if playing and not self._beat.isActive():
            self._beat.start()
        elif not playing:
            self._beat.stop()
        self._apply_geometry(animate=True)
        self.update()

    def _tick(self):
        visible = self._activity_visible()
        if visible != self._activity_shown:
            self._activity_shown = visible
            self._apply_geometry(animate=True)
        shown = self._stock_chip_visible()
        if shown != self._stock_shown:
            self._stock_shown = shown
            self._apply_geometry(animate=True)
        if self.focus["running"] and self.focus["remaining"] > 0:
            self.focus["remaining"] = max(0, self.focus["remaining"] - 1)
            if self.focus["remaining"] == 0:
                finished = self.focus["phase"]
                self.focus["running"] = False
                self.focus["phase"] = "rest" if finished == "focus" else "focus"
                self._focus_reset()
                self._focus_done = True
                self._pet_until = time.monotonic() + 4.0
                if self.cfg.get("focus_remind", True):
                    if finished == "focus":
                        self._enqueue_alert(
                            "focus", "专注结束 · 该休息了",
                            f"休息 {self.focus['total'] // 60} 分钟", "focus")
                    else:
                        self._enqueue_alert(
                            "focus", "休息结束 · 该专注了",
                            f"专注 {self.focus['total'] // 60} 分钟", "focus")
                self._apply_geometry(animate=True)
        self._water_tick()
        self._todo_reminder_tick()
        if (self._meeting_offer is not None
                and time.monotonic() >= self._meeting_offer["until"]):
            self._meeting_offer = None
            self._drop_alert("meeting")
        if (self._notice is not None
                and time.monotonic() >= self._notice_until):
            self._show_next_notice(force=True)
        self.update()

    def _inside(self) -> bool:
        return self.rect().contains(self.mapFromGlobal(QCursor.pos()))

    def enterEvent(self, event):
        self._hovered = True
        self._leaving.stop()
        if self.expanded:
            return
        self._swell.target = 1.0
        self._start_motion()
        self._intent.start()

    def leaveEvent(self, event):
        if self._inside():
            return
        self._hovered = False
        self._intent.stop()
        if self.expanded:
            self._leaving.start()
        else:
            self._swell.target = 0.0
            self._start_motion()

    def _poll_hover(self):
        if (not self._hovered or self._click_through or self._fs_hidden
                or not self.isVisible()):
            return
        if self._inside():
            self._leaving.stop()
            return
        if self.expanded:
            if not self._leaving.isActive():
                self._intent.stop()
                self._leaving.start()
            return
        self._hovered = False
        if self._swell.target:
            self._swell.target = 0.0
            self._start_motion()

    def _maybe_expand(self):
        if not self.expanded and self._inside():
            self.set_expanded(True)

    def _maybe_collapse(self):
        if (self.expanded and not self._inside() and not self._todo_adding
                and self._todo_editing is None
                and not self._shelf_press and not self._shelf_dragging):
            self.set_expanded(False)

    def set_expanded(self, expanded: bool, animate: bool = True):
        expanded = bool(expanded)
        self._intent.stop()
        if expanded:
            self._leaving.stop()
        else:
            self._hovered = False
        if expanded == self.expanded:
            if not expanded and self._swell.target:
                self._swell.target = 0.0
                self._start_motion()
            return
        self.expanded = expanded
        self._sync_monitor_sampling()
        if not expanded:
            self._todo_adding = False
            self._todo_editing = None
            self._todo_choosing = False
            self._todo_repeat = []
            self.todo_input.clear()
            self.todo_time_input.clear()
            self._volume_open = False
        self._swell.target = 0.0
        if expanded:
            self._w.tune(*OPEN_W)
            self._h.tune(*OPEN_H)
        else:
            self._leaving.stop()
            self._w.tune(*CLOSE)
            self._h.tune(*CLOSE)
        self._retarget()
        if animate:
            self._start_motion()
        else:
            self._w.snap(self._w.target)
            self._h.snap(self._h.target)
            self._swell.snap(0.0)
            self._sync_geometry()
        self._sync_overlays()
        QTimer.singleShot(80, self._apply_blur)

    def toggle(self):
        self.set_expanded(not self.expanded)

    def _content_rect(self):
        panel = self.open_shape.rect
        return QRectF(panel.left() + 41, panel.top() + 31,
                      panel.width() - 82, panel.height() - 49)

    def _music_layout(self):
        area = self._content_rect()
        right = area.right()
        top = area.top()
        size = 54.0
        center = area.center().x()
        return {
            "cover": QRectF(area.left(), top, size, size),
            "prev": QRectF(center - 49, top + 72, 24, 24),
            "play": QRectF(center - 12, top + 72, 24, 24),
            "next": QRectF(center + 25, top + 72, 24, 24),
            "lyrics": QRectF(area.left() + 2, top + 73, 26, 22),
            "strip": QRectF(area.left(), top, size, size),
            "progress": QRectF(area.left(), top + 66, area.width(), 3.5),
        }

    def _volume_popup_rect(self):
        area = self._content_rect()
        return QRectF(area.right() - 64, area.top() + 4, 64, 66)

    def _volume_track_rect(self):
        popup = self._volume_popup_rect()
        return QRectF(popup.center().x() - 3, popup.top() + 18, 6, 26)

    def _set_volume_at(self, y):
        track = self._volume_track_rect()
        ratio = 1.0 - (y - track.top()) / max(1.0, track.height())
        level = set_volume(ratio)
        if level is not None:
            self.data["volume"] = level
            self.data["muted"] = False
        self.update()

    def mousePressEvent(self, event):
        if not self.expanded:
            point = QPointF(event.pos().x() + self._window_rect.left(),
                            event.pos().y() + self._window_rect.top())
            for rect, page in reversed(self._compact_hits):
                if rect.contains(point):
                    if page == "notice":
                        self._open_notice()
                        return
                    self.set_page(page)
                    self.set_expanded(True, animate=False)
                    return
        if self.expanded:
            point = QPointF(event.pos().x() + self._window_rect.left(),
                            event.pos().y() + self._window_rect.top())
            if self.page == "music" and self._volume_open:
                popup = self._volume_popup_rect()
                if popup.contains(point):
                    track = self._volume_track_rect()
                    if track.adjusted(-8, -4, 8, 4).contains(point):
                        self._volume_drag = True
                        self._set_volume_at(point.y())
                        return
                    for rect, action, arg in reversed(self._hits):
                        if action == "music_volume_mute" and rect.contains(point):
                            self._do_action(action, arg)
                            return
                    return
                self._volume_open = False
                self.update()
                return
            for rect, action, arg in reversed(self._tab_hits + self._tools_hits
                                              + self._hits):
                if rect.contains(point):
                    if action == "shelf_open" and event.button() == Qt.LeftButton:
                        self._shelf_press = (arg, point, event.pos())
                        return
                    self._do_action(action, arg)
                    return
        if self.expanded and self.music and self.page == "music":
            point = QPointF(event.pos().x() + self._window_rect.left(),
                            event.pos().y() + self._window_rect.top())
            layout = self._music_layout()
            state = self._music_state()
            bar = layout["progress"]
            if (state["present"] and state["can_seek"] and state["length"] > 0
                    and bar.adjusted(-4, -6, 4, 6).contains(point)):
                self._drag_seek = render.seek_seconds(
                    point.x(), bar.left(), bar.width(), state["length"])
                self.update()
                return
            if self.music.get("player"):
                for key, command in (("prev", "Previous"), ("play", "PlayPause"),
                                     ("next", "Next")):
                    if layout[key].contains(point):
                        self.music_command.emit(command)
                        return
                if layout["strip"].contains(point):
                    self.music_command.emit("PlayPause")
                    return
        if self.cfg["style"] == "line" and not self.expanded:
            self.set_expanded(not self.expanded)

    def mouseMoveEvent(self, event):
        point = QPointF(event.pos().x() + self._window_rect.left(),
                        event.pos().y() + self._window_rect.top())
        if self._volume_drag:
            self._set_volume_at(point.y())
            return
        if (self._shelf_press and event.buttons() & Qt.LeftButton
                and (event.pos() - self._shelf_press[2]).manhattanLength() > 6):
            path = self._shelf_press[0]
            self._shelf_dragging = True
            drag = QDrag(self)
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(path)])
            drag.setMimeData(mime)
            try:
                drag.exec_(Qt.CopyAction)
            finally:
                self._shelf_dragging = False
                self._shelf_press = None
            self.unsetCursor()
            return
        if self._drag_seek is not None:
            state = self._music_state()
            bar = self._music_layout()["progress"]
            if state["length"] > 0:
                self._drag_seek = render.seek_seconds(
                    point.x(), bar.left(), bar.width(), state["length"])
                self.update()
            return
        if self.expanded and self.music and self.page == "music":
            bar = self._music_layout()["progress"]
            if (self._music_state()["can_seek"]
                    and bar.adjusted(-4, -6, 4, 6).contains(point)):
                self.setCursor(Qt.SizeHorCursor)
            else:
                self.unsetCursor()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._shelf_dragging:
            return
        if self._volume_drag:
            self._volume_drag = False
            return
        if self._shelf_press and event.button() == Qt.LeftButton:
            path = self._shelf_press[0]
            self._shelf_press = None
            self._do_action("shelf_open", path)
            return
        if self._drag_seek is not None:
            target = self._drag_seek
            self._drag_seek = None
            self._seek_preview = target
            self._seek_title = (self.music or {}).get("title", "")
            self._seek_at = time.monotonic()
            self.unsetCursor()
            self.music_seek.emit(target)
            self.update()
            return
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if not self.expanded:
            return
        self._wheel_acc += event.angleDelta().y()
        if abs(self._wheel_acc) < 60:
            return
        step = -1 if self._wheel_acc > 0 else 1
        self._wheel_acc = 0
        point = QPointF(event.pos().x() + self._window_rect.left(),
                        event.pos().y() + self._window_rect.top())
        if (self.page == "music" and self._volume_open
                and self._volume_popup_rect().contains(point)):
            current = self.data.get("volume")
            if current is not None:
                level = set_volume(float(current) - step * 0.04)
                if level is not None:
                    self.data["volume"] = level
                    self.data["muted"] = False
                self.update()
            event.accept()
            return
        if self._list_rect is not None and self._list_rect.contains(point):
            if self.page == "mail":
                self._scroll_by("mail", step,
                                len(self.mail.get("items") or []), 3)
            elif self.page == "todo":
                visible = 1 if (self._todo_adding
                                or self._todo_editing is not None) else 3
                self._scroll_by("todo", step,
                                len(self.productivity.todos), visible)
            else:
                self._scroll_by("clips", step,
                                len(self.productivity.clips), 3)
            event.accept()
            return
        self.navigate_page(step)
        event.accept()

    def _scroll_by(self, key, step, count, visible):
        span = max(0, count - visible)
        if span <= 0:
            return False
        self._scroll[key] = max(0, min(span, self._scroll[key] + step))
        self.update()
        return True

    def dragEnterEvent(self, event):
        if event.source() is self:
            return
        if event.mimeData().hasUrls():
            self._drag_active = True
            self.set_page("tools")
            self.set_tools_page("shelf")
            self.set_expanded(True, animate=False)
            event.setDropAction(Qt.CopyAction)
            event.acceptProposedAction()

    def dragMoveEvent(self, event):
        if event.source() is self:
            return
        if event.mimeData().hasUrls():
            event.setDropAction(Qt.CopyAction)
            event.acceptProposedAction()

    def dragLeaveEvent(self, event):
        self._drag_active = False
        self.update()

    def dropEvent(self, event):
        if event.source() is self:
            event.ignore()
            return
        paths = [url.toLocalFile() for url in event.mimeData().urls()
                 if url.isLocalFile()]
        added = False
        for path in paths:
            if os.path.exists(path):
                added = self.productivity.add_shelf(path) or added
        self._drag_active = False
        event.setDropAction(Qt.CopyAction)
        event.acceptProposedAction()
        if added:
            self.set_page("tools")
            self.set_tools_page("shelf")
            self._pet_until = time.monotonic() + 2.0
        self.update()

    def _hit(self, rect, action, arg=None):
        self._hits.append((QRectF(rect), action, arg))

    def _confirming(self, key):
        return self._confirm[0] == key and time.monotonic() - self._confirm[1] < 3.0

    def _copied(self, text):
        return (time.monotonic() < self._copy_until
                and self._copied_text == str(text))

    def _refreshing(self, kind):
        until = (self._mail_refresh_until if kind == "mail"
                 else self._quota_refresh_until if kind == "quota"
                else self._stock_refresh_until if kind == "stock"
                 else self._calendar_refresh_until)
        return time.monotonic() < until

    def _arm_confirm(self, key):
        if self._confirming(key):
            self._confirm = ("", 0.0)
            return True
        self._confirm = (key, time.monotonic())
        return False

    def _do_action(self, action, arg=None):
        if action == "page":
            self.set_page(arg)
        elif action == "nav":
            self.navigate_page(int(arg))
        elif action == "tools":
            self.set_tools_page(arg)
        elif action == "settings":
            self.open_settings.emit(arg or self.page)
        elif action == "music_lyrics":
            self._show_lyrics = not self._show_lyrics
            self.update()
        elif action == "music_volume":
            self._volume_open = not self._volume_open
            self.update()
        elif action == "music_volume_mute":
            muted = not bool(self.data.get("muted", False))
            if set_muted(muted) is not None:
                self.data["muted"] = muted
            self.update()
        elif action == "todo_add":
            if self._todo_adding:
                self._todo_adding = False
                self.todo_input.clear()
                self.todo_time_input.clear()
            else:
                self._todo_adding = True
                self._todo_editing = None
                self._todo_choosing = False
                self._todo_repeat = []
                self._scroll["todo"] = 0
                self.todo_input.clear()
                self.todo_time_input.clear()
            self._sync_overlays()
            if self._todo_adding:
                self.todo_input.setFocus(Qt.OtherFocusReason)
        elif action == "todo_edit":
            if self._todo_adding or self._todo_editing is not None:
                self._todo_adding = False
                self._todo_editing = None
                self._todo_choosing = False
                self._todo_repeat = []
                self.todo_input.clear()
                self.todo_time_input.clear()
            elif len(self.productivity.todos) == 1:
                self._todo_pick(self.productivity.display_order()[0])
            else:
                self._todo_choosing = not self._todo_choosing
            self._sync_overlays()
            self.update()
        elif action == "todo_pick":
            self._todo_pick(int(arg))
            self._sync_overlays()
            self.update()
        elif action == "todo_save":
            self._todo_submit()
        elif action == "todo_detail":
            self._todo_detail = int(arg)
            self.update()
        elif action == "todo_back":
            self._todo_detail = None
            self.update()
        elif action == "todo_repeat":
            day = int(arg)
            if day in self._todo_repeat:
                self._todo_repeat.remove(day)
            else:
                self._todo_repeat.append(day)
            self.update()
        elif action == "todo_toggle":
            self.productivity.toggle_todo(int(arg))
            self._apply_geometry(animate=True)
        elif action == "todo_remove":
            self.productivity.remove_todo(int(arg))
            self._todo_detail = None
            self._apply_geometry(animate=True)
        elif action == "todo_clear":
            if self._arm_confirm("todo_clear"):
                self.productivity.clear_done_todos()
                self._todo_detail = None
                self._apply_geometry(animate=True)
        elif action == "meeting_accept":
            self._resolve_meeting(True)
        elif action == "meeting_reject":
            self._resolve_meeting(False)
        elif action == "water":
            amount = int(arg)
            if self.productivity.add_water(amount):
                self._pet_until = time.monotonic() + 2.0
                if amount > 0:
                    self._ack_water(False)
        elif action == "water_undo":
            self.productivity.undo_water()
            self.update()
        elif action == "water_remind":
            remind = not self.cfg.get("water_remind", True)
            self._water_due = time.monotonic() + self._water_interval()
            if remind:
                self._water_pending = False
            self.option_change.emit("water_remind", remind)
        elif action == "water_ack":
            self._ack_water(False)
        elif action == "water_drink":
            self._ack_water(True)
        elif action == "focus_phase":
            self.focus["phase"] = arg
            self.focus["running"] = False
            self._focus_done = False
            self._focus_reset()
            self._drop_alert("focus")
            self._apply_geometry(animate=True)
        elif action == "focus_toggle":
            if self.focus["remaining"] <= 0:
                self._focus_reset()
            self._focus_done = False
            self._drop_alert("focus")
            self.focus["running"] = not self.focus["running"]
            self._apply_geometry(animate=True)
        elif action == "focus_reset":
            self._focus_done = False
            self._focus_reset()
            self._drop_alert("focus")
            self._apply_geometry(animate=True)
        elif action == "mail_refresh":
            if not self._refreshing("mail"):
                self._mail_refresh_until = time.monotonic() + 15.0
                if hasattr(self, "mail_refresh"):
                    self.mail_refresh()
        elif action == "mail_open":
            self._mail_detail = int(arg)
            items = self.mail.get("items") or []
            if 0 <= self._mail_detail < len(items):
                item = items[self._mail_detail]
                self._mail_mark_read(item)
                if (self._mail_sync_enabled() and item.get("uid")
                        and not item.get("seen", False)):
                    self._mail_op_action = "seen"
                    self._mail_op_key = self._mail_key(item)
                    self._mail_op_message = "正在同步已读…"
                    self._mail_op_until = time.monotonic() + 15.0
                    self._mail_op_token = "textTertiary"
                    self.mail_action.emit("seen", item["uid"])
        elif action == "mail_back":
            self._mail_detail = None
        elif action == "mail_full":
            item = self._current_mail()
            if item:
                self._open_mail_reader(item)
        elif action == "mail_filter":
            self._mail_filter = arg if arg in ("all", "unread") else "all"
            self._mail_detail = None
            self._scroll["mail"] = 0
        elif action == "mail_read":
            item = self._current_mail()
            if item:
                self._mail_mark_read(item)
                if self._mail_sync_enabled() and item.get("uid"):
                    self._mail_op_action = "seen"
                    self._mail_op_key = self._mail_key(item)
                    self._mail_op_message = "正在同步已读…"
                    self._mail_op_until = time.monotonic() + 15.0
                    self._mail_op_token = "textTertiary"
                    self.mail_action.emit("seen", item["uid"])
                self.update()
        elif action == "mail_unread":
            item = self._current_mail()
            if item and self._mail_sync_enabled() and item.get("uid"):
                self._mail_read.discard(self._mail_key(item))
                self._mail_op_action = "unseen"
                self._mail_op_key = self._mail_key(item)
                self._mail_op_message = "正在同步未读…"
                self._mail_op_until = time.monotonic() + 15.0
                self._mail_op_token = "textTertiary"
                self.mail_action.emit("unseen", item["uid"])
                self.update()
        elif action == "mail_read_all":
            items = [item for item in (self.mail.get("items") or [])
                     if self._mail_key(item) not in self._mail_hidden
                     and self._mail_unread(item)]
            for item in items:
                self._mail_mark_read(item)
            if self._mail_sync_enabled():
                self._mail_op_action = "all_seen"
                self._mail_op_key = None
                self._mail_op_message = "正在同步全部已读…"
                self._mail_op_until = time.monotonic() + 15.0
                self._mail_op_token = "textTertiary"
                self.mail_action.emit("all_seen", None)
            self.update()
        elif action == "mail_delete":
            item = self._current_mail()
            if item:
                key = self._mail_key(item)
                if not self._arm_confirm(
                        "mail_delete:" + self._mail_confirm_key(key)):
                    self.update()
                elif self._mail_sync_enabled() and item.get("uid"):
                    self._mail_pending_delete = key
                    self._mail_op_action = "trash"
                    self._mail_op_message = "正在移到邮箱回收站…"
                    self._mail_op_until = time.monotonic() + 15.0
                    self._mail_op_token = "textTertiary"
                    self.mail_action.emit("trash", item["uid"])
                    self.update()
                else:
                    self._mail_hidden.add(key)
                    self._mail_detail = None
                    self._mail_op_message = "已在本机隐藏（未改动邮箱）"
                    self._mail_op_until = time.monotonic() + 5.0
                    self._mail_op_token = "success"
                    self.update()
        elif action == "calendar_refresh":
            if not self._refreshing("calendar"):
                self._calendar_refresh_until = time.monotonic() + 15.0
                if hasattr(self, "calendar_refresh"):
                    self.calendar_refresh()
        elif action == "quota_refresh":
            if not self._refreshing("quota"):
                self._quota_refresh_until = time.monotonic() + 15.0
                if callable(self.quota_refresh):
                    self.quota_refresh()
                self.update()
        elif action == "stock_refresh":
            if not self._refreshing("stock"):
                self._stock_refresh_until = time.monotonic() + 15.0
                if callable(self.stock_refresh):
                    self.stock_refresh()
                self.update()
        elif action == "quota_pick":
            self.quota_selected = str(arg or "")
            self.update()
        elif action == "copy":
            text = str(arg or "")
            QGuiApplication.clipboard().setText(text)
            self._copied_text = text
            self._copy_until = time.monotonic() + 1.6
            self._pet_until = time.monotonic() + 1.5
        elif action == "clip_remove":
            self.productivity.remove_clip(int(arg))
        elif action == "clip_pin":
            self.productivity.toggle_pin(int(arg))
        elif action == "clips_clear":
            if self._arm_confirm("clips_clear"):
                self.productivity.clear_clips()
        elif action == "shelf_add":
            paths, _ = QFileDialog.getOpenFileNames(self, "放进置物架")
            for path in paths:
                self.productivity.add_shelf(path)
            self.set_tools_page("shelf")
        elif action == "shelf_open":
            if os.path.exists(str(arg)):
                subprocess.Popen(["xdg-open", str(arg)])
        elif action == "shelf_remove":
            index = int(arg)
            self.productivity.remove_shelf(index)
        elif action == "shelf_clear":
            if self._arm_confirm("shelf_clear"):
                self.productivity.clear_shelf()
        elif action == "notify_clear":
            if self._arm_confirm("notify_clear"):
                self.notifications = []
                self._unread = 0
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ox, oy = self._window_origin()
        p.translate(-ox, -oy)
        path = render.surface_path(self.shape)
        shadow = geometry.smoothstep(0.1, 0.9, self.progress)
        if shadow > 0.01:
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, int(46 * shadow)))
            p.drawRoundedRect(self.shape.rect.adjusted(0, 3, 0, 6),
                              geometry.PANEL_RADIUS, geometry.PANEL_RADIUS)
            p.restore()
        render.paint_surface(p, path, self.theme)
        if self.progress < 0.999:
            p.save()
            p.setClipPath(path)
            p.setOpacity(1.0 - geometry.smoothstep(0.0, 0.18, self.progress))
            self._paint_content(p)
            p.restore()
        if self.progress > 0.0:
            p.save()
            p.setClipPath(path)
            p.setOpacity(geometry.smoothstep(0.50, 0.97, self.progress))
            self._paint_details(p)
            p.restore()
        p.end()

    def _paint_content(self, p):
        theme = self.theme
        base = self.base
        self._compact_hits = []
        if base.style == "line":
            ratio, token = self._line_status()
            track = theme.color("indicator")
            if theme.material.get("kind") != "opaque":
                track.setAlphaF(0.60)
            p.fillRect(base.rect, track)
            fill_w = max(base.rect.height(), base.rect.width() * ratio)
            tip = QRectF(base.rect.left(), base.rect.top(),
                         fill_w, base.rect.height())
            p.fillRect(tip, theme.color(token))
            return

        r = QRectF(self.shape.rect)
        scale = base.scale
        inset = base.inset
        cy = r.center().y()
        left, right = r.left() + inset, r.right() - inset
        gap = 6 * scale
        gauge = 19 * scale
        x = left

        level = self._battery_level()
        clock_text = self._clock_text(datetime.now())
        clock_px = 13.5 * scale
        clock_w = render.text_width(clock_text, clock_px, QFont.DemiBold)
        bat_w = render.BATTERY_W * scale if level is not None else 0.0
        bat_x = right - bat_w
        clock_x = bat_x - (gap if bat_w else 0) - clock_w

        parts = self._compact_parts(scale)
        weather = (self._weather_slot(scale)
                   if any(kind == "weather" for kind, _, _ in parts) else None)
        weather_x = clock_x - gap - (weather["width"] if weather else 0.0)
        content_right = weather_x if weather else clock_x
        p.save()
        p.setClipRect(QRectF(left - 2, r.top(),
                             max(0.0, content_right - left + 2), r.height()))
        for kind, width, page in parts:
            if kind == "weather":
                continue
            if kind in ("cpu", "mem"):
                value = self.data.get("cpu" if kind == "cpu" else "memory")
                render.paint_ring_gauge(
                    p, x, cy, gauge, value or 0.0,
                    "--" if value is None else f"{int(value * 100)}",
                    theme, "accent" if kind == "cpu" else "textPrimary")
            elif kind == "pet":
                render.paint_pet(p, x, cy, 15 * scale, theme, self._pet_mood(),
                                 time.monotonic())
            elif kind == "music":
                music_text, info = self._compact_music_text()
                if self.music.get("status") == "Playing":
                    render.paint_equalizer(p, x, cy, theme,
                                           time.monotonic() * 4.0, scale)
                else:
                    render.paint_play(p, x + 2, cy, 12 * scale, theme)
                title_x = x + 22 * scale + 4 * scale
                room = x + width - title_x
                if info:
                    self._paint_lyric(
                        p, QRectF(title_x, r.top(), room, r.height()),
                        render.elide(music_text, 11 * scale, room,
                                     QFont.DemiBold), 11 * scale)
                else:
                    render.paint_marquee(
                        p, QRectF(title_x, r.top(), room, r.height()), music_text,
                        theme, 11 * scale,
                        self._marquee_elapsed("compact-title", music_text),
                        QFont.DemiBold, token="textPrimary")
            elif kind == "notice":
                notice = self._notice or {}
                kind_name = notice.get("kind")
                label = render.elide(self._notice_text(notice), 10.5 * scale,
                                     width - 22 * scale)
                ease = max(0.0, min(
                    1.0, (time.monotonic() - self._notice_at) / NOTICE_FADE))
                p.save()
                p.setOpacity(p.opacity() * (0.3 + 0.7 * ease))
                p.translate(-2.0 * (1.0 - ease), 0.0)
                if kind_name == "focus":
                    render.paint_tomato(p, x + 9 * scale, cy, 15 * scale, theme,
                                        "danger")
                elif kind_name == "mail":
                    render.paint_envelope(p, x + 6 * scale, cy, 14 * scale,
                                          theme, "accent")
                elif kind_name == "meeting":
                    render.paint_checklist(p, x + 1 * scale, cy, 15 * scale,
                                           theme, "accent")
                else:
                    render.paint_drop(p, x + 9 * scale, cy, 14 * scale,
                                      theme, "accent")
                render.paint_text(
                    p, QRectF(x + 22 * scale, r.top(), width - 22 * scale,
                              r.height()),
                    label, theme, 10.5 * scale, QFont.DemiBold,
                    Qt.AlignLeft | Qt.AlignVCenter,
                    token="accent" if kind_name in ("mail", "water", "meeting") else
                    "textPrimary")
                p.restore()
                chip = QRectF(x, cy - 9 * scale, width, 18 * scale)
                self._compact_hits.append((chip, "notice"))
            else:
                chip = QRectF(x, cy - 9 * scale, width, 18 * scale)
                if kind == "mail":
                    if time.monotonic() < self._mail_pulse_until:
                        alpha = 0.10 + 0.10 * (0.5 + 0.5 * math.sin(
                            time.monotonic() * 7.0))
                        p.save()
                        p.setPen(Qt.NoPen)
                        color = theme.color("accent")
                        color.setAlphaF(alpha)
                        p.setBrush(color)
                        p.drawRoundedRect(chip, 7 * scale, 7 * scale)
                        p.restore()
                    render.paint_envelope(p, x + 3 * scale, cy, 13 * scale,
                                          theme, "accent")
                    token = "accent"
                    label = self._mail_badge()
                elif kind == "focus":
                    remaining = max(0, self.focus["remaining"])
                    token = "success" if self.focus["phase"] != "focus" else "danger"
                    render.paint_tomato(p, x + 8 * scale, cy, 14 * scale,
                                        theme, token)
                    label = ("休息" if self.focus["phase"] == "rest" else "专注") \
                        if self._focus_done and not self.focus["running"] else \
                        f"{remaining // 60:02d}:{remaining % 60:02d}"
                elif kind == "activity":
                    token = self._activity_token()
                    render.paint_spark(p, x + 7 * scale, cy, 12 * scale, theme,
                                       token)
                    label = render.elide(str(self.activity.get("label") or ""),
                                         9.5 * scale, width - 18 * scale)
                elif kind == "water":
                    token = "accent"
                    render.paint_drop(p, x + 8 * scale, cy, 14 * scale,
                                      theme, "accent")
                    label = "喝水"
                elif kind == "meeting":
                    token = "accent"
                    render.paint_checklist(p, x + 1 * scale, cy, 15 * scale,
                                           theme, "accent")
                    label = "会议待办"
                elif kind == "stock":
                    token = self._stock_token()
                    label = self._stock_chip_text()
                    render.paint_text(
                        p, QRectF(x + 4 * scale, r.top(), width - 4 * scale,
                                  r.height()),
                        label, theme, 9.5 * scale, QFont.DemiBold,
                        Qt.AlignLeft | Qt.AlignVCenter, token=token)
                    self._compact_hits.append((chip, page))
                    x += width + gap
                    continue
                else:
                    token = "success"
                    render.paint_checklist(p, x + 1 * scale, cy, 14 * scale,
                                           theme, token)
                    done_today, total_today = self.productivity.progress()
                    label = str(max(0, total_today - done_today))
                render.paint_text(
                    p, QRectF(x + 18 * scale, r.top(), width - 18 * scale,
                              r.height()),
                    label, theme, 9.5 * scale, QFont.DemiBold,
                    Qt.AlignLeft | Qt.AlignVCenter, token=token)
                self._compact_hits.append((chip, page))
            x += width + gap

        p.restore()
        if weather:
            render.paint_weather_icon(p, weather_x, cy, weather["icon"],
                                      weather["kind"], theme)
            render.paint_text(
                p, QRectF(weather_x + weather["icon"] + weather["gap"],
                          r.top(),
                          weather["width"] - weather["icon"] - weather["gap"] + 1,
                          r.height()),
                weather["text"], theme, weather["text_px"], QFont.DemiBold,
                Qt.AlignLeft | Qt.AlignVCenter, token="textPrimary")
            self._compact_hits.append((
                QRectF(weather_x, r.top(), weather["width"] + 2 * scale,
                       r.height()), "weather"))
        render.paint_text(p, QRectF(clock_x, r.top(), clock_w + 1, r.height()),
                          clock_text, theme, clock_px, QFont.DemiBold,
                          Qt.AlignRight | Qt.AlignVCenter, token="clock")
        if level is not None:
            render.paint_battery(p, bat_x, cy, level, theme,
                                 self.data.get("charging", False), scale)

    def _line_status(self):
        """Fill ratio and theme token for the collapsed indicator bar."""
        if self.focus["running"] and self.focus["total"] > 0:
            used = 1.0 - self.focus["remaining"] / self.focus["total"]
            return max(0.0, min(1.0, used)), "accent"
        if self._focus_done:
            return 1.0, "success"
        music = self._music_state()
        if (music["present"] and music["length"] > 0
                and (music["playing"] or music["paused"])):
            ratio = max(0.0, min(1.0, music["position"] / music["length"]))
            return ratio, "accent" if music["playing"] else "equalizer"
        if self.cfg.get("show_monitor", True):
            values = [value for value in (
                self.data.get("cpu"), self.data.get("memory"),
                self.data.get("disk")) if value is not None]
            if values:
                ratio = max(0.0, min(1.0, max(values)))
                token = ("danger" if ratio >= 0.92 else
                         "warning" if ratio >= 0.8 else "accent")
                return ratio, token
        return 0.38, "accent"

    def _paint_lyric(self, p, rect, text, px):
        ease = self._lyric_ease()
        if ease >= 1.0:
            render.paint_text(p, rect, text, self.theme, px, QFont.DemiBold,
                              Qt.AlignLeft | Qt.AlignVCenter,
                              token="textPrimary")
            return
        p.save()
        p.setClipRect(rect)
        p.setOpacity(p.opacity() * ease)
        render.paint_text(p, rect.translated(0.0, 3.0 * (1.0 - ease)), text,
                          self.theme, px, QFont.DemiBold,
                          Qt.AlignLeft | Qt.AlignVCenter, token="textPrimary")
        p.restore()

    def _paint_details(self, p):
        theme = self.theme
        self._hits = []
        self._tab_hits = []
        self._tools_hits = []
        self._list_rect = None
        self._paint_chrome(p)
        paint = {
            "music": self._paint_music_page,
            "todo": self._paint_todo,
            "focus": self._paint_focus,
            "water": self._paint_water,
            "mail": self._paint_mail,
            "calendar": self._paint_calendar,
            "quota": self._paint_quota,
            "stock": self._paint_stock,
            "weather": self._paint_weather,
            "monitor": self._paint_monitor,
            "tools": self._paint_tools,
        }[self.page]
        elapsed = time.monotonic() - self._page_at
        if elapsed < 0.24:
            share = elapsed / 0.24
            ease = 1.0 - (1.0 - share) ** 3
            p.save()
            p.setOpacity(p.opacity() * (0.55 + 0.45 * ease))
            p.translate(self._page_dir * 10.0 * (1.0 - ease), 0)
            paint(p)
            p.restore()
        else:
            paint(p)
        self._sync_overlays()

    def _paint_chrome(self, p):
        theme = self.theme
        panel = self.open_shape.rect
        title = PAGE_TITLE.get(self.page, "")
        if title:
            render.paint_text(
                p, QRectF(panel.left() + 15, panel.top() + 12, 150, 17),
                title, theme, 14, QFont.Bold,
                Qt.AlignLeft | Qt.AlignVCenter, token="textPrimary")

        now = datetime.now()
        clock = self._panel_clock(now)
        date = self._panel_date(now)
        clock_w = render.text_width(clock, 13, QFont.DemiBold)
        date_w = render.text_width(date, 9.5)
        gap = 8.0
        gx = panel.center().x() - (clock_w + gap + date_w) / 2
        head = QFontMetricsF(render.ui_font(14, QFont.Bold))
        baseline = panel.top() + 20.5 + (head.ascent() - head.descent()) / 2
        p.save()
        p.setFont(render.ui_font(13, QFont.DemiBold))
        p.setPen(theme.color("textPrimary"))
        p.drawText(QPointF(gx, baseline), clock)
        p.setFont(render.ui_font(9.5))
        p.setPen(theme.color("textSecondary"))
        p.drawText(QPointF(gx + clock_w + gap, baseline), date)
        p.restore()

        gear = QRectF(panel.right() - 40, panel.top() + 5, 28, 28)
        render.paint_gear(p, gear.center().x(), gear.center().y(), 15, theme)
        self._hits.append((gear, "settings", None))

        cy = panel.top() + 68
        left_arrow = QRectF(panel.left() + 8, cy - 13, 26, 26)
        right_arrow = QRectF(panel.right() - 34, cy - 13, 26, 26)
        render.paint_chevron(p, panel.left() + 21, cy, -1, theme, 0.8)
        render.paint_chevron(p, panel.right() - 21, cy, 1, theme, 0.8)
        self._hits.append((left_arrow, "nav", -1))
        self._hits.append((right_arrow, "nav", 1))

        slot = 10.0
        pages = self._pages()
        total = slot * len(pages)
        x = panel.center().x() - total / 2
        y = panel.bottom() - 7.2
        now = time.monotonic()
        mail_unread = any(
            self._mail_unread(item)
            and self._mail_key(item) not in self._mail_hidden
            for item in (self.mail.get("items") or []))
        for page, _ in pages:
            active = page == self.page
            color = theme.color("accent" if active else "textTertiary")
            if not active:
                color.setAlphaF(0.55)
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(x + slot / 2 - 2, y - 2, 4, 4), 2, 2)
            dot = ("danger" if page == "tools" and self._unread else
                   "danger" if page == "focus" and self._focus_done else
                   "accent" if page == "water" and self._water_pending else
                   "accent" if page == "todo" and self._meeting_offer else
                   "accent" if page == "mail" and mail_unread else None)
            if dot:
                render.paint_dot(p, x + slot / 2, y - 7, 2.5, theme, dot)
            p.restore()
            self._hits.append((QRectF(x, y - 12, slot, 24), "page", page))
            x += slot

    def _pet_mood(self):
        if self.music and self.music.get("status") == "Playing":
            return "music"
        if self.focus["running"]:
            return "focus"
        if time.monotonic() < self._pet_until:
            return "happy"
        return "awake"

    def _paint_music_page(self, p):
        state = self._music_state()
        self._paint_music(p, state)
        if state["present"]:
            return
        self._paint_status_cells(p)
        volume = self.data.get("volume")
        if self._volume_open and volume is not None:
            self._paint_volume_popup(p, volume)

    def _paint_status_cells(self, p):
        """Idle music page doubles as the resource readout."""
        theme = self.theme
        area = self._content_rect()
        mem = self.data.get("memory")
        cpu = self.data.get("cpu")
        bat = self.data.get("battery")
        charging = bool(self.data.get("charging"))
        down = format_rate(self.data.get("net_down"))
        up = format_rate(self.data.get("net_up"))
        online = self.data.get("online")
        network = ("离线" if online is False else
                   "不可用" if down == "--" and up == "--" else
                   f"↓{down} ↑{up}" if down != "--" else "在线")
        cells = [
            ("CPU", "--" if cpu is None else f"{int(cpu * 100)}%",
             _meter_token(cpu)),
            ("内存", "--" if mem is None else f"{int(mem * 100)}%",
             _meter_token(mem)),
            ("电量", "--" if bat is None else f"{int(bat * 100)}%",
             "success" if charging else
             "danger" if bat is not None and bat <= 0.15 else
             "textPrimary" if bat is not None else "textTertiary"),
            ("网络", network, "danger" if online is False else
             "textTertiary" if network == "不可用" else "textPrimary"),
        ]
        strip = area.bottom() - 33
        p.save()
        p.setPen(QPen(theme.color("hairline"), 1))
        p.drawLine(QPointF(area.left(), strip), QPointF(area.right(), strip))
        p.restore()
        unit = area.width() / 5
        for index, (label, value, token) in enumerate(cells):
            left = area.left() + index * unit
            width = unit * (5 - index) if index == len(cells) - 1 else unit
            pad = 0.0 if index == 0 else 12.0
            if index:
                p.save()
                p.setPen(QPen(theme.color("hairline"), 1))
                p.drawLine(QPointF(left, strip + 5),
                           QPointF(left, area.bottom() - 3))
                p.restore()
            render.paint_text(p, QRectF(left + pad, strip + 5,
                                        width - pad - 6, 11),
                              label, theme, 9, token="textTertiary")
            render.paint_text(p, QRectF(left + pad, strip + 16,
                                        width - pad - 6, 15),
                              render.elide(value, 12, width - pad - 6,
                                           QFont.DemiBold),
                              theme, 12, QFont.DemiBold, token=token)

    def _paint_todo(self, p):
        theme = self.theme
        area = self._content_rect()
        card = self._todo_card_rect()
        today = datetime.now().date()
        done, total = self.productivity.progress(today)
        order = self.productivity.display_order(today)
        editing = self._todo_adding or self._todo_editing is not None
        detail = self._todo_detail
        if (detail is not None and not editing
                and 0 <= detail < len(self.productivity.todos)
                and self._todo_details(self.productivity.todos[detail])):
            self._paint_todo_detail(p, area,
                                    self.productivity.todos[detail])
            return
        self._todo_detail = None

        render.paint_text(p, QRectF(area.left(), area.top() - 4, 46, 36),
                          str(done), theme, 29, QFont.Bold,
                          token="success" if done and done == total else "textPrimary")
        render.paint_text(p, QRectF(area.left() + 24, area.top() + 8, 60, 18),
                          f"/{total}", theme, 13, QFont.DemiBold,
                          token="textSecondary")
        render.paint_text(p, QRectF(area.left(), area.top() + 30, 90, 12),
                          "今日完成", theme, 9.5, token="textSecondary")
        add = QRectF(area.left(), area.top() + 44, 72, 20)
        render.paint_button(p, add, "+ 添加", theme,
                            active=not editing)
        self._hits.append((add, "todo_add", None))
        edit = QRectF(area.left(), add.bottom() + 4, 72, 20)
        chosen = editing or self._todo_choosing
        render.paint_button(p, edit, "取消" if chosen else "改一下", theme,
                            active=chosen)
        self._hits.append((edit, "todo_edit", None))

        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("fill"))
        p.drawRoundedRect(card, 10, 10)
        p.restore()

        offer = self._meeting_offer
        if offer is not None and not editing:
            render.paint_text(p, QRectF(card.left() + 8, card.top() + 7,
                                        card.width() - 16, 14),
                              "识别到会议邀请 · 是否创建待办", theme, 9.5,
                              QFont.DemiBold, token="accent")
            render.paint_text(p, QRectF(card.left() + 8, card.top() + 24,
                                        card.width() - 16, 14),
                              render.elide(offer["text"], 9.5,
                                          card.width() - 16), theme, 9.5)
            note = (f"{offer['remind']} 提醒" if offer["remind"]
                    else "会议时间已过 · 只记待办")
            if offer.get("code"):
                note += f" · 会议号 {offer['code']}"
            render.paint_text(p, QRectF(card.left() + 8, card.top() + 40,
                                        card.width() - 16, 12),
                              note, theme, 9,
                              QFont.Normal,
                              Qt.AlignLeft | Qt.AlignVCenter,
                              token="textTertiary")
            accept = QRectF(card.left() + 8, card.bottom() - 30, 76, 23)
            render.paint_button(p, accept, "创建待办", theme, active=True,
                                px=9.5)
            self._hit(accept, "meeting_accept")
            reject = QRectF(accept.right() + 8, accept.top(), 48, 23)
            render.paint_button(p, reject, "忽略", theme, px=9.5)
            self._hit(reject, "meeting_reject")
            return

        if not editing:
            label = f"今日 {total} 项"
            if len(order) > 3:
                label += " · 滚轮"
            render.paint_text(p, QRectF(card.left() + 8, card.top() + 1,
                                        card.width() - 76, 12),
                              label, theme, 9, token="textTertiary")
            if done and total:
                armed = self._confirming("todo_clear")
                clear = QRectF(card.right() - 64, card.top() + 1, 58, 12)
                render.paint_text(
                    p, clear, "确认清空?" if armed else "清空已完成", theme,
                    9, QFont.Normal, Qt.AlignRight | Qt.AlignVCenter,
                    token="danger" if armed else "textTertiary")
                self._hits.append((clear, "todo_clear", None))

        if not order and not editing:
            render.paint_checklist(p, card.center().x() - 14,
                                   card.center().y() - 10, 28, theme,
                                   "textTertiary")
            render.paint_text(p, QRectF(card.left(), card.center().y() + 10,
                                        card.width(), 14),
                              "今天还没有安排", theme, 9, QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
            return

        if editing:
            save = QRectF(card.right() - 23, card.top() + 3, 18, 19)
            render.paint_button(p, save, "✓", theme, active=True, px=9)
            self._hits.append((save, "todo_save", None))
            render.paint_text(p, QRectF(card.left() + 7, card.top() + 24,
                                        25, 15),
                              "重复", theme, 9, token="textTertiary")
            for day in range(7):
                chip = QRectF(card.left() + 32 + day * 20, card.top() + 24,
                              18, 15)
                render.paint_button(p, chip, WEEKDAYS_ZH[day], theme,
                                    active=day in self._todo_repeat, px=9)
                self._hits.append((chip, "todo_repeat", day))
            render.paint_text(p, QRectF(card.left() + 7, card.top() + 41,
                                        25, 15),
                              "提醒", theme, 9, token="textTertiary")

        visible = 1 if editing else 3
        rows_order = [index for index in order if index != self._todo_editing]
        offset = min(self._scroll["todo"],
                     max(0, len(rows_order) - visible))
        self._list_rect = card
        top_y = card.top() + (61 if editing else 15)
        row_h = 22 if editing else 23
        for row_index, index in enumerate(rows_order[offset:offset + visible]):
            item = self.productivity.todos[index]
            y = top_y + row_index * row_h
            row = QRectF(card.left() + 4, y, card.width() - 8, row_h - 1)
            due = self.productivity.todo_due(item, today)
            item_done = self.productivity.todo_done(item, today)
            if self._todo_choosing:
                render.paint_pencil(p, row.left() + 8, row.center().y(), 10,
                                    theme, "accent")
            else:
                box = QRectF(row.left() + 3, row.center().y() - 5, 10, 10)
                p.save()
                p.setPen(QPen(theme.color("outline"), 1.2))
                p.setBrush(theme.color("success") if item_done else Qt.NoBrush)
                p.drawEllipse(box)
                if item_done:
                    p.setPen(QPen(theme.color("surface"), 1.4))
                    p.drawLine(QPointF(box.left() + 2.4, row.center().y()),
                               QPointF(box.center().x(), box.bottom() - 2.6))
                    p.drawLine(QPointF(box.center().x(), box.bottom() - 2.6),
                               QPointF(box.right() - 2.0, row.top() + 2.8))
                p.restore()
            tag = " · ".join(part for part in (
                repeat_tag(item.get("repeat")), item.get("remind") or "")
                if part)
            tag_w = (render.text_width(tag, 9) + 5) if tag else 0.0
            reserve = 32 if self._todo_choosing else 16
            text_w = max(24.0, row.width() - 24 - tag_w - reserve)
            text = render.elide(item["text"], 9.5, text_w)
            token = ("textTertiary" if item_done or not due
                     else "textPrimary")
            tx = row.left() + 18
            render.paint_text(p, QRectF(tx, y, text_w, row_h - 1), text, theme,
                              9.5, token=token)
            tw = render.text_width(text, 9.5)
            if item_done:
                p.save()
                p.setPen(QPen(theme.color("textTertiary"), 1))
                p.drawLine(QPointF(tx, row.center().y()),
                           QPointF(tx + tw, row.center().y()))
                p.restore()
            if tag:
                render.paint_text(
                    p, QRectF(tx + tw + 5, y, tag_w, row_h - 1), tag, theme,
                    9, QFont.Normal, Qt.AlignLeft | Qt.AlignVCenter,
                    token="accent" if due else "textTertiary")
            if self._todo_choosing:
                render.paint_text(p, QRectF(row.right() - 28, y, 26, row_h - 1),
                                  "修改", theme, 9, QFont.Normal,
                                  Qt.AlignRight | Qt.AlignVCenter,
                                  token="accent")
                self._hits.append((row, "todo_pick", index))
            else:
                close = QRectF(row.right() - 16, y + 4, 14, 15)
                render.paint_close(p, close.center().x(), close.center().y(),
                                   6, theme)
                if self._todo_details(item):
                    # 有会议细节的行：点文字看详情，勾完成只点左边的圆圈
                    render.paint_chevron(p, row.right() - 26, row.center().y(),
                                         1, theme, 0.7)
                    self._hits.append(
                        (QRectF(row.left(), y, 20, row_h - 1), "todo_toggle",
                         index))
                    self._hits.append(
                        (QRectF(20 + row.left(), y, row.width() - 38, row_h - 1),
                         "todo_detail", index))
                elif due or item.get("remind_on"):
                    self._hits.append((row.adjusted(0, 0, -18, 0),
                                       "todo_toggle", index))
                self._hits.append((close, "todo_remove", index))
        if len(rows_order) > visible:
            self._paint_scrollbar(p, card.adjusted(0, 14, -2, -4), offset,
                                  len(rows_order), visible)

    def _todo_details(self, item):
        """Fields worth a detail view: meeting number, room, join link."""
        meeting_info = item.get("meeting") or {}
        rows = []
        day = item.get("remind_on") or ""
        clock = item.get("remind") or ""
        if day or clock:
            rows.append(("时间", f"{day} {clock}".strip(), ""))
        for label, key in (("会议号", "code"), ("地点", "place"),
                           ("链接", "link")):
            value = meeting_info.get(key) or ""
            if value:
                rows.append((label, value, value))
        return rows

    def _paint_todo_detail(self, p, area, item):
        theme = self.theme
        rows = self._todo_details(item)
        back = QRectF(area.right() - 48, area.top() - 2, 48, 20)
        render.paint_button(p, back, "返回", theme, px=9)
        self._hits.append((back, "todo_back", None))
        index = self._todo_detail
        finished = self.productivity.todo_done(item)
        toggle = QRectF(back.left() - 56, area.top() - 2, 52, 20)
        render.paint_button(p, toggle, "取消完成" if finished else "完成",
                            theme, active=not finished, px=9)
        self._hits.append((toggle, "todo_toggle", index))
        head_w = toggle.left() - area.left() - 6
        render.paint_text(p, QRectF(area.left(), area.top() - 2, head_w, 20),
                          render.elide(item["text"], 10.5, head_w,
                                       QFont.DemiBold),
                          theme, 10.5, QFont.DemiBold)
        y = area.top() + 21
        label_w = 34.0
        copy_w = 40.0
        for label, value, copy in rows[:4]:
            room = area.width() - label_w - (copy_w + 4 if copy else 0)
            render.paint_text(p, QRectF(area.left(), y, label_w, 16), label,
                              theme, 9, token="textTertiary")
            render.paint_text(p, QRectF(area.left() + label_w, y, room, 16),
                              render.elide(value, 10, room), theme, 10)
            if copy:
                button = QRectF(area.right() - copy_w, y - 1, copy_w, 17)
                render.paint_button(p, button,
                                    "已复制" if self._copied(copy) else "复制",
                                    theme, active=self._copied(copy), px=9)
                self._hits.append((button, "copy", copy))
            y += 18

    def _paint_focus(self, p):
        theme = self.theme
        area = self._content_rect()
        total = max(1, self.focus["total"])
        elapsed = max(0.0, min(1.0, 1.0 - self.focus["remaining"] / total))
        resting = self.focus["phase"] != "focus"
        token = "success" if resting else "danger"
        cy = area.top() + 46
        render.paint_ring_gauge(p, area.left() + 4, cy, 56, elapsed,
                                "", theme, token)
        render.paint_tomato(p, area.left() + 32, cy, 22, theme, "danger")
        remaining = max(0, self.focus["remaining"])
        render.paint_text(p, QRectF(area.left() + 94, area.top() - 2, 200, 38),
                          f"{remaining // 60:02d}:{remaining % 60:02d}",
                          theme, 31, QFont.DemiBold,
                          token=token if resting else "textPrimary")
        status = ("计时中" if self.focus["running"] else
                  "待开始" if self._focus_done else
                  "已结束" if remaining == 0 else "已暂停")
        render.paint_text(p, QRectF(area.left() + 96, area.top() + 34, 210, 14),
                          f"{'休息' if resting else '专注'} · {status} · "
                          f"{total // 60} 分钟", theme, 9.5,
                          token="textSecondary")
        y = area.bottom() - 25
        for index, (phase, label) in enumerate((("focus", "专注"),
                                                ("rest", "休息"))):
            rect = QRectF(area.left() + 94 + index * 52, y, 48, 23)
            active = self.focus["phase"] == phase
            render.paint_button(p, rect, label, theme, active=active, px=9.5,
                                token="danger" if phase == "focus" and active else
                                "success" if active else None)
            self._hits.append((rect, "focus_phase", phase))
        toggle = QRectF(area.left() + 202, y, 58, 23)
        render.paint_button(p, toggle, "暂停" if self.focus["running"] else "开始",
                            theme, active=True, px=9.5)
        self._hits.append((toggle, "focus_toggle", None))
        reset = QRectF(area.left() + 264, y, 42, 23)
        render.paint_button(p, reset, "重置", theme, px=9.5)
        self._hits.append((reset, "focus_reset", None))

    def _paint_water(self, p):
        theme = self.theme
        area = self._content_rect()
        percent = self.productivity.water_percent()
        remind = bool(self.cfg.get("water_remind", True))
        ml = self.productivity.water_ml

        switch = QRectF(area.right() - 40, area.top() + 1, 38, 20)
        track = theme.color("accent") if remind else theme.color("track")
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(switch.adjusted(2, 1.5, -2, -1.5), 8.5, 8.5)
        knob_x = switch.right() - 13 if remind else switch.left() + 7
        p.setBrush(theme.color("surface"))
        p.drawEllipse(QPointF(knob_x, switch.center().y()), 7, 7)
        p.restore()
        render.paint_bell(p, knob_x, switch.center().y(), 9,
                          theme, "accent" if remind else "textTertiary")
        render.paint_text(p, QRectF(switch.left() - 28, switch.top(), 26, 20),
                          "提醒", theme, 9.5, QFont.Normal,
                          Qt.AlignRight | Qt.AlignVCenter,
                          token="textSecondary")
        self._hits.append((switch.adjusted(-26, -2, 2, 2), "water_remind",
                           None))

        liters = f"{ml / 1000.0:.1f}"
        render.paint_text(p, QRectF(area.left(), area.top() + 4, 58, 36),
                          liters, theme, 29, QFont.Bold, token="textPrimary")
        lw = render.text_width(liters, 29, QFont.Bold)
        render.paint_text(
            p, QRectF(area.left() + lw + 4, area.top() + 18, 78, 15),
            f"/ {WATER_GOAL / 1000.0:.1f} L", theme, 10, QFont.DemiBold,
            token="textSecondary")

        now = datetime.now()
        if self._water_pending:
            tail = "待确认"
        elif percent >= 1.0:
            tail = "已达标"
        elif not remind:
            tail = "提醒已关"
        elif not WATER_HOURS[0] <= now.hour < WATER_HOURS[1]:
            tail = f"{WATER_HOURS[0]}:00–{WATER_HOURS[1]}:00 外"
        else:
            due = now + timedelta(
                seconds=max(0.0, self._water_due - time.monotonic()))
            tail = f"下次 {due.strftime('%H:%M')}"
        render.paint_text(
            p, QRectF(area.left(), area.top() + 37, 250, 14),
            f"今日 {int(percent * 100)}% · {tail}", theme, 9.5,
            QFont.DemiBold if self._water_pending else QFont.Normal,
            token="accent" if self._water_pending else "textSecondary")
        render.paint_bar(p, QRectF(area.left(), area.top() + 54,
                                   228, 4), percent, theme, "accent")

        drink = QRectF(area.left(), area.bottom() - 27, 72, 24)
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("accent"))
        p.drawRoundedRect(drink, 12, 12)
        p.restore()
        render.paint_text(p, QRectF(drink.left(), drink.top(),
                                    drink.width(), drink.height()),
                          "喝一口", theme, 12, QFont.DemiBold,
                          Qt.AlignCenter, token="onAccent")
        self._hits.append((drink, "water_drink", None))
        if self._water_pending:
            side = QRectF(drink.right() + 10, drink.top(), 44, 24)
            render.paint_text(p, side, "稍后", theme, 9.5,
                              Qt.AlignCenter, token="textSecondary")
            self._hits.append((side, "water_ack", None))
        elif ml > 0:
            side = QRectF(drink.right() + 10, drink.top(), 44, 24)
            render.paint_text(p, side, "撤销", theme, 9.5,
                              Qt.AlignCenter, token="textSecondary")
            self._hits.append((side, "water_undo", None))
        reset = QRectF(area.right() - 44, area.bottom() - 27, 44, 24)
        render.paint_text(p, reset, "重置", theme, 9.5,
                          Qt.AlignCenter, token="textTertiary")
        self._hits.append((reset, "water", -ml))

    def _paint_mail(self, p):
        theme = self.theme
        area = self._content_rect()
        result = self.mail
        items = result.get("items") or []
        if self._mail_detail is not None and 0 <= self._mail_detail < len(items):
            item = items[self._mail_detail]
            if self._mail_key(item) not in self._mail_hidden:
                self._paint_mail_detail(p, area, item)
                return
            self._mail_detail = None
        visible = [(index, item) for index, item in enumerate(items)
                   if self._mail_key(item) not in self._mail_hidden]
        refreshing = self._refreshing("mail")
        unread = sum(1 for _, item in visible if self._mail_unread(item))
        filtered = [(index, item) for index, item in visible
                    if self._mail_filter != "unread" or self._mail_unread(item)]
        code_index = next((index for index, item in filtered
                           if str(item.get("code") or "")), None)
        has_card = code_index is not None and result.get("status") == "ok"
        list_x = area.left() + (144 if has_card else 0)
        op_active = time.monotonic() < self._mail_op_until
        refresh = QRectF(area.right() - 42, area.top() - 2, 42, 19)
        render.paint_button(p, refresh, "刷新中" if refreshing else "刷新",
                            theme, active=refreshing, px=9)
        self._hits.append((refresh, "mail_refresh", None))
        show_read_all = bool(unread) and not op_active
        if show_read_all:
            read_all = QRectF(refresh.left() - 48, area.top() - 2, 46, 19)
            render.paint_button(p, read_all, "全部已读", theme, px=9)
            self._hits.append((read_all, "mail_read_all", None))

        if op_active:
            status, token = self._mail_op_message, self._mail_op_token
        elif not has_card:
            status, token = ((("IMAP · 刷新中…", "textTertiary")) if refreshing
                             else self._status_line(result, "IMAP", "邮件"))
        else:
            status, token = "", "textTertiary"
        band_right = refresh.left() - 4
        status_right = band_right - (48 if show_read_all else 0)
        status_x = list_x + 112
        centered = False
        # 验证码卡片优先：列表列只剩 36px，成功和进行中改用短词，
        # 只有报错才借筛选按钮的整行位置，宁可截也不省
        narrow = bool(status) and status_right - status_x < render.text_width(status, 9)
        if narrow and token != "danger":
            status = "已同步" if token == "success" else "同步中"
            narrow = False
            # 短词右对齐只剩 4px 贴住刷新按钮，改成在筛选按钮和刷新之间居中
            band_left = list_x + 106
            status_x = band_left + (band_right - band_left
                                    - render.text_width(status, 9)) / 2.0
            status_right = status_x + render.text_width(status, 9)
            centered = True
        if narrow:
            status_x = list_x
        else:
            for index, (key, label) in enumerate((
                    ("all", f"全部 {len(visible)}"),
                    ("unread", f"未读 {unread}"))):
                tab = QRectF(list_x + index * 52, area.top() - 2, 50, 19)
                render.paint_button(p, tab, label, theme,
                                    active=self._mail_filter == key, px=9)
                self._hits.append((tab, "mail_filter", key))

        if status:
            status_width = status_right - status_x
            render.paint_text(
                p, QRectF(status_x, area.top() - 2,
                          max(0.0, status_width), 19),
                render.elide(status, 9, max(0.0, status_width)),
                theme, 9, QFont.Normal,
                (Qt.AlignLeft if centered else Qt.AlignRight) | Qt.AlignVCenter,
                token=token if token in ("danger", "success") else "textTertiary")

        if result.get("status") != "ok" or not visible:
            message = ("在 设置 → 邮件 填写 IMAP 账号" if result.get("status") == "unconfigured"
                       else "收件箱为空" if result.get("status") == "ok"
                       else result.get("error", "读取失败"))
            render.paint_text(p, QRectF(list_x, area.top() + 20,
                                        area.right() - list_x, 34),
                              render.elide(message, 9, area.width()), theme, 9,
                              QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
            if result.get("status") == "unconfigured":
                go = QRectF(area.center().x() - 32, area.top() + 54, 64, 22)
                render.paint_button(p, go, "去设置", theme, active=True, px=9)
                self._hits.append((go, "settings", "mail"))
            return

        if has_card:
            item = items[code_index]
            card = QRectF(area.left(), area.top() + 4, 136,
                          area.height() - 4)
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("fill"))
            p.drawRoundedRect(card, 10, 10)
            p.restore()
            code = str(item.get("code") or "")
            render.paint_text(p, QRectF(card.left() + 8, card.top() + 3,
                                        40, 12), "验证码", theme, 9,
                              token="textTertiary")
            render.paint_text(
                p, QRectF(card.left() + 48, card.top() + 3,
                          card.width() - 56, 12),
                render.elide(self._sender_name(item.get("sender")), 9,
                             card.width() - 56, QFont.DemiBold),
                theme, 9, QFont.DemiBold,
                Qt.AlignRight | Qt.AlignVCenter, token="textSecondary")
            code_px = 22.0
            while code_px > 12 and render.text_width(code, code_px,
                                                     QFont.Bold) > card.width() - 16:
                code_px -= 1
            render.paint_text(p, QRectF(card.left() + 8, card.top() + 15,
                                        card.width() - 16, 28),
                              code, theme, code_px, QFont.Bold,
                              token="success")
            render.paint_text(
                p, QRectF(card.left() + 8, card.top() + 43,
                          card.width() - 16, 13),
                render.elide(item.get("subject", ""), 9, card.width() - 16),
                theme, 9, token="textSecondary")
            render.paint_text(
                p, QRectF(card.left() + 8, card.bottom() - 15,
                          card.width() - 60, 12),
                "已复制" if self._copied(code) else "点击复制", theme, 9,
                QFont.Normal, token="accent")
            render.paint_text(
                p, QRectF(card.right() - 50, card.bottom() - 15, 42, 12),
                self._short_time(item.get("date", "")), theme, 9,
                QFont.Normal, Qt.AlignRight | Qt.AlignVCenter,
                token="textTertiary")
            self._hits.append((card, "copy", code))

        visible = 3
        offset = min(self._scroll["mail"], max(0, len(filtered) - visible))
        body = QRectF(list_x, area.top() + 21, area.right() - list_x,
                      area.height() - 21)
        self._list_rect = body
        if not filtered:
            message = "没有未读邮件" if self._mail_filter == "unread" \
                else "还没有收到邮件"
            render.paint_text(p, body, message, theme, 9, QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
            return
        p.save()
        p.setClipRect(body, Qt.IntersectClip)
        now = time.monotonic()
        for row_index, (index, item) in enumerate(
                filtered[offset:offset + visible]):
            y = area.top() + 22 + row_index * 22
            row = QRectF(list_x, y, body.width(), 22)
            key = self._mail_key(item)
            if self._mail_new.get(key, 0) > now:
                p.save()
                p.setPen(Qt.NoPen)
                color = theme.color("accent")
                color.setAlphaF(0.10)
                p.setBrush(color)
                p.drawRoundedRect(row, 4, 4)
                p.restore()
            p.save()
            p.setPen(QPen(theme.color("hairline"), 1))
            p.drawLine(row.bottomLeft(), row.bottomRight())
            p.restore()
            is_unread = self._mail_unread(item)
            if is_unread:
                p.save()
                p.setPen(Qt.NoPen)
                p.setBrush(theme.color("accent"))
                p.drawEllipse(QPointF(row.left() + 3, row.center().y()), 2, 2)
                p.restore()
            sender_w = 56 if has_card else 66
            render.paint_text(
                p, QRectF(row.left() + 9, y, sender_w, 22),
                render.elide(item.get("sender", ""), 9.5, sender_w,
                             QFont.DemiBold),
                theme, 9.5, QFont.DemiBold,
                token="textPrimary" if is_unread else "textTertiary")
            subject_x = row.left() + 9 + sender_w + 3
            subject_w = max(20.0, row.right() - subject_x - 35)
            render.paint_text(
                p, QRectF(subject_x, y, subject_w, 22),
                render.elide(item.get("subject", ""), 9.5, subject_w),
                theme, 9.5,
                token="textPrimary" if is_unread else "textSecondary")
            render.paint_text(
                p, QRectF(row.right() - 33, y, 31, 22),
                self._short_time(item.get("date", "")), theme, 9,
                QFont.Normal, Qt.AlignRight | Qt.AlignVCenter,
                token="textTertiary")
            self._hits.append((row, "mail_open", index))
        p.restore()
        self._paint_scrollbar(p, body, offset, len(filtered), visible)

    def _paint_mail_detail(self, p, area, item):
        theme = self.theme
        back = QRectF(area.right() - 48, area.top() - 2, 48, 20)
        render.paint_button(p, back, "返回", theme, px=9)
        self._hits.append((back, "mail_back", None))
        code = str(item.get("code") or "")
        read = QRectF(back.left() - 58, area.top() - 2, 54, 20)
        key = self._mail_key(item)
        armed = self._confirming("mail_delete:" + self._mail_confirm_key(key))
        delete = QRectF(read.left() - 58, area.top() - 2, 54, 20)
        render.paint_button(p, delete, "确认删除" if armed else "删除", theme,
                            active=armed, px=9,
                            token="danger" if armed else None)
        self._hits.append((delete, "mail_delete", None))
        if self._mail_unread(item):
            render.paint_button(p, read, "标已读", theme, px=9)
            self._hits.append((read, "mail_read", None))
        elif self._mail_sync_enabled():
            render.paint_button(p, read, "标未读", theme, px=9)
            self._hits.append((read, "mail_unread", None))
        else:
            render.paint_text(p, read, "已读", theme, 9, QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
        right = delete.left() - 4
        full = QRectF(right - 46, area.top() - 2, 44, 20)
        render.paint_button(p, full, "全文", theme, active=True, px=9)
        self._hits.append((full, "mail_full", None))
        right = full.left() - 3
        if code:
            copy = QRectF(right - 46, area.top() - 2, 44, 20)
            render.paint_button(
                p, copy, "已复制" if self._copied(code) else "复制", theme,
                active=True, px=9)
            self._hits.append((copy, "copy", code))
            right = copy.left()
        else:
            copy = QRectF(right - 46, area.top() - 2, 44, 20)
            subject = item.get("subject", "")
            render.paint_button(
                p, copy, "已复制" if self._copied(subject) else "复制", theme,
                px=9)
            self._hits.append((copy, "copy", item.get("subject", "")))
            right = copy.left()
        sender_w = max(40.0, right - area.left() - 4)
        render.paint_text(
            p, QRectF(area.left(), area.top() - 2, sender_w, 20),
            render.elide(item.get("sender", ""), 10, sender_w, QFont.DemiBold),
            theme, 10, QFont.DemiBold)
        y = area.top() + 17
        subject_w = area.width() - 52
        for line in render.wrap_text(item.get("subject", ""), 10.5,
                                     subject_w)[:2]:
            render.paint_text(p, QRectF(area.left(), y, subject_w, 13),
                              line, theme, 10.5, QFont.DemiBold)
            y += 13
        render.paint_text(
            p, QRectF(area.right() - 48, area.top() + 17, 48, 13),
            self._short_time(item.get("date", "")), theme, 9, QFont.Normal,
            Qt.AlignRight | Qt.AlignVCenter, token="textTertiary")
        y = max(y, area.top() + 43)
        if code:
            card = QRectF(area.left(), y, area.width(), 22)
            p.save()
            p.setPen(Qt.NoPen)
            color = theme.color("accent")
            color.setAlphaF(0.14)
            p.setBrush(color)
            p.drawRoundedRect(card, 6, 6)
            p.restore()
            render.paint_text(p, QRectF(card.left() + 8, card.top(),
                                        card.width() - 70, card.height()),
                              code, theme, 15, QFont.Bold,
                              token="accent")
            render.paint_text(
                p, QRectF(card.right() - 60, card.top(), 52, card.height()),
                "已复制" if self._copied(code) else "点击复制",
                theme, 9, QFont.Normal,
                Qt.AlignRight | Qt.AlignVCenter, token="textTertiary")
            self._hits.append((card, "copy", code))
            y = card.bottom() + 3
        preview = item.get("preview", "")
        if preview:
            room = max(0, int((area.bottom() - y) / 12))
            for line in render.wrap_text(preview, 9.5, area.width())[:room]:
                render.paint_text(p, QRectF(area.left(), y, area.width(), 12),
                                  line, theme, 9.5, token="textSecondary")
                y += 12

    def _paint_scrollbar(self, p, rect, offset, count, visible):
        if count <= visible:
            return
        track = QRectF(rect.right() - 2, rect.top() + 2, 2,
                       max(4.0, rect.height() - 4))
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(self.theme.color("track"))
        p.drawRoundedRect(track, 1, 1)
        span = max(1, count - visible)
        room = max(12.0, track.height() * visible / count)
        top = track.top() + (track.height() - room) * offset / span
        p.setBrush(self.theme.color("textTertiary"))
        p.drawRoundedRect(QRectF(track.left(), top, track.width(), room), 1, 1)
        p.restore()

    def _paint_calendar(self, p):
        from island import calendar as cal
        theme = self.theme
        area = self._content_rect()
        result = self.calendar
        refreshing = self._refreshing("calendar")
        if refreshing:
            status, token = "日历 · 正在刷新…", "textTertiary"
        else:
            status, token = self._status_line(result, "日历", "日程")
        render.paint_text(p, QRectF(area.left(), area.top(), area.width() - 52, 16),
                          render.elide(status, 9.5, area.width() - 52), theme,
                          9.5, token=token)
        refresh = QRectF(area.right() - 44, area.top() - 2, 44, 18)
        render.paint_button(p, refresh, "刷新中" if refreshing else "刷新",
                            theme, active=refreshing)
        self._hits.append((refresh, "calendar_refresh", None))
        if result.get("status") != "ok" or not result.get("items"):
            message = ("在 设置 → 日历 填写 .ics 或 CalDAV" if result.get("status") == "unconfigured"
                       else "未来 7 天没有日程" if result.get("status") == "ok"
                       else result.get("error", "读取失败"))
            render.paint_text(p, QRectF(area.left(), area.top() + 24,
                                        area.width(), 40),
                              render.elide(message, 9, area.width()), theme, 9,
                              QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
            return
        for index, event in enumerate(result["items"][:3]):
            y = area.top() + 20 + index * 24
            render.paint_text(p, QRectF(area.left(), y, 64, 20),
                              cal.event_text(event), theme, 9.5, QFont.DemiBold,
                              token="accent")
            summary = event.get("summary", "")
            if event.get("place"):
                summary += " · " + str(event["place"])
            render.paint_text(p, QRectF(area.left() + 68, y,
                                        area.width() - 68, 20),
                              render.elide(summary, 10, area.width() - 68),
                              theme, 10)

    def _paint_quota(self, p):
        theme = self.theme
        area = self._content_rect()
        providers = self.quota.get("providers") or []
        if not providers:
            render.paint_text(p, area, "读取额度…", theme, 9, QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
            return
        shown = [item for item in providers
                 if item.get("status") != "unconfigured"][:6]
        shown = shown or providers[:1]
        gap = 4.0
        chip_w = max(40.0, min(
            66.0, (area.width() - 48.0 - gap * (len(shown) - 1))
            / max(1, len(shown))))
        for index, item in enumerate(shown):
            rect = QRectF(area.left() + index * (chip_w + gap), area.top(),
                          chip_w, 20)
            active = item.get("id") == self.quota_selected
            label = render.elide(str(item.get("label") or ""), 9,
                                 chip_w - 8)
            render.paint_button(p, rect, label, theme, active=active, px=9)
            self._hit(rect, "quota_pick", item.get("id"))

        busy = time.monotonic() < self._quota_refresh_until
        refresh = QRectF(area.right() - 44, area.top(), 44, 20)
        render.paint_button(p, refresh, "刷新中" if busy else "刷新", theme,
                            px=9)
        self._hit(refresh, "quota_refresh", None)

        provider = next((item for item in providers
                         if item.get("id") == self.quota_selected),
                        providers[0])
        metrics = [item for item in (provider.get("metrics") or [])
                   if isinstance(item, dict)]
        body = area.top() + 26.0
        right_x = area.left() + 68.0
        right_w = area.right() - right_x
        percent_metrics = [item for item in metrics
                           if item.get("kind") != "balance"
                           and item.get("remaining") is not None]
        shares = [float(item["remaining"]) for item in percent_metrics[:2]]
        tokens = [_quota_token(float(item.get("used") or 0))
                  for item in percent_metrics[:2]]
        if len(tokens) > 1 and tokens[1] == tokens[0]:
            tokens[1] = "success" if tokens[0] != "success" else "accent"
        ring_index = {id(item): index
                      for index, item in enumerate(percent_metrics[:2])}
        render.paint_quota_rings(p, area.left() + 29, body + 29, 58,
                                 shares, theme, tokens)

        title = str(provider.get("label") or "")
        plan = str(provider.get("plan") or "")
        if plan:
            title += " · " + plan
        title_w = right_w - 64
        render.paint_text(p, QRectF(right_x, body - 2, title_w, 13),
                          render.elide(title, 10, title_w), theme, 10,
                          QFont.DemiBold)
        status = provider.get("status")
        if busy:
            when, token = "刷新中…", "accent"
        elif status == "unconfigured":
            when, token = "未配置", "textTertiary"
        elif status == "error":
            when, token = "读取失败", "warning"
        else:
            when, token = _quota_when(provider.get("updated")), "textTertiary"
        if when:
            render.paint_text(p, QRectF(right_x + right_w - 74, body, 74, 12),
                              when, theme, 9, QFont.Normal,
                              Qt.AlignRight | Qt.AlignVCenter, token=token)

        if metrics:
            rows = metrics[:2]
            row_h = 24.0 if len(rows) > 1 else 26.0
            start = body + 12.0
            for index, item in enumerate(rows):
                y = start + index * row_h
                used = float(item.get("used") or 0)
                ring = ring_index.get(id(item))
                dot_token = (tokens[ring] if ring is not None
                             else _quota_token(used))
                color = theme.color(dot_token)
                p.save()
                p.setPen(Qt.NoPen)
                p.setBrush(color)
                p.drawEllipse(QPointF(right_x + 4, y + 5), 2.2, 2.2)
                p.restore()
                label = str(item.get("label") or "")
                render.paint_text(
                    p, QRectF(right_x + 11, y - 1, 90, 12),
                    render.elide(label, 9.5, 90), theme, 9.5, QFont.DemiBold)
                text = str(item.get("text") or "")
                kind = item.get("kind")
                px = (10.0 if kind in ("tokens", "balance") or len(text) > 6
                      else 13.0)
                render.paint_text(
                    p, QRectF(right_x + right_w - 108, y - 4, 108, 16),
                    text, theme, px, QFont.DemiBold,
                    Qt.AlignRight | Qt.AlignVCenter,
                    token=(dot_token if used >= 0.8
                           else "textPrimary"))
                note = str(item.get("reset_text") or "")
                if note:
                    render.paint_text(
                        p, QRectF(right_x + 11, y + 10, right_w - 11, 10),
                        render.elide(note, 9, right_w - 11), theme, 9,
                        token="textTertiary")
        else:
            message = (provider.get("error") or provider.get("note")
                       or "等待更新")
            rows = render.wrap_text(message, 9.5, right_w, QFont.Normal)[:2]
            for index, line in enumerate(rows):
                render.paint_text(
                    p, QRectF(right_x, body + 15 + index * 12, right_w, 11),
                    line, theme, 9.5, token="textTertiary")

        if self._activity_visible():
            self._paint_activity_line(p, area)

    def _paint_activity_line(self, p, area):
        theme = self.theme
        token = self._activity_token()
        cy = area.bottom() - 4.5
        render.paint_spark(p, area.left() + 5, cy, 11, theme, token)
        provider = str(self.activity.get("provider") or "")
        label = str(self.activity.get("label") or "")
        head = f"{provider} · {label}" if provider else label
        if self._activity_age():
            head += " · " + self._activity_age()
        x = area.left() + 13
        room = area.right() - x
        head_w = min(room, render.text_width(head, 9, QFont.DemiBold))
        render.paint_text(p, QRectF(x, area.bottom() - 11, head_w + 1, 11),
                          render.elide(head, 9, room), theme, 9,
                          QFont.DemiBold, token=token)
        detail = ""
        if self.activity.get("state") in ("responding", "completed"):
            detail = str(self.activity.get("detail") or "")
        rest = room - head_w - 4
        if detail and rest > 24:
            render.paint_text(
                p, QRectF(x + head_w + 4, area.bottom() - 11, rest, 11),
                render.elide(detail, 9, rest), theme, 9,
                token="textTertiary")

    def _paint_stock(self, p):
        theme = self.theme
        area = self._content_rect()
        result = self.stock or {}
        code = str(result.get("code") or self.cfg.get("stock_code") or "")
        name = str(result.get("name") or code or "股票")
        when = str(result.get("at") or "")
        head = f"{name} · {code}" + (f" · {when}" if when else "")
        if not self._stock_shown:
            head += " · 休市，收起态已隐藏"
        render.paint_text(
            p, QRectF(area.left(), area.top(), area.width() - 52, 16),
            render.elide(head, 9.5, area.width() - 52), theme, 9.5,
            QFont.DemiBold, token="textSecondary")
        busy = self._refreshing("stock")
        refresh = QRectF(area.right() - 44, area.top() - 2, 44, 18)
        render.paint_button(p, refresh, "刷新中" if busy else "刷新", theme,
                            active=busy)
        self._hits.append((refresh, "stock_refresh", None))

        price = result.get("price")
        if result.get("status") != "ok" or price is None:
            message = ("读取行情…" if result.get("status") in (None, "loading")
                       else result.get("error") or "行情不可用")
            render.paint_text(
                p, QRectF(area.left(), area.top() + 24, area.width(), 40),
                render.elide(message, 9, area.width()), theme, 9,
                token="textTertiary", align=Qt.AlignCenter)
            return

        token = self._stock_token()
        try:
            change = float(result.get("change") or 0.0)
            pct = float(result.get("change_pct") or 0.0)
            prev_close = float(result.get("prev_close") or 0.0)
        except (TypeError, ValueError):
            change = pct = prev_close = 0.0
        body = area.top() + 20
        render.paint_text(
            p, QRectF(area.left(), body, 104, 26), f"{float(price):.2f}",
            theme, 22, QFont.DemiBold, token=token)
        render.paint_text(
            p, QRectF(area.left(), body + 26, 104, 13),
            f"{change:+.2f}  {pct:+.2f}%", theme, 9.5, QFont.DemiBold,
            token=token)

        high, low = result.get("high"), result.get("low")
        if high is not None:
            render.paint_text(
                p, QRectF(area.left(), body + 42, 104, 11),
                f"高 {float(high):.2f}", theme, 8.5, token="textTertiary")
        if low is not None:
            render.paint_text(
                p, QRectF(area.left(), body + 52, 104, 11),
                f"低 {float(low):.2f}", theme, 8.5, token="textTertiary")

        chart = QRectF(area.left() + 106, body + 2,
                       area.width() - 106, 58)
        points = result.get("points") or []
        if len(points) < 2:
            render.paint_text(p, chart, "分时数据暂不可用", theme, 9,
                              token="textTertiary", align=Qt.AlignCenter)
            return
        render.paint_trend(p, chart, points, prev_close, theme, token)
        start = str(points[0][0])
        end = str(points[-1][0])
        render.paint_text(
            p, QRectF(chart.left(), chart.bottom() + 1, 48, 10),
            f"{start[:2]}:{start[2:]}", theme, 8, token="textTertiary")
        render.paint_text(
            p, QRectF(chart.right() - 48, chart.bottom() + 1, 48, 10),
            f"{end[:2]}:{end[2:]}", theme, 8,
            align=Qt.AlignRight | Qt.AlignVCenter, token="textTertiary")

    @staticmethod
    def _weather_day_label(index, date):
        if index == 0:
            return "今天"
        if index == 1:
            return "明天"
        try:
            day = datetime.strptime(str(date), "%Y-%m-%d")
        except (TypeError, ValueError):
            return f"D{index + 1}"
        return "周" + WEEKDAYS_ZH[day.weekday()]

    def _paint_weather(self, p):
        theme = self.theme
        area = self._content_rect()
        data = self.data.get("weather") or {}
        place = str(data.get("place") or "天气")
        region = str(data.get("region") or "")
        head = place + (f" · {region}" if region and region != place else "")
        stale = bool(data.get("stale"))
        render.paint_text(
            p, QRectF(area.left(), area.top(), area.width() - 54, 13),
            render.elide(head, 9.5, area.width() - 54), theme, 9.5,
            QFont.DemiBold, token="warning" if stale else "textSecondary")
        try:
            when = datetime.fromtimestamp(
                float(data.get("at"))).strftime("%H:%M")
        except (TypeError, ValueError, OSError):
            when = ""
        if when:
            render.paint_text(
                p, QRectF(area.right() - 54, area.top(), 54, 12),
                ("上次 " if stale else "") + when, theme, 8,
                align=Qt.AlignRight | Qt.AlignVCenter, token="textTertiary")

        temp = data.get("temp")
        if temp is None:
            message = str(data.get("error") or "读取天气…")
            render.paint_text(
                p, QRectF(area.left(), area.top() + 20, area.width(), 40),
                render.elide(message, 9, area.width()), theme, 9,
                token="textTertiary", align=Qt.AlignCenter)
            return

        left_w = 104.0
        body = area.top() + 14
        render.paint_text(
            p, QRectF(area.left(), body, 86, 30), f"{float(temp):.0f}°",
            theme, 26, QFont.Bold, token="textPrimary")
        high, low = data.get("high"), data.get("low")
        today = str(data.get("text") or "")
        if high is not None and low is not None:
            today += f"  {float(high):.0f}°/{float(low):.0f}°"
        render.paint_text(
            p, QRectF(area.left(), body + 30, left_w, 12),
            render.elide(today, 9, left_w), theme, 9, token="textSecondary")
        feels, humidity, wind = (data.get("feels"), data.get("humidity"),
                                 data.get("wind"))
        stats = []
        if humidity is not None:
            stats.append(f"湿度 {float(humidity):.0f}%")
        if wind is not None:
            stats.append(f"风 {float(wind):.0f}km/h")
        render.paint_text(
            p, QRectF(area.left(), body + 44, left_w, 11),
            render.elide(" · ".join(stats), 8, left_w), theme, 8,
            token="textTertiary")
        if feels is not None:
            render.paint_text(
                p, QRectF(area.left(), body + 56, left_w, 11),
                f"体感 {float(feels):.0f}°", theme, 8,
                token="textTertiary")

        days = [item for item in (data.get("daily") or [])
                if isinstance(item, dict)][:7]
        chart = QRectF(area.left() + left_w + 6, area.top() + 14,
                       area.width() - left_w - 6, 68)
        p.save()
        p.setPen(QPen(theme.color("hairline"), 1.0))
        p.drawLine(QPointF(area.left() + left_w, area.top() + 16),
                   QPointF(area.left() + left_w, area.bottom() - 4))
        p.restore()
        if not days:
            render.paint_text(p, chart, "未来 7 天暂不可用", theme, 9,
                              token="textTertiary", align=Qt.AlignCenter)
            return
        col = chart.width() / 7
        for index, day in enumerate(days):
            x = chart.left() + col * index
            center = x + col / 2
            render.paint_text(
                p, QRectF(x, chart.top(), col, 10),
                self._weather_day_label(index, day.get("date")), theme, 8,
                align=Qt.AlignCenter, token="textSecondary")
            render.paint_weather_icon(
                p, center - 7, chart.top() + 21, 14,
                day.get("kind") or weather.kind(day.get("text")), theme)
            high, low = day.get("high"), day.get("low")
            render.paint_text(
                p, QRectF(x, chart.top() + 31, col, 11),
                "--" if high is None else f"{float(high):.0f}°", theme, 9,
                QFont.DemiBold, align=Qt.AlignCenter, token="textPrimary")
            render.paint_text(
                p, QRectF(x, chart.top() + 42, col, 10),
                "--" if low is None else f"{float(low):.0f}°", theme, 8,
                align=Qt.AlignCenter, token="textTertiary")
            rain = day.get("precip")
            if rain is not None:
                render.paint_text(
                    p, QRectF(x, chart.top() + 52, col, 9),
                    f"{float(rain):.0f}%", theme, 7.5,
                    align=Qt.AlignCenter, token="accent" if rain >= 40
                    else "textTertiary")

    def _paint_monitor(self, p):
        theme = self.theme
        area = self._content_rect()
        cpu, mem = self.data.get("cpu"), self.data.get("memory")
        disk, temp = self.data.get("disk"), self.data.get("temperature")
        gpu = self.data.get("gpu") or {}
        down = format_rate(self.data.get("net_down"))
        up = format_rate(self.data.get("net_up"))
        online = self.data.get("online")
        network = ("离线" if online is False else
                   f"↓{down} ↑{up}" if down != "--" else "不可用")

        def pct(value):
            return "--" if value is None else f"{int(value * 100)}%"

        cells = [
            ("CPU", pct(cpu), cpu),
            ("内存", pct(mem), mem),
            ("磁盘", pct(disk), disk),
            ("温度", "--" if temp is None else f"{temp:.0f}°C",
             None if temp is None else min(1.0, temp / 100.0)),
            ("GPU", pct(gpu.get("util")) if gpu else "不可用",
             (gpu.get("util") or 0.0) if gpu else 0.0),
            ("网络", network, 0.0),
        ]
        cell_w = area.width() / 3
        cell_h = 45
        for index, (label, value, ratio) in enumerate(cells):
            x = area.left() + cell_w * (index % 3)
            y = area.top() + cell_h * (index // 3)
            render.paint_text(p, QRectF(x, y, cell_w - 12, 13), label, theme,
                              9.5,
                              token="textTertiary")
            render.paint_text(p, QRectF(x, y + 11, cell_w - 12, 19), value, theme,
                              13, QFont.DemiBold, token="textPrimary")
            ratio = ratio or 0.0
            token = ("danger" if ratio >= 0.92 else
                     "warning" if ratio >= 0.8 else "accent")
            render.paint_bar(p, QRectF(x, y + 32, cell_w - 22, 3), ratio, theme,
                             token)

    def _paint_tools(self, p):
        theme = self.theme
        area = self._content_rect()
        for index, (key, label) in enumerate(TOOLS):
            rect = QRectF(area.left() + index * 52, area.top(), 48, 19)
            active = self.tools_page == key
            render.paint_button(p, rect, label, theme, active=active, px=9)
            if key == "notify" and self._unread:
                # 页码豆说不清是哪个标签，这里点名
                render.paint_dot(p, rect.right() - 6, rect.center().y(), 2.5,
                                 theme, "danger")
            self._tools_hits.append((rect, "tools", key))
        body = QRectF(area.left(), area.top() + 25, area.width(),
                      area.height() - 25)
        if self.tools_page == "shelf":
            self._paint_shelf(p, body)
        elif self.tools_page == "clips":
            self._paint_clips(p, body)
        else:
            self._paint_notify(p, body)

    def _paint_shelf(self, p, body):
        theme = self.theme
        add = QRectF(body.right() - 42, body.top() - 24, 42, 18)
        render.paint_button(p, add, "添加", theme)
        self._hits.append((add, "shelf_add", None))
        if self.productivity.shelf:
            armed = self._confirming("shelf_clear")
            clear = QRectF(body.right() - 88, body.top() - 24, 42, 18)
            render.paint_button(p, clear, "确认?" if armed else "清空", theme,
                                active=armed, px=9,
                                token="danger" if armed else None)
            self._hits.append((clear, "shelf_clear", None))
            render.paint_text(p, QRectF(body.left() + 156, body.top() - 24,
                                        body.width() - 254, 18),
                              f"{len(self.productivity.shelf)} 项",
                              theme, 9.5, QFont.Normal,
                              Qt.AlignRight | Qt.AlignVCenter,
                              token="textTertiary")
        if self._drag_active:
            p.save()
            p.setPen(Qt.NoPen)
            color = theme.color("accent")
            color.setAlphaF(0.12)
            p.setBrush(color)
            p.drawRoundedRect(body, 12, 12)
            pen = QPen(theme.color("accent"), 1.4, Qt.DashLine)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(body.adjusted(1, 1, -1, -1), 11, 11)
            p.restore()
            render.paint_tray(p, body.center().x(), body.top() + 22, 26, theme)
            render.paint_text(p, QRectF(body.left(), body.top() + 36,
                                        body.width(), 16),
                              "松手放进置物架", theme, 11, QFont.DemiBold,
                              Qt.AlignCenter)
            render.paint_text(p, QRectF(body.left(), body.top() + 51,
                                        body.width(), 12),
                              "只记住文件位置，不复制", theme, 9.5,
                              QFont.Normal, Qt.AlignCenter,
                              token="textTertiary")
            return
        if not self.productivity.shelf:
            p.save()
            p.setPen(QPen(theme.color("outline"), 1.2, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(body.adjusted(1, 1, -1, -1), 11, 11)
            p.restore()
            render.paint_tray(p, body.center().x(), body.top() + 18, 24, theme)
            render.paint_text(p, QRectF(body.left(), body.top() + 32,
                                        body.width(), 16),
                              "把文件拖到这儿", theme, 10, QFont.DemiBold,
                              Qt.AlignCenter)
            render.paint_text(p, QRectF(body.left(), body.top() + 47,
                                        body.width(), 12),
                              "只记位置，不复制 · 点一下打开", theme, 9.5,
                              QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
            return
        slot = body.width() / 5
        card_h = body.height()
        for index in range(5):
            x = body.left() + slot * index + (slot - 60) / 2
            card = QRectF(x, body.top(), 60, card_h)
            if index >= len(self.productivity.shelf):
                p.save()
                p.setPen(QPen(theme.color("outline"), 1.1, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawRoundedRect(card.adjusted(1, 1, -1, -1), 9, 9)
                p.restore()
                render.paint_plus(p, card.center().x(), card.center().y(),
                                  12, theme, "textTertiary")
                self._hits.append((card, "shelf_add", None))
                continue
            path = self.productivity.shelf[index]
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("fill"))
            p.drawRoundedRect(card, 9, 9)
            p.restore()
            render.paint_file(p, card.center().x(), card.top() + 20, 28,
                              theme, "textSecondary")
            name = os.path.basename(path.rstrip("/")) or path
            render.paint_text(p, QRectF(card.left(), card.top() + 37,
                                        card.width(), 12),
                              render.elide(name, 9.5, card.width() - 4), theme,
                              9.5, QFont.DemiBold, Qt.AlignCenter)
            render.paint_text(p, QRectF(card.left(), card.top() + 49,
                                        card.width(), 10),
                              self._file_meta(path), theme, 9, QFont.Normal,
                              Qt.AlignCenter, token="textTertiary")
            close = QRectF(card.right() - 16, card.top() + 2, 15, 15)
            render.paint_close(p, close.center().x(), close.center().y(), 6,
                               theme)
            self._hits.append((card.adjusted(0, 0, -16, 0), "shelf_open", path))
            self._hits.append((close, "shelf_remove", index))
    def _file_meta(self, path):
        try:
            if os.path.isdir(path):
                return "文件夹"
            size = os.path.getsize(path)
        except OSError:
            return ""
        if size >= 1024 * 1024:
            return f"{size / (1024 * 1024):.0f} MB"
        if size >= 1024:
            return f"{size / 1024:.0f} KB"
        return f"{size} B"

    def _paint_clips(self, p, body):
        theme = self.theme
        clips = self.productivity.clips
        pinned = sum(1 for item in clips if item.get("pinned"))
        armed = self._confirming("clips_clear")
        clear = QRectF(body.right() - 54, body.top() - 24, 54, 18)
        if len(clips) - pinned:
            render.paint_button(p, clear, "确认?" if armed else "清空", theme,
                                active=armed, token="danger" if armed else None)
            self._hits.append((clear, "clips_clear", None))
        render.paint_text(p, QRectF(body.left(), body.top() - 24,
                                    body.width() - 58, 18),
                          f"{len(clips)} 条" + (f" · 固定 {pinned}" if pinned else "")
                          + " · 点击复制",
                          theme, 9.5, QFont.Normal,
                          Qt.AlignRight | Qt.AlignVCenter,
                          token="textTertiary")
        if not clips:
            p.save()
            p.setPen(QPen(theme.color("outline"), 1.1, Qt.DashLine))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(body.adjusted(1, 1, -1, -1), 10, 10)
            p.restore()
            render.paint_clipboard(p, body.center().x(), body.top() + 16, 22,
                                   theme, "textTertiary")
            render.paint_text(p, QRectF(body.left(), body.top() + 34,
                                        body.width(), 14),
                              "复制的文字会出现在这里", theme, 9.5,
                              QFont.DemiBold, Qt.AlignCenter)
            render.paint_text(p, QRectF(body.left(), body.top() + 49,
                                        body.width(), 12),
                              "记录保存在本机，重新打开仍可查看", theme, 9.5,
                              QFont.Normal, Qt.AlignCenter,
                              token="textTertiary")
            return
        visible = 3
        count = len(clips)
        order = sorted(range(count),
                       key=lambda index: 0 if clips[index].get("pinned") else 1)
        offset = min(self._scroll["clips"], max(0, count - visible))
        self._list_rect = body
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("fill"))
        p.drawRoundedRect(body, 10, 10)
        p.restore()
        p.save()
        p.setClipRect(body, Qt.IntersectClip)
        for position, index in enumerate(order[offset:offset + visible]):
            item = clips[index]
            y = body.top() + 1 + position * 21.5
            row = QRectF(body.left() + 6, y, body.width() - 12, 20.5)
            if position:
                p.save()
                p.setPen(QPen(theme.color("hairline"), 1))
                p.drawLine(row.bottomLeft(), row.bottomRight())
                p.restore()
            is_pinned = bool(item.get("pinned"))
            if is_pinned:
                render.paint_pin(p, row.left() + 8, row.center().y(), 10,
                                 theme, "accent")
            else:
                p.save()
                p.setPen(Qt.NoPen)
                p.setBrush(theme.color("textTertiary"))
                p.drawEllipse(QPointF(row.left() + 8, row.center().y()), 2.2, 2.2)
                p.restore()
            text = item["text"].replace("\n", " ")
            text_w = row.width() - 92
            render.paint_text(p, QRectF(row.left() + 18, y, text_w, 20.5),
                              render.elide(text, 9, text_w), theme, 9,
                              token="textPrimary" if is_pinned else "textSecondary")
            copied = self._copied(item["text"])
            render.paint_text(p, QRectF(row.right() - 71, y, 34, 20.5),
                              "已复制" if copied else item.get("at", ""),
                              theme, 9, QFont.Normal,
                              Qt.AlignRight | Qt.AlignVCenter,
                              token="accent" if copied else "textTertiary")
            pin = QRectF(row.right() - 37, y + 1, 17, 18)
            render.paint_pin(p, pin.center().x(), pin.center().y(), 9, theme,
                             "accent" if is_pinned else "textTertiary")
            close = QRectF(row.right() - 18, y + 2, 15, 16)
            render.paint_close(p, close.center().x(), close.center().y(), 6,
                               theme)
            self._hits.append((row.adjusted(0, 0, -38, 0), "copy",
                               item["text"]))
            self._hits.append((pin, "clip_pin", index))
            self._hits.append((close, "clip_remove", index))
        p.restore()
        self._paint_scrollbar(p, body, offset, count, visible)

    def _paint_notify(self, p, body):
        theme = self.theme
        armed = self._confirming("notify_clear")
        clear = QRectF(body.right() - 54, body.top() - 24, 54, 18)
        render.paint_button(p, clear, "确认?" if armed else "清空", theme,
                            active=armed, token="danger" if armed else None)
        self._hits.append((clear, "notify_clear", None))
        if not self.notifications:
            message = ("通知监听不可用：" + self.notify_error
                       if self.notify_error else "暂无通知 · 正在监听系统通知")
            render.paint_text(p, body, render.elide(message, 9, body.width()),
                              theme, 9, QFont.Normal, Qt.AlignCenter,
                              token="danger" if self.notify_error else "textTertiary")
            return
        for index, note in enumerate(self.notifications[:2]):
            y = body.top() + index * 33
            render.paint_text(p, QRectF(body.left(), y, body.width() - 44, 12),
                              render.elide(note.get("app", ""), 9.5,
                                           body.width() - 44),
                              theme, 9.5, QFont.DemiBold, token="accent")
            render.paint_text(p, QRectF(body.right() - 40, y, 40, 12),
                              note.get("at", ""), theme, 9, QFont.Normal,
                              Qt.AlignRight,
                              token="textTertiary")
            text = note.get("summary", "")
            if note.get("body"):
                text += " · " + note["body"]
            render.paint_text(p, QRectF(body.left(), y + 12, body.width(), 16),
                              render.elide(text, 9.5, body.width()), theme, 9.5)

    def _status_line(self, result, name, label):
        status = result.get("status")
        if status == "ok":
            return f"{name} · 已连接 {result.get('at', '')}", "success"
        if status == "unconfigured":
            return f"{name} · 未配置", "textTertiary"
        if status == "error":
            return f"{label}读取失败 · {result.get('error', '')}", "danger"
        return f"{name} · 正在读取…", "textTertiary"

    def _short_time(self, text):
        match = re.search(r"(\d{1,2}:\d{2})", text or "")
        return match.group(1) if match else ""

    def _music_state(self):
        music = self.music or {}
        position = float(music.get("position") or 0)
        if self._drag_seek is not None:
            position = self._drag_seek
        elif self._seek_preview is not None:
            if (music.get("title") != self._seek_title
                    or time.monotonic() - self._seek_at > 2.5):
                self._seek_preview = None
            else:
                position = self._seek_preview
        info = (lyrics.current(music.get("lyric"), position)
                if music.get("title") else None)
        return {
            "present": bool(music.get("title")),
            "playing": music.get("status") == "Playing",
            "paused": music.get("status") == "Paused",
            "player": bool(music.get("player")),
            "can_seek": bool(music.get("can_seek")),
            "seeking": self._drag_seek is not None,
            "line": info["text"] if info else "",
            "line_info": info,
            "position": position,
            "length": float(music.get("length") or 0),
        }

    def _paint_music(self, p, state):
        theme = self.theme
        self._sync_lyrics_anim(state)
        layout = self._music_layout()
        cover = layout["cover"]
        music = self.music or {}
        p.save()
        clip = QPainterPath()
        clip.addRoundedRect(cover, 8, 8)
        p.setClipPath(clip)
        if self._cover is None:
            pix = QPixmap(self._cover_path) if self._cover_path else QPixmap()
            self._cover = pix if not pix.isNull() else False
        if self._cover:
            p.drawPixmap(cover.toRect(), self._cover.scaled(
                cover.size().toSize(), Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation))
        elif state["present"]:
            first, second = _cover_colors(music.get("title", ""))
            gradient = QLinearGradient(cover.topLeft(), cover.bottomRight())
            gradient.setColorAt(0.0, QColor(first))
            gradient.setColorAt(1.0, QColor(second))
            p.fillRect(cover, gradient)
            p.setPen(QColor(255, 255, 255, 235))
            p.setFont(render.ui_font(cover.height() * 0.4, QFont.DemiBold))
            p.drawText(cover, Qt.AlignCenter, "♪")
        else:
            p.fillRect(cover, theme.color("fill"))
            render.paint_text(p, cover, "♪", theme, cover.height() * 0.45,
                              QFont.DemiBold, Qt.AlignCenter, token="textTertiary")
        p.restore()
        if not state["present"]:
            area = self._content_rect()
            p.save()
            p.setPen(QPen(theme.color("outline"), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(cover.adjusted(0.5, 0.5, -0.5, -0.5), 8, 8)
            p.restore()
            text_w = area.right() - cover.right() - 12
            render.paint_text(p, QRectF(cover.right() + 12, area.top() + 12,
                                        text_w, 16),
                              "暂无音乐", theme, 12, QFont.Bold)
            hint_w = max(30.0, text_w - 70)
            render.paint_text(
                p, QRectF(cover.right() + 12, area.top() + 30,
                          hint_w, 13),
                render.elide("打开播放器后自动显示", 9, hint_w), theme, 9,
                token="textTertiary")
            volume = self.data.get("volume")
            if volume is not None:
                rect = QRectF(area.right() - 64, area.top() + 19, 64, 16)
                render.paint_text(p, rect, f"音量 {int(volume * 100)}%", theme,
                                  9, QFont.Normal,
                                  Qt.AlignRight | Qt.AlignVCenter,
                                  token="textTertiary")
                self._hits.append((rect.adjusted(-4, -3, 0, 3),
                                   "music_volume", None))
            return
        area = self._content_rect()
        has_player = state["player"]
        title = music.get("title", "")
        artist = music.get("artist") or music.get("app") or "播放中"
        if not state["playing"]:
            artist += " · 已暂停" if state["paused"] else " · 已停止"

        mix = self._lyrics_mix()
        if mix > 0.0:
            p.save()
            p.setOpacity(p.opacity() * mix)
            p.translate(0.0, 4.0 * (1.0 - mix))
            text_w = max(30.0, area.left() + 143 - cover.right() - 8)
            render.paint_text(
                p, QRectF(cover.right() + 8, cover.top() - 1, text_w, 15),
                render.elide(title, 10.5, text_w, QFont.DemiBold), theme,
                10.5, QFont.DemiBold)
            render.paint_text(
                p, QRectF(cover.right() + 8, cover.top() + 14, text_w, 13),
                render.elide(artist, 9, text_w), theme, 9,
                token="textTertiary")
            divider_x = area.left() + 148
            p.save()
            p.setPen(QPen(theme.color("hairline"), 1))
            p.drawLine(QPointF(divider_x, area.top() + 1),
                       QPointF(divider_x, area.top() + 60))
            p.restore()
            col = QRectF(divider_x + 5, area.top(), area.right() - divider_x - 5,
                         62)
            p.save()
            p.setClipRect(col)
            ease = self._lyric_ease()
            p.setOpacity(p.opacity() * (0.45 + 0.55 * ease))
            p.translate(0.0, 3.5 * (1.0 - ease))
            info = state.get("line_info") or {}
            lines = music.get("lyric") or []
            index = info.get("index", -1)
            if 0 < index < len(lines):
                render.paint_text(
                    p, QRectF(col.left(), col.top() + 2, col.width(), 13),
                    render.elide(lines[index - 1][1], 9, col.width()), theme,
                    9, token="textTertiary")
            line = state["line"]
            rows, first = self._lyric_page(
                render.wrap_text(line, 10.5, col.width(), QFont.DemiBold),
                2, info, state["position"])
            if line != self._lyric_page_line or first != self._lyric_page_index:
                if line == self._lyric_page_line:
                    self._lyric_page_at = time.monotonic()
                    self._start_motion()
                self._lyric_page_line = line
                self._lyric_page_index = first
            page_ease = self._lyric_page_ease()
            p.setOpacity(p.opacity() * (0.45 + 0.55 * page_ease))
            p.translate(0.0, 3.5 * (1.0 - page_ease))
            for row_index, row in enumerate(rows):
                render.paint_text(
                    p, QRectF(col.left(), col.top() + 17 + row_index * 12,
                              col.width(), 13),
                    row, theme, 10.5, QFont.DemiBold)
            if 0 <= index + 1 < len(lines):
                render.paint_text(
                    p, QRectF(col.left(), col.bottom() - 13, col.width(), 13),
                    render.elide(lines[index + 1][1], 9, col.width()), theme,
                    9, token="textTertiary")
            p.restore()
            p.restore()
        if mix < 1.0:
            p.save()
            p.setOpacity(p.opacity() * (1.0 - mix))
            p.translate(0.0, -4.0 * mix)
            text_w = max(30.0, area.right() - cover.right() - 18)
            render.paint_marquee(
                p, QRectF(cover.right() + 10, cover.top() - 1, text_w, 17),
                title, theme, 11.5,
                self._marquee_elapsed("detail-title", title),
                QFont.DemiBold)
            render.paint_marquee(
                p, QRectF(cover.right() + 10, cover.top() + 15, text_w, 13),
                artist, theme, 9.5,
                self._marquee_elapsed("detail-artist", artist),
                token="textTertiary")
            if music.get("album"):
                render.paint_text(
                    p, QRectF(cover.right() + 10, cover.top() + 30,
                              text_w, 13),
                    render.elide(music["album"], 9.5, text_w), theme, 9.5,
                    token="textTertiary")
            p.restore()

        bar = layout["progress"]
        length = state["length"]
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("track"))
        p.drawRoundedRect(bar, 1.75, 1.75)
        ratio = 0.0 if length <= 0 else max(
            0.0, min(1.0, state["position"] / length))
        if ratio > 0:
            p.setBrush(theme.color("accent"))
            p.drawRoundedRect(QRectF(bar.left(), bar.top(),
                                     max(bar.width() * ratio, 3.5),
                                     bar.height()), 1.75, 1.75)
        if state["seeking"]:
            p.setBrush(theme.color("textPrimary"))
            p.drawEllipse(QPointF(bar.left() + bar.width() * ratio,
                                  bar.center().y()), 4, 4)
        position = max(0.0, state["position"])
        render.paint_text(
            p, QRectF(area.left(), bar.top() - 12, 64, 12),
            format_time(position), theme, 9, token="textTertiary")
        remaining = ("--:--" if length <= 0
                     else "-" + format_time(max(0.0, length - position)))
        if not (self._volume_open and self.data.get("volume") is not None):
            render.paint_text(
                p, QRectF(bar.right() - 64, bar.top() - 12, 64, 12), remaining,
                theme, 9, QFont.Normal, Qt.AlignRight | Qt.AlignVCenter,
                token="textTertiary")

        render.paint_button(p, layout["lyrics"], "词", theme,
                            active=self._show_lyrics, px=9)
        self._hits.append((layout["lyrics"], "music_lyrics", None))
        if has_player:
            center = layout["play"].center().y()
            p.save()
            p.setPen(Qt.NoPen)
            p.setBrush(theme.color("fill"))
            p.drawEllipse(layout["play"].center(), 12, 12)
            p.restore()
            render.paint_skip(p, layout["prev"].left() + 6, center, 13, theme,
                              forward=False)
            if state["playing"]:
                render.paint_pause(p, layout["play"].left() + 7, center, 11, theme)
            else:
                render.paint_play(p, layout["play"].left() + 7, center, 11, theme)
            render.paint_skip(p, layout["next"].left() + 5, center, 13, theme)
        volume = self.data.get("volume")
        volume_rect = QRectF(area.right() - 62, layout["lyrics"].top(),
                             60, 22)
        render.paint_text(
            p, volume_rect,
            ("音量 --" if volume is None
             else f"音量 {int(volume * 100)}%"), theme, 9, QFont.Normal,
            Qt.AlignRight | Qt.AlignVCenter, token="textTertiary")
        if volume is not None:
            self._hits.append((volume_rect, "music_volume", None))
        if self._volume_open and volume is not None:
            self._paint_volume_popup(p, volume)

    def _paint_volume_popup(self, p, volume):
        theme = self.theme
        popup = self._volume_popup_rect()
        muted = bool(self.data.get("muted", False))
        p.save()
        p.setPen(QPen(theme.color("popupBorder"), 1))
        p.setBrush(theme.color("popup"))
        p.drawRoundedRect(popup, 11, 11)
        p.restore()
        render.paint_text(
            p, QRectF(popup.left(), popup.top() + 2, popup.width(), 15),
            f"{int(volume * 100)}%", theme, 9, QFont.DemiBold,
            Qt.AlignCenter,
            token="textTertiary" if muted else "textPrimary")
        track = self._volume_track_rect()
        render.paint_bar(p, track, volume, theme,
                         "textTertiary" if muted else "accent")
        head = track.bottom() - track.height() * max(0.0, min(1.0, volume))
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(theme.color("textTertiary" if muted else "textPrimary"))
        p.drawEllipse(QPointF(track.center().x(), head),
                      5 if self._volume_drag else 4, 5 if self._volume_drag else 4)
        p.restore()
        mute = QRectF(popup.center().x() - 17, popup.bottom() - 18, 34, 16)
        render.paint_button(p, mute, "恢复" if muted else "静音", theme,
                            active=muted, px=9)
        self._hits.append((mute, "music_volume_mute", None))
