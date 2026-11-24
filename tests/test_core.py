"""Plain asserts: theme loading, contrast, geometry bounds, config round-trip.

    .build-venv/bin/python tests/test_core.py
"""
import os
import sys
import subprocess
import tempfile
import time
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["UKUI_ISLAND_CONFIG_DIR"] = tempfile.mkdtemp() + "/config"
os.environ["UKUI_ISLAND_STATE_DIR"] = tempfile.mkdtemp() + "/state"

from island import (__version__, activity, autostart, calendar, config, geometry,
                    lyrics, mail, motion,
                    meeting, music, productivity, quota, render, sources,
                    stock, theme, weather)  # noqa: E402


def test_themes():
    ids = theme.list_themes()
    assert "classic" in ids and len(ids) >= 5, ids
    for tid in ids:
        t = theme.load(tid)
        assert t.material.get("kind") in ("opaque", "glass", "fluid"), tid
        for token in theme.REQUIRED:
            assert t.colors[token].isValid(), f"{tid}/{token}"
        for token in theme.TEXT_TOKENS:
            got = theme.contrast(t.colors[token], t.colors["surface"])
            assert got >= 4.49, f"{tid}/{token} contrast {got:.2f}"
    cream = theme.load("cream")
    assert theme.contrast(cream.color("textPrimary"), cream.color("surface")) > 7


def test_geometry():
    for style in config.STYLES:
        for scale in (80, 100, 140):
            s = geometry.resolve(style, 1920, scale, content_width=128)
            assert s.rect.width() > 0 and s.rect.height() > 0, (style, scale)
            assert s.rect.left() >= -1 and s.rect.right() <= 1921, (style, scale, s.rect)
            assert s.rect.top() >= 0
            if style == "notch":
                assert s.rect.top() == 0
            if style == "capsule":
                assert s.rect.top() == geometry.CAPSULE_TOP
            if style == "line":
                assert s.rect.height() == geometry.LINE_H
    narrow = geometry.resolve("notch", 200)
    assert narrow.rect.width() <= 200
    grown = geometry.resolve("capsule", 1920, 100, content_width=400)
    assert grown.rect.width() > geometry.CAPSULE_W
    for style in config.STYLES:
        wide = geometry.resolve(style, 1920, 100, content_width=1000)
        panel = geometry.expanded(style, 1920, 100)
        assert wide.rect.width() <= panel.rect.width(), (style, wide.rect.width())


def test_config_roundtrip():
    cfg = dict(config.DEFAULTS)
    cfg.update({"theme": "cream", "style": "capsule", "scale": 999, "clock_12h": True,
                "clock_period": 2, "show_weekday": True, "clock_english": True,
                "show_weather": False, "show_monitor": False,
                "weather_city": "上海",
                "mail_host": "imap.example.com", "mail_port": 143,
                "mail_user": "me@example.com", "mail_password": "secret",
                "calendar_url": "/tmp/a.ics", "quota_url": "http://127.0.0.1/q",
                "quota_token": "relay-secret",
                "stock_code": "600519", "show_stock": False,
                "focus_minutes": 45, "rest_minutes": 10,
                "focus_remind": False, "water_remind": False,
                "water_minutes": 60, "mail_remind": False,
                "show_pet": False, "click_through": True,
                "hide_fullscreen": False,
                "enable_blur": False})
    config.save(config._clean(cfg))
    loaded = config.load()
    assert loaded["theme"] == "cream" and loaded["style"] == "capsule"
    assert loaded["scale"] == 140 and loaded["clock_12h"] is True
    assert loaded["clock_period"] == 2
    assert loaded["stock_code"] == "sh600519" and loaded["show_stock"] is False
    assert loaded["show_weekday"] is True and loaded["clock_english"] is True
    assert loaded["show_weather"] is False
    assert loaded["show_monitor"] is False
    assert loaded["weather_city"] == "上海"
    assert loaded["quota_token"] == "relay-secret"
    assert loaded["mail_host"] == "imap.example.com"
    assert loaded["mail_port"] == 143 and loaded["mail_tls"] is True
    assert loaded["focus_minutes"] == 45 and loaded["rest_minutes"] == 10
    assert loaded["focus_remind"] is False and loaded["water_remind"] is False
    assert loaded["water_minutes"] == 60 and loaded["mail_remind"] is False
    assert loaded["show_pet"] is False and loaded["click_through"] is True
    assert loaded["hide_fullscreen"] is False and loaded["enable_blur"] is False
    assert oct(os.stat(config.config_path()).st_mode & 0o777) == "0o600"
    config.config_path().write_text("{not json")
    assert config.load() == config.DEFAULTS
    assert "JSONDecodeError" in config.LOAD_ERROR


def test_spring_and_morph():
    s = motion.Spring(0.0, 330.0, 0.70)
    s.target = 1.0
    peak = 0.0
    for _ in range(60):
        s.step(1.0 / 60.0)
        peak = max(peak, s.value)
    assert 1.0 < peak < 1.08, peak
    assert not s.moving(), (s.value, s.velocity)

    a = motion.Spring(0.0, 300.0, 0.75)
    b = motion.Spring(0.0, 300.0, 0.75)
    a.target = b.target = 1.0
    for _ in range(30):
        a.step(1.0 / 30.0)
    for _ in range(144):
        b.step(1.0 / 144.0)
    assert abs(a.value - b.value) < 0.01, (a.value, b.value)

    a.target = 0.0
    before = a.value
    a.step(1.0 / 60.0)
    assert a.value < before and abs(a.value - before) < 0.1, (before, a.value)

    for style in config.STYLES:
        base = geometry.resolve(style, 1920, 100, content_width=128)
        grown = geometry.expanded(style, 1920, 100)
        at_base = geometry.morph(base, grown, base.rect.width(), base.rect.height())
        at_open = geometry.morph(base, grown, grown.rect.width(), grown.rect.height())
        assert at_base.shoulder == base.shoulder
        assert abs(at_base.bottom_radius - base.bottom_radius) < 1e-6
        assert at_open.shoulder == 0 and at_open.top_radius == geometry.PANEL_RADIUS

    base = geometry.resolve("capsule", 1920, 100, content_width=128)
    opened = geometry.expanded("capsule", 1920, 100)
    part = geometry.morph(base, opened, 300, 80)
    for shape in (base, part, opened):
        box = geometry.window_rect(shape)
        assert box.left() == shape.bounds.left() - geometry.EDGE
        assert box.bottom() == shape.bounds.bottom() + geometry.SHADOW


def test_sources_and_weather():
    before = sources.cpu_times("cpu  100 0 100 800 0 0 0 0 0 0")
    after = sources.cpu_times("cpu  150 0 150 900 0 0 0 0 0 0")
    idle = after[0] - before[0]
    total = after[1] - before[1]
    assert total == 200 and idle == 100
    assert sources.format_rate(1536) == "2K"
    assert sources.format_rate(2_500_000) == "2.5M"
    assert weather.describe("Light rain") == "小雨"
    assert weather.describe("Patchy light rain with thunder") == "雷雨"
    assert weather.describe("") == "未知"
    parsed = weather.parse_current(
        {"current_condition": [{"temp_C": "12.4",
                                "weatherDesc": [{"value": "Partly cloudy"}]}]}, "北京")
    assert parsed["temp"] == 12.4 and parsed["text"] == "多云"
    assert weather.parse_current({}) is None
    assert weather.text_for_code(61) == "小雨"
    parsed = weather.parse_forecast({
        "current": {"temperature_2m": 10.2, "weather_code": 3,
                    "relative_humidity_2m": 81, "wind_speed_10m": 1.3,
                    "apparent_temperature": 9.2},
        "daily": {"time": ["2026-11-19", "2026-11-20"],
                  "weather_code": [3, 61],
                  "temperature_2m_max": [16.8, 15.9],
                  "temperature_2m_min": [8.0, 7.1],
                  "precipitation_probability_max": [10, 80],
                  "sunrise": ["2026-11-19T06:52"],
                  "sunset": ["2026-11-19T17:38"]}},
        {"name": "北京", "region": "北京"})
    assert parsed["text"] == "阴" and len(parsed["daily"]) == 2
    assert parsed["daily"][1]["text"] == "小雨"
    assert parsed["daily"][0]["high"] == 16.8
    thread = weather.Weather({"weather_city": "北京"})
    thread.refresh()
    assert thread._force and thread._wake.is_set()
    weather._cache_path().write_text("{bad cache", encoding="utf-8")
    errors = []
    assert weather.load_cache(None, "北京", errors) is None
    assert errors and "JSONDecodeError" in errors[0]


def test_music_metadata():
    props = {
        "PlaybackStatus": ("s", "Playing"),
        "Position": ("x", 42_000_000),
        "CanGoNext": ("b", True),
        "CanGoPrevious": ("b", False),
        "CanSeek": ("b", True),
        "Metadata": ("a{sv}", {
            "xesam:title": ("s", "晴天"),
            "xesam:artist": ("as", ["周杰伦"]),
            "mpris:length": ("x", 215_000_000),
            "mpris:artUrl": ("s", "file:///tmp/cover.png"),
            "mpris:trackid": ("o", "/org/mpris/MediaPlayer2/Track/42"),
        }),
    }
    state = music.parse_state(props)
    assert state["title"] == "晴天" and state["artist"] == "周杰伦"
    assert state["position"] == 42 and state["length"] == 215
    assert state["status"] == "Playing" and state["can_next"] is True
    assert state["can_seek"] is True
    assert state["track_id"] == "/org/mpris/MediaPlayer2/Track/42"
    assert render.seek_seconds(10, 10, 100, 200) == 0
    assert render.seek_seconds(60, 10, 100, 200) == 100
    assert render.seek_seconds(200, 10, 100, 200) == 200
    assert render.seek_seconds(60, 10, 0, 200) == 0
    assert music.format_time(215) == "3:35" and music.format_time(None) == "0:00"
    window = music.parse_window_title("▶ 晴天 - 360安全浏览器v13")
    assert window["title"] == "晴天" and window["status"] == "Playing"
    assert window["app"] == "浏览器"
    assert music.parse_window_title("普通标签页") is None
    assert music.clean_title("▶ Test Song - Google Chrome") == "Test Song"
    assert music.clean_title("Song - Artist") == "Song - Artist"
    lines = lyrics.parse_lrc("[00:01.50]第一句\n[00:03.00][00:05.00]重复\n"
                             "[by:x]\n[00:00.00]作词 : 某人")
    assert lines == [(1.5, "第一句"), (3.0, "重复"), (5.0, "重复")]
    assert lyrics.current_line(lines, 0.5) == ""
    assert lyrics.current_line(lines, 3.4) == "重复"
    songs = [{"id": 1, "name": "唯一", "duration": 262400},
             {"id": 2, "name": "唯一", "duration": 180000},
             {"id": 3, "name": "唯一(Live)", "duration": 262000}]
    assert lyrics.candidates(songs, "唯一", 262.2) == [1]
    assert render.marquee_offset(100, 120, 10) == 0
    assert render.marquee_offset(200, 100, 1.5) == 36
    assert music.player_label("org.mpris.MediaPlayer2.chromium.instance1") == "Chrome/Chromium"


def test_productivity_store():
    path = Path(tempfile.mkdtemp()) / "productivity.json"
    store = productivity.Productivity(path)
    assert store.add_todo("买牛奶") and store.add_todo("写周报")
    assert store.todos[0]["text"] == "写周报"
    assert store.toggle_todo(0) and store.todos[0]["done"] is True
    assert store.add_water(250) and store.water_ml == 250
    assert abs(store.water_percent() - 0.125) < 1e-9
    assert store.record_clip("复制的文字", "09:30")
    assert not store.record_clip("复制的文字", "09:31")
    assert store.add_shelf("/etc/hosts")
    assert not store.add_shelf("/definitely/not/here")
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"
    again = productivity.Productivity(path)
    assert again.todos[0]["text"] == "写周报" and again.todos[0]["done"]
    assert again.water_ml == 250
    assert again.clips[0]["text"] == "复制的文字"
    assert again.shelf == ["/etc/hosts"]
    assert again.clear_done_todos() is None and again.todos[0]["text"] == "买牛奶"
    assert again.remove_todo(0) and again.remove_clip(0)
    assert again.remove_shelf(0) and not again.todos and not again.shelf
    broken = Path(tempfile.mkdtemp()) / "productivity.json"
    broken.write_text("{bad json", encoding="utf-8")
    failed = productivity.Productivity(broken)
    assert failed.load_error and not failed.todos


def test_logging():
    from island import app as island_app

    log = config.state_dir() / "island.log"
    if log.exists():
        log.unlink()
    island_app._log("probe", "WARN")
    fake = object.__new__(island_app.IslandApp)
    fake._issues = {}
    fake._report_issue("weather", "offline")
    fake._report_issue("weather", "offline")
    fake._report_issue("weather", "timeout")
    fake._clear_issue("weather")
    fake._source_status("stock", {"status": "error", "error": "boom"},
                        "sh000001")
    fake._source_status("stock", {"status": "ok"})

    class Window:
        def set_weather(self, value):
            pass

    fake.window = Window()
    fake._on_weather({"place": "北京", "temp": None, "stale": True,
                      "error": "Timeout"})
    fake._on_weather({"place": "北京", "temp": 12, "stale": True})
    fake._on_weather({"place": "北京", "temp": 12, "stale": False})
    text = log.read_text(encoding="utf-8")
    assert "[WARN]" in text and "probe" in text
    assert text.count("weather: offline") == 1
    assert "weather: timeout" in text
    assert "weather: recovered" in text
    assert "stock: sh000001: boom" in text
    assert "stock: recovered" in text
    assert "weather: Timeout" in text
    assert "weather: recovered" in text


def test_todo_repeat_and_clip_pin():
    path = Path(tempfile.mkdtemp()) / "productivity.json"
    store = productivity.Productivity(path)
    tuesday = date(2026, 11, 17)
    assert store.add_todo("每天跑步", list(range(7)))
    assert store.add_todo("周三复盘", [0, 2, 4])
    order = store.display_order(tuesday)
    due = store.todos.index(next(item for item in store.todos
                                 if item["text"] == "每天跑步"))
    later = store.todos.index(next(item for item in store.todos
                                   if item["text"] == "周三复盘"))
    assert order[0] == due and order[-1] == later
    assert store.progress(tuesday) == (0, 1)
    assert store.toggle_todo(later, tuesday) is False
    assert store.toggle_todo(due, tuesday)
    assert store.todo_done(store.todos[due], tuesday)
    assert store.progress(tuesday) == (1, 1)
    assert store.update_todo(due, "晨跑", list(range(7)), "07:30")
    assert store.todos[due]["text"] == "晨跑"
    assert store.todos[due]["remind"] == "07:30"
    store.clear_done_todos(tuesday)
    assert len(store.todos) == 2
    assert not store.todo_done(store.todos[due], tuesday)
    assert productivity.repeat_tag([0, 1, 2, 3, 4]) == "工作日"
    assert productivity.repeat_tag([0, 2, 4]) == "周一三五"

    assert store.record_clip("固定的内容", "09:10")
    assert store.toggle_pin(0)
    assert store.record_clip("临时内容", "09:11")
    store.clear_clips()
    assert [item["text"] for item in store.clips] == ["固定的内容"]
    again = productivity.Productivity(path)
    assert again.clips[0]["pinned"] is True
    assert again.todos[due]["repeat"] == list(range(7))
    assert again.add_water(250) and again.undo_water()
    assert again.water_ml == 0


def test_mail_parsing():
    assert mail.extract_code("您的验证码是 482913") == "482913"
    assert mail.extract_code("Verification code: 731904") == "731904"
    assert mail.extract_code("Your OTP is 1234, valid 5 min") == "1234"
    assert mail.extract_code("会议改到 2026 年") == ""
    from email.message import Message
    msg = Message()
    msg["From"] = "王工 <wang@example.com>"
    msg["Subject"] = "您的验证码是 886611"
    msg["Date"] = "Tue, 17 Nov 2026 12:00:00 +0800"
    parsed = mail.parse_message(msg.as_bytes())
    assert parsed["sender"].startswith("王工")
    assert parsed["subject"] == "您的验证码是 886611"
    assert parsed["code"] == "886611"
    preview = mail.parse_message(
        b"From: a@b\r\nSubject: hi", b"Hello world")
    assert preview["preview"] == "Hello world"
    assert mail._flags_part([(b"1 (FLAGS (\\Seen)) {10}", b"x")]) == b"\\Seen"

    class Box:
        def list(self):
            return None, [b'(\\HasNoChildren) "/" "INBOX"',
                          b'(\\HasNoChildren \\Trash) "/" "Deleted Messages"']

    assert mail.trash_folder(Box()) == "Deleted Messages"


def test_mail_mark_seen_reply():
    # mark_seen 必须看服务器回包，不能把自己当成功
    class Box:
        def __init__(self, typ, rows, fetch=None):
            self.typ, self.rows, self.fetch = typ, rows, fetch
            self.stored = []
        def login(self, user, password):
            pass
        def select(self, mailbox, readonly=False):
            self.readonly = readonly
            return "OK", [b"1"]
        def uid(self, cmd, *args):
            self.stored.append((cmd,) + args)
            if cmd == "store":
                return self.typ, self.rows
            if cmd == "search":
                return "OK", [b"4 5"]
            return "OK", (self.fetch if self.fetch is not None
                          else [b"4 (UID 4 FLAGS (\\Seen))"])
        def logout(self):
            pass

    cfg = {"mail_host": "h", "mail_user": "u", "mail_password": "p"}
    original = mail._open_box
    try:
        box = Box("OK", [b"4 (UID 4 FLAGS ())"])
        mail._open_box = lambda c: box
        ok = mail.mark_seen(cfg, "4", False)
        assert ok["status"] == "ok", ok
        assert box.stored[0][:3] == ("store", "4", "-FLAGS"), box.stored
        assert box.readonly is False
        # 服务器回 NO：报错，不能报“已同步”
        mail._open_box = lambda c: Box("NO", [b"Store rejected"])
        bad = mail.mark_seen(cfg, "4", False)
        assert bad["status"] == "error" and "rejected" in bad["error"], bad
        # 服务器说改了但 FLAGS 里还有 \Seen：报错
        mail._open_box = lambda c: Box("OK", [b"4 (UID 4 FLAGS (\\Seen))"])
        liar = mail.mark_seen(cfg, "4", False)
        assert liar["status"] == "error", liar
        # 完全不回包：邮件已不在收件箱
        mail._open_box = lambda c: Box("OK", [None], fetch=[None])
        gone = mail.mark_seen(cfg, "4", False)
        assert gone["status"] == "error" and "收件箱" in gone["error"], gone
        # 全部已读仍然按回包判断
        rows = [b"4 (FLAGS (\\Seen))", b"5 (FLAGS (\\Seen))"]
        mail._open_box = lambda c: Box("OK", rows)
        assert mail.mark_seen(cfg)["status"] == "ok"
    finally:
        mail._open_box = original


def test_mail_operation_queue():
    # 上一条写操作还在跑时，新点击不能悄悄丢掉
    from island import app as island_app

    started = []

    class Worker:
        busy = [False]

        def __init__(self, cfg, action, uid=None, parent=None):
            self.action, self.uid = action, uid
            self.done, self.finished = _Sig(), _Sig()
        def isRunning(self):
            return Worker.busy[0]
        def start(self):
            started.append((self.action, self.uid))
            Worker.busy[0] = True

    class _Sig:
        def __init__(self):
            self.slots = []
        def connect(self, slot):
            self.slots.append(slot)
        def fire(self):
            for slot in self.slots:
                slot()

    fake = object.__new__(island_app.IslandApp)
    fake.cfg = {}
    fake._mail_worker = None
    fake._mail_pending_op = None
    fake._on_mail_operation = lambda result: None
    original = island_app.MailAction
    island_app.MailAction = Worker
    try:
        fake._mail_operation("seen", "7")
        assert started == [("seen", "7")], started
        fake._mail_operation("unseen", "8")   # 还在跑，先排队
        assert started == [("seen", "7")], started
        fake._mail_worker.finished.fire()     # 上一条跑完
        assert started == [("seen", "7"), ("unseen", "8")], started
        assert fake._mail_pending_op is None
    finally:
        island_app.MailAction = original
        Worker.busy[0] = False


def test_calendar_parsing():
    tomorrow = datetime.now().date() + timedelta(days=1)
    day_after = tomorrow + timedelta(days=1)
    ics = (
        "BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\n"
        "SUMMARY:产品评审\r\n"
        f"DTSTART:{tomorrow:%Y%m%d}T100000\r\n"
        f"DTEND:{tomorrow:%Y%m%d}T110000\r\n"
        "LOCATION:3F\r\nEND:VEVENT\r\n"
        "BEGIN:VEVENT\r\nSUMMARY:一段很长\r\n 的标题\r\n"
        f"DTSTART;VALUE=DATE:{day_after:%Y%m%d}\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    events = calendar.parse_ics(ics)
    assert len(events) == 2, events
    assert events[0]["summary"] == "产品评审" and events[0]["place"] == "3F"
    assert events[1]["summary"] == "一段很长的标题" and events[1]["all_day"] is True
    now = events[0]["start"].replace(hour=9, minute=0)
    rows = calendar.upcoming(events, now=now)
    assert len(rows) == 2 and rows[0]["summary"] == "产品评审"
    assert calendar.event_text(events[0]).endswith("10:00")
    assert calendar.event_text(events[1]).endswith("全天")
    ics_path = Path(tempfile.mkdtemp()) / "demo.ics"
    ics_path.write_text(ics, encoding="utf-8")
    loaded = calendar.load_calendar(str(ics_path))
    assert loaded["status"] == "ok" and len(loaded["items"]) == 2
    assert calendar.load_calendar("/missing.ics")["status"] == "error"
    assert calendar.load_calendar("")["status"] == "unconfigured"
    assert mail.fetch_inbox("", 993, "", "")["status"] == "unconfigured"


def test_stock_parsing():
    fields = (["1", "上证指数", "000001", "3587.83", "3584.58", "3596.55",
               "423934832"] + ["0"] * 23
              + ["20261118161500", "3.25", "0.09", "3596.55", "3560.45"])
    quote = stock.parse_quote('v_sh000001="' + "~".join(fields) + '";')
    assert quote["status"] == "ok" and quote["name"] == "上证指数"
    assert quote["price"] == 3587.83 and quote["change_pct"] == 0.09
    assert quote["high"] == 3596.55 and quote["at"] == "16:15"
    hk = list(fields)
    hk[30] = "2026/11/18 16:08:10"
    assert stock.parse_quote('v_hk00700="' + "~".join(hk) + '";')["at"] == "16:08"
    payload = {"data": {"sh000001": {"data": {
        "date": "20261118",
        "data": ["0930 3596.55 1 1", "0931 3582.44 2 2"]}}}}
    assert stock.parse_minutes(payload, "sh000001") == [
        ["0930", 3596.55], ["0931", 3582.44]]
    assert stock.normalize_code("600519") == "sh600519"
    assert stock.normalize_code("000858") == "sz000858"
    assert stock.normalize_code("00700") == "hk00700"
    assert stock.normalize_code("AAPL") == "usAAPL"
    assert stock.normalize_code("sh000001") == "sh000001"
    assert stock.normalize_code("no way") == ""
    assert quote["date"] == "20261118"


def _at(day, hour, minute):
    return day.replace(hour=hour, minute=minute)


def _us_at(day, hour, minute):
    """美东交易所墙钟 -> 等价的本机时间，CI 在任意时区都成立。"""
    exchange = day.replace(hour=hour, minute=minute)
    base = exchange - timedelta(hours=stock.US_UTC_OFFSET)
    for delta in range(-26, 27):
        candidate = base + timedelta(hours=delta)
        if (stock.local_now("usAAPL", candidate)
                .replace(second=0, microsecond=0) == exchange):
            return candidate
    raise AssertionError(f"cannot map {exchange} to local time")


def test_stock_session():
    assert stock.stamp_date("20261119161427") == "20261119"
    assert stock.stamp_date("2026-11-18 16:08:13") == "20261118"
    assert stock.stamp_date("") == ""
    monday = datetime(2026, 11, 16)
    assert stock.in_session("sh000001", _at(monday, 9, 30))
    assert stock.in_session("sh000001", _at(monday, 12, 0))
    assert stock.in_session("sh000001", _at(monday, 15, 14))
    assert not stock.in_session("sh000001", _at(monday, 15, 15))
    assert not stock.in_session("sh000001", _at(monday, 9, 29))
    assert stock.in_session("sh000001", _at(monday, 15, 40), grace_minutes=60)
    assert not stock.in_session("sh000001", _at(monday, 15, 0), grace_minutes=0)
    weekend = monday + timedelta(days=6)
    assert not stock.in_session("sh000001", _at(weekend, 10, 0))
    assert stock.in_session("hk00700", _at(monday, 15, 50))
    assert not stock.in_session("hk00700", _at(monday, 16, 20))
    # 美股 09:30-16:00 美东，含收盘 15 分钟宽限；按交易所墙钟换算，不绑本机时区
    assert stock.in_session("usAAPL", _us_at(monday, 10, 0))
    assert not stock.in_session("usAAPL", _us_at(monday, 9, 0))
    assert stock.in_session("usAAPL", _us_at(monday, 15, 10))
    assert stock.in_session("usAAPL", _us_at(monday, 16, 10))
    assert not stock.in_session("usAAPL", _us_at(monday, 16, 20))
    july = datetime(2026, 7, 15)  # 夏令时：09:30 EDT
    assert stock.in_session("usAAPL", _us_at(july, 10, 0))
    assert not stock.in_session("usAAPL", _us_at(july, 9, 0))
    assert stock.in_session("unknown", _at(monday, 3, 0))
    assert stock.quote_fresh("sh000001", "20261116", monday)
    assert not stock.quote_fresh("sh000001", "20261113", monday)
    assert stock.quote_fresh("sh000001", "", monday)
    assert stock.chip_visible("sh000001", "20261116", _at(monday, 15, 10))
    assert not stock.chip_visible("sh000001", "20261116", _at(monday, 15, 10),
                                  grace_minutes=0)
    assert not stock.chip_visible("sh000001", "20261116", _at(monday, 15, 30))
    assert not stock.chip_visible("sh000001", "20261113", _at(monday, 10, 0))
    assert stock.chip_visible("sh000001", "20261113", _at(monday, 10, 0),
                              enabled=False)


def test_meeting_invite():
    now = datetime.now()
    later = (now + timedelta(days=3)).strftime("%Y/%m/%d")
    soon = now.replace(hour=min(23, now.hour + 1), minute=0)
    invite = ("温建春 邀请您参加腾讯会议\n"
              "会议主题：中行生产物料交付评审\n"
              f"会议时间：{later} 09:20-09:50 (GMT+08:00) 中国标准时间 - 北京\n\n"
              "点击链接入会，或添加至会议列表：\n"
              "https://meeting.tencent.com/dm/arNC46twIeG3\n\n"
              "#腾讯会议：902-631-704\n\n"
              "复制该信息，打开手机腾讯会议即可参与")
    got = meeting.parse_meeting(invite)
    assert got["text"].endswith("中行生产物料交付评审"), got
    assert got["code"] == "902631704", got
    assert got["remind_on"] == (now + timedelta(days=3)).date().isoformat(), got
    short = meeting.parse_meeting(
        f"会议主题：中行生产环境备份功能沟通\n"
        f"会议时间：{soon:%Y/%m/%d} {soon:%H:%M}-17:45\n"
        "#腾讯会议：370-268-672")
    assert short["remind"] == f"{soon:%H:%M}", short
    assert short["remind_on"] == soon.date().isoformat(), short
    assert short["code"] == "370268672", short
    gone = meeting.parse_meeting(
        f"会议主题：昨天的会\n会议时间：{now - timedelta(days=1):%Y/%m/%d} "
        "09:00-09:30")
    assert gone["remind"] == "" and gone["remind_on"] == "", gone
    assert gone["past"], gone
    assert meeting.parse_meeting("会议主题：季度复盘\n会议时间：12 月 30 日") is None
    assert meeting.parse_meeting("复制的文字 会议 902-631-704") is None
    assert meeting.parse_meeting("") is None


def test_meeting_notice():
    notice = ("@全体成员 关于召开全体党员大会的通知\n\n"
              "支部全体党员：\n"
              "  定于2099年11月12日召开全体党员大会。现将有关事项通知如下：\n"
              "   一、时间2099年11月12日（星期五）下午16：00\n"
              "   二、地点\n"
              "   北京   1102会议室\n"
              "   天津 北斗1104会议室\n"
              "其余地区蓝信接入，蓝信会议号  910115509386\n"
              "   三、参加人员\n   支部全体党员\n")
    got = meeting.parse_meeting(notice)
    assert got["title"] == "关于召开全体党员大会的通知", got
    assert got["text"] == "11/12 16:00 关于召开全体党员大会的通知", got
    assert got["remind"] == "16:00" and got["remind_on"] == "2099-11-12", got
    assert got["place"] == "北京 1102会议室；天津 北斗1104会议室", got
    assert got["code"] == "910115509386", got
    assert meeting.parse_meeting("2099年11月12日的会议改期，另定时间") is None
    assert meeting.parse_meeting("会议通知：明天上午开会") is None


def test_meeting_notice_markdown_copy():
    """A rich-text copy keeps literal backslash line breaks and &#x20;."""
    escaped = ("@全体成员 关于召开全体党员大会的通知\\\n\\\n"
               "支部全体党员：\\\n&#x20;   一、时间2099年11月12日（星期五）下午16：00\\\n"
               "&#x20;   二、地点\\\n&#x20;   北京   1102会议室\\\n"
               "&#x20;   天津 北斗1104会议室\\\n其余地区蓝信接入，蓝信会议号  910115509386\\\n"
               "&#x20;   三、参加人员\\\n&#x20;  1\\. 参会时请佩戴党徽。")
    got = meeting.parse_meeting(escaped)
    assert got["title"] == "关于召开全体党员大会的通知", got
    assert "\\" not in got["text"], got
    assert got["place"] == "北京 1102会议室；天津 北斗1104会议室", got
    assert got["code"] == "910115509386", got
    assert meeting._plain(r"会议主题：C:\Users\lyx\n会议时间：2099-01-01 09:20") == (
        r"会议主题:C:\Users\lyx\n会议时间:2099-01-01 09:20")


def test_todo_meeting_details():
    invite = ("会议主题：交付评审\n会议时间：2099-01-01 09:20-09:50\n"
              "入会链接：https://meeting.tencent.com/dm/abc123，\n"
              "#腾讯会议：902-631-704\n会议地点：3 楼 302 会议室")
    got = meeting.parse_meeting(invite)
    assert got["code"] == "902631704", got
    assert got["place"] == "3 楼 302 会议室", got
    assert got["link"] == "https://meeting.tencent.com/dm/abc123", got
    assert meeting.parse_meeting("会议主题：无地点\n会议时间：2099-01-01 09:20")[
        "place"] == ""

    path = Path(tempfile.mkdtemp()) / "productivity.json"
    store = productivity.Productivity(path)
    assert store.add_todo("评审", None, "09:20", "2099-01-01", got)
    saved = store.todos[0]["meeting"]
    assert saved["code"] == "902631704" and saved["place"] == "3 楼 302 会议室"
    assert store.add_todo("超长", None, "", "", {
        "code": "9" * 80, "place": "房" * 80, "link": "u" * 400, "junk": "x"})
    capped = store.todos[0]["meeting"]
    assert len(capped["code"]) == 32 and len(capped["place"]) == 60
    assert len(capped["link"]) == 300 and "junk" not in capped
    assert productivity.clean_meeting(None) == {}
    assert productivity.clean_meeting("不是字典") == {}
    again = productivity.Productivity(path)
    assert again.todos[1]["meeting"]["code"] == "902631704"


def test_todo_remind_on():
    path = Path(tempfile.mkdtemp()) / "productivity.json"
    store = productivity.Productivity(path)
    today = date(2026, 11, 20)
    later = today + timedelta(days=2)
    assert store.add_todo("11/22 09:20 后天的评审", None, "09:20",
                          later.isoformat())
    assert store.add_todo("11/20 14:00 今天的评审", None, "14:00",
                          today.isoformat())
    today_item, later_item = store.todos[0], store.todos[1]
    assert today_item["remind_on"] == today.isoformat()
    assert later_item["remind_on"] == later.isoformat()
    # 只有当天的 dated 待办算今日，非当天的不污染进度也不排前面
    assert store.progress(today) == (0, 1)
    assert store.progress(later) == (0, 1)
    assert store.progress(today + timedelta(days=1)) == (0, 0)
    assert store.display_order(today)[0] == 0
    assert store.todo_due(today_item, today)
    assert not store.todo_due(today_item, later)
    assert not store.todo_due(later_item, today)
    assert store.todo_due(later_item, later)
    # 过期了也还能勾掉
    assert store.toggle_todo(0, today) and store.toggle_todo(1, today)
    assert store.progress(today) == (1, 1), "非当天的不计入今日"
    assert store.progress(later) == (1, 1)
    again = productivity.Productivity(path)
    assert [item["remind_on"] for item in again.todos] == [
        today.isoformat(), later.isoformat()]
    # 没有 remind_on 的旧数据按原样走重复判定
    legacy = {"text": "老待办", "done": False, "repeat": [], "done_on": "",
              "remind": "14:00"}
    assert store.todo_due(legacy, today) and store.todo_due(legacy, later)
    # 手动设了重复就按重复走，日期不再压住它
    both = {"text": "每天但带日期", "done": False, "repeat": list(range(7)),
            "done_on": "", "remind": "14:00", "remind_on": today.isoformat()}
    assert store.todo_due(both, today) and store.todo_due(both, later)


def test_quota_parsing():
    assert quota.parse_url_payload({"percent": 42})["percent"] == 0.42
    assert quota.parse_url_payload({"data": {"percent": 0.25}})["percent"] == 0.25
    assert quota.parse_url_payload({"usage": {"used": 25, "total": 100}})["percent"] == 0.25
    assert quota.parse_url_payload({"balance": 12.5})["text"] == "12.5"
    try:
        quota.parse_url_payload({"nope": 1})
    except ValueError:
        pass
    else:
        raise AssertionError("invalid payload accepted")

    home = Path(tempfile.mkdtemp())
    codex = home / ".codex/sessions/2026/11/17"
    codex.mkdir(parents=True)
    (codex / "rollout.jsonl").write_text(
        '{"type":"event_msg","payload":{"total_token_usage":'
        '{"input_tokens":100,"output_tokens":23,"total_tokens":123}}}\n',
        encoding="utf-8")
    assert quota.codex_usage(home)["total"] == 123
    claude = home / ".claude/projects/-tmp"
    claude.mkdir(parents=True)
    from datetime import date
    (claude / "session.jsonl").write_text(
        '{"timestamp":"%sT10:00:00Z","message":{"usage":'
        '{"input_tokens":10,"output_tokens":5,"cache_read_input_tokens":7}}}\n'
        % date.today().isoformat(), encoding="utf-8")
    assert quota.claude_usage(home)["total"] == 22

    import http.server
    import threading

    seen = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.headers.get("Authorization"))
            body = b'{"percent":25}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        parsed = quota.http_quota(
            "http://127.0.0.1:%d/q" % server.server_address[1],
            token="relay-key")
    finally:
        server.shutdown()
    assert parsed["status"] == "ok" and parsed["percent"] == 0.25
    assert seen[-1] == "Bearer relay-key"


def test_codex_quota_snapshot_and_claude_history():
    home = Path(tempfile.mkdtemp())
    now = time.time()
    codex = home / ".codex/sessions/2026/11/17"
    codex.mkdir(parents=True)
    (codex / "rollout.jsonl").write_text(
        '{"timestamp":"%s","type":"event_msg","payload":{"type":"token_count",'
        '"rate_limits":{"plan_type":"pro","primary":{"used_percent":74,'
        '"window_minutes":43200,"resets_at":%d}}}}\n'
        % (date.today().isoformat() + "T10:00:00Z", int(now + 3600)),
        encoding="utf-8")
    limits, stamp = quota.latest_codex_limits(home, now=now)
    assert limits["plan_type"] == "pro" and stamp > 0
    metrics = quota.parse_codex_limits(limits, now=now)
    assert len(metrics) == 1 and metrics[0]["label"] == "30 天"
    assert abs(metrics[0]["remaining"] - 0.26) < 0.001
    assert "重置" in metrics[0]["reset_text"]
    assert not quota.parse_codex_limits(
        {"primary": {"used_percent": 10, "window_minutes": 300,
                     "resets_at": int(now - 120)}}, now=now)

    profile = home / ".config/Claude/plan-usage-history.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(
        '{"samples":[{"t":%d,"u":{"fh":12,"sd":34}}]}'
        % int(now * 1000), encoding="utf-8")
    history = quota.claude_history(home, now=now)
    assert [item["label"] for item in history] == ["5 小时", "本周"]
    assert abs(history[0]["used"] - 0.12) < 0.001
    cfg = dict(config.DEFAULTS)
    result = quota.collect(cfg, home=home)
    assert [item["id"] for item in result["providers"]] == [
        "codex", "claude", "workbuddy"]


def test_workbuddy_usage():
    import json

    home = Path(tempfile.mkdtemp())
    traces = home / ".workbuddy/traces/123"
    traces.mkdir(parents=True)
    today = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    (traces / "trace_a.json").write_text(json.dumps({
        "trace": {"sessionId": "s1", "totalTokens": 1500,
                  "startedAt": today.isoformat(),
                  "metadata": {"note": "a } b { c"}},
        "spans": [{"name": "span"}]}), encoding="utf-8")
    (traces / "trace_b.json").write_text(json.dumps({
        "trace": {"sessionId": "s1", "totalTokens": 500,
                  "startedAt": today.isoformat()},
        "spans": []}), encoding="utf-8")
    (traces / "trace_old.json").write_text(json.dumps({
        "trace": {"sessionId": "s0", "totalTokens": 9_999_999,
                  "startedAt": (today - timedelta(days=3)).isoformat()},
        "spans": []}), encoding="utf-8")
    usage = quota.workbuddy_usage(home)
    assert usage["total"] == 2000 and usage["sessions"] == 1
    cfg = dict(config.DEFAULTS)
    provider = next(item for item in quota.collect(
        cfg, home=home)["providers"]
        if item["id"] == "workbuddy")
    assert provider["status"] == "ok" and provider["usage"]["today"] == 2000


def test_activity_parsing():
    state = activity.empty()
    activity.parse_codex(
        state, {"type": "event_msg", "payload": {"type": "user_message"}}, 1.0)
    assert state["state"] == "thinking" and state["active"]
    activity.parse_codex(
        state, {"type": "response_item",
                "payload": {"type": "function_call", "name": "exec_command"}},
        2.0)
    assert state["label"] == "正在执行"
    activity.parse_codex(
        state, {"type": "event_msg",
                "payload": {"type": "agent_message", "message": "已修复 X"}},
        3.0)
    assert state["state"] == "responding" and state["detail"] == "已修复 X"
    activity.parse_codex(
        state, {"type": "event_msg",
                "payload": {"type": "task_complete",
                            "last_agent_message": "完成 X"}}, 4.0)
    assert state["state"] == "completed" and not state["active"]
    assert state["detail"] == "完成 X"

    claude = activity.empty("Claude")
    activity.parse_claude(
        claude, {"type": "assistant",
                 "message": {"model": "claude", "content": [
                     {"type": "tool_use", "name": "Bash"}]}}, 5.0)
    assert claude["label"] == "正在执行" and claude["model"] == "claude"
    activity.parse_claude(
        claude, {"type": "assistant",
                 "message": {"content": [{"type": "thinking"},
                                         {"type": "text", "text": "结果如下"}]}},
        6.0)
    assert claude["state"] == "responding"
    activity.parse_claude(
        claude, {"type": "system", "subtype": "turn_duration"}, 7.0)
    assert claude["state"] == "completed"

    home = Path(tempfile.mkdtemp())
    session = home / ".codex/sessions/2026/11/17/rollout.jsonl"
    session.parent.mkdir(parents=True)
    session.write_text(
        '{"type":"session_meta","payload":{"id":"s1"}}\n'
        '{"type":"event_msg","payload":{"type":"user_message"}}\n',
        encoding="utf-8")
    live = activity.Activity(home=home)
    assert live.scan()["state"] == "thinking"
    assert live.scan()["session"] == "s1"
    with open(session, "a", encoding="utf-8") as handle:
        handle.write('{"type":"event_msg","payload":{"type":"agent_message",'
                     '"message":"hello"}}\n')
    assert live.scan()["detail"] == "hello"
    live._state.update(active=True, state="working", at=time.time() - 1000)
    assert live.result()["state"] == "idle"


def test_online_quota():
    now = 1_800_000_000.0
    windows, plan = quota.parse_codex_online({
        "plan_type": "pro",
        "rate_limit": {
            "primary_window": {"used_percent": 42,
                               "limit_window_seconds": 18000,
                               "reset_at": int(now + 600)},
            "secondary_window": {"used_percent": 10,
                                 "limit_window_seconds": 604800,
                                 "reset_at": int(now + 86400)}}})
    assert plan == "Pro"
    metrics = quota.parse_codex_limits(windows, now=now)
    assert [item["label"] for item in metrics] == ["5 小时", "本周"]
    assert abs(metrics[0]["remaining"] - 0.58) < 0.001

    claude = quota.parse_claude_online({
        "five_hour": {"utilization": 25, "resets_at": "2027-01-15T11:00:00Z"},
        "limits": [
            {"kind": "weekly_all", "percent": 40,
             "resets_at": "2027-01-20T00:00:00Z"},
            {"kind": "weekly_scoped", "group": "weekly",
             "percent": 12, "scope": {"model": {"display_name": "Opus"}}},
            {"kind": "weekly_scoped", "percent": 12,
             "scope": {"model": {"display_name": "Opus"}}}],
    }, now=now)
    assert [item["label"] for item in claude] == ["5 小时", "本周", "Opus 本周"]
    assert abs(claude[0]["used"] - 0.25) < 0.001

    home = Path(tempfile.mkdtemp())
    assert quota.codex_online(home)[3] == "未找到 Codex 登录信息"
    assert quota.claude_online(home)[2] == "未找到 Claude 登录信息"
    (home / ".codex").mkdir()
    (home / ".codex/auth.json").write_text(
        '{"tokens":{"access_token":"secret-token","account_id":"acc-1"}}',
        encoding="utf-8")
    (home / ".claude").mkdir()
    (home / ".claude/.credentials.json").write_text(
        '{"claudeAiOauth":{"accessToken":"claude-token",'
        '"subscriptionType":"Max"}}', encoding="utf-8")
    calls = []

    def fake(url, token, extra=None, timeout=8):
        calls.append((url, token, dict(extra or {})))
        if url == quota.CODEX_USAGE_URL:
            return {"plan_type": "pro", "rate_limit": {
                "primary_window": {"used_percent": 5,
                                   "limit_window_seconds": 18000,
                                   "reset_at": int(time.time() + 600)}}}
        return {"five_hour": {"utilization": 30}}

    original = quota._http_json
    quota._http_json = fake
    try:
        windows, _, plan, error = quota.codex_online(home)
        assert not error and plan == "Pro" and windows
        metrics, plan, error = quota.claude_online(home)
        assert not error and plan == "Max" and metrics
    finally:
        quota._http_json = original
    assert calls[0][1] == "secret-token"
    assert calls[0][2]["ChatGPT-Account-Id"] == "acc-1"
    assert calls[1][1] == "claude-token"
    assert calls[1][2]["anthropic-beta"] == "oauth-2025-04-20"

    import http.server
    import threading
    import urllib.error

    class Redirect(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:1/elsewhere")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", 0), Redirect)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        try:
            quota._http_json(
                f"http://127.0.0.1:{server.server_port}/usage", "secret")
        except urllib.error.HTTPError as exc:
            assert exc.code == 302
        else:
            raise AssertionError("online quota followed a redirect")
    finally:
        server.shutdown()
        server.server_close()


def test_monitor_sources():
    assert sources.read_disk("/") is None or 0 <= sources.read_disk("/") <= 1
    assert sources.read_temperature() is None or sources.read_temperature() > 0


def test_trae_and_workbuddy_online():
    import base64
    import json

    now = 1_800_000_000

    def jwt(exp):
        def part(value):
            raw = json.dumps(value, separators=(",", ":")).encode()
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
        return ".".join(part(item) for item in (
            {"alg": "RS256", "typ": "JWT"}, {"exp": exp}, "sig"))

    home = Path(tempfile.mkdtemp())
    (home / ".trae-cn").mkdir()
    token_path = home / ".trae-cn" / "trae-jwt-token"
    token_path.write_text(jwt(now + 600), encoding="utf-8")
    calls = []

    def fake(url, token=None, extra=None, timeout=12, data=None,
             method=None):
        calls.append((url, token, dict(extra or {}), data))
        if url == quota.TRAE_USAGE_URL:
            return {"code": 0, "user_entitlement_pack_list": [{
                "entitlement_base_info": {
                    "product_type": 1,
                    "quota": {"credits_limit": 100}},
                "usage": {"credits_amount": 40},
                "expire_time": now + 86400}]}
        return {"code": 0, "data": {
            "SubscriptionPackageName": "专业版",
            "Packages": [{"CycleTotalCapacity": 100,
                          "CycleRemainCapacity": 75,
                          "CycleUsedCapacity": 25}]}}

    original = quota._http_json
    original_session = quota.workbuddy_session
    quota._http_json = fake
    try:
        metrics, plan, error = quota.trae_online(home, now)
        assert not error and plan == "Pro", (plan, error)
        assert metrics[0]["text"] == "60/100"
        assert abs(metrics[0]["used"] - 0.4) < 0.001
        assert calls[0][2]["Authorization"] == (
            "Cloud-IDE-JWT " + token_path.read_text(encoding="utf-8"))
        assert calls[0][3] == {"require_usage": True, "req_source": 0}

        token_path.write_text(jwt(now - 1), encoding="utf-8")
        metrics, plan, error = quota.trae_online(home, now)
        assert not metrics and "过期" in error

        metrics, plan = quota.parse_workbuddy_online({
            "code": 0, "data": {
                "SubscriptionPackageName": "专业版",
                "Packages": [{"CycleTotalCapacity": 100,
                              "CycleRemainCapacity": 75,
                              "CycleUsedCapacity": 25}]}}, now)
        assert plan == "专业版" and metrics[0]["text"] == "75/100"
        assert abs(metrics[0]["used"] - 0.25) < 0.001

        metrics, plan = quota.parse_workbuddy_online({
            "code": 0, "data": {
                "SubscriptionPackageName": "专业版",
                "CreditGroups": [
                    {"Kind": "plan_base", "CycleTotalCapacity": 500,
                     "CycleUsedCapacity": 0},
                    {"Kind": "addon", "CycleTotalCapacity": 2300,
                     "CycleUsedCapacity": 1206.29}]}}, now)
        assert [item["text"] for item in metrics] == ["500/500", "1093.71/2300"]
        assert abs(metrics[1]["used"] - 0.5245) < 0.001

        state, url = quota._workbuddy_login_request({
            "code": 0, "data": {
                "state": "abc",
                "authUrl": "https://www.workbuddy.cn/login?state=abc"}})
        assert state == "abc" and url.endswith("state=abc")
        try:
            quota._workbuddy_login_request({
                "code": 0, "data": {
                    "state": "abc",
                    "authUrl": "https://example.com/login?state=abc"}})
        except ValueError:
            pass
        else:
            raise AssertionError("WorkBuddy accepted a foreign login URL")

        quota.workbuddy_session = lambda: {
            "origin": quota.WORKBUDDY_ORIGIN,
            "access_token": "workbuddy-token",
            "refresh_token": "",
            "domain": "www.workbuddy.cn",
            "uid": "user-1"}
        metrics, plan, error = quota.workbuddy_online(now)
        assert not error and plan == "专业版", (plan, error)
        assert metrics[0]["text"] == "75/100"
        assert calls[-1][2]["X-User-Id"] == "user-1"
    finally:
        quota._http_json = original
        quota.workbuddy_session = original_session


def test_copilot_quota():
    import json

    now = 1_800_000_000
    home = Path(tempfile.mkdtemp())
    folder = home / ".config" / "github-copilot"
    folder.mkdir(parents=True)
    (folder / "apps.json").write_text(json.dumps({
        "github.com:octocat": {"user": "octocat", "oauth_token": "gho_x"}}),
        encoding="utf-8")
    calls = []

    def fake(url, token=None, extra=None, timeout=12, data=None,
             method=None):
        calls.append((url, token, dict(extra or {})))
        return {"copilot_plan": "free",
                "access_type_sku": "free_limited_copilot",
                "quota_reset_date_utc": "2026-12-01T00:00:00Z",
                "quota_snapshots": {
                    "chat": {"entitlement": 200, "quota_remaining": 150},
                    "completions": {"entitlement": "2000",
                                    "quota_remaining": "2000"},
                    "premium_interactions": {"unlimited": True,
                                             "has_quota": False}}}

    original = quota._http_json
    original_session = quota.copilot_session
    quota.copilot_session = lambda: None
    quota._http_json = fake
    try:
        metrics, plan, error = quota.copilot_online(home, now)
        assert not error and plan == "Free", (plan, error)
        assert [item["label"] for item in metrics] == [
            "Chat 请求", "补全", "高级请求"]
        assert metrics[0]["text"] == "150/200"
        assert abs(metrics[0]["used"] - 0.25) < 0.001
        assert metrics[1]["text"] == "2000/2000"
        assert metrics[2]["used"] == 1.0
        assert calls[0][0] == quota.COPILOT_USER_URL
        assert calls[0][2]["Authorization"] == "token gho_x"
        assert calls[0][2]["Copilot-Integration-Id"] == "vscode-chat"
    finally:
        quota._http_json = original
        quota.copilot_session = original_session
    import types

    original_run, original_which = quota.subprocess.run, quota.shutil.which
    quota.shutil.which = lambda name: None
    try:
        metrics, plan, error = quota.copilot_online(
            Path(tempfile.mkdtemp()), now)
    finally:
        quota.shutil.which = original_which
    assert not metrics and "Copilot" in error

    quota.subprocess.run = lambda *a, **k: types.SimpleNamespace(
        returncode=0, stdout="gho_gh\n")
    quota.shutil.which = lambda name: "/usr/bin/" + name
    try:
        token, login = quota.copilot_token(Path(tempfile.mkdtemp()))
        assert token == "gho_gh", token
    finally:
        quota.subprocess.run, quota.shutil.which = original_run, original_which


def test_trae_session():
    import json
    import urllib.error

    now = 1_800_000_000
    session = quota.parse_trae_callback({
        "userJwt": [json.dumps({
            "Token": "jwt-token", "RefreshToken": "refresh-1",
            "TokenExpireAt": int((now + 3600) * 1000)})],
        "userInfo": [json.dumps({"UserID": 42, "ScreenName": "tester"})],
    })
    assert session["access_token"] == "jwt-token"
    assert session["refresh_token"] == "refresh-1"
    assert session["uid"] == "42" and session["name"] == "tester"
    assert abs(session["expires"] - (now + 3600)) < 1
    url = quota.trae_login_url(
        "dev", "machine", "http://127.0.0.1:1/authorize")
    assert "client_id=ono9krqynydwx5" in url
    assert "auth_callback_url=" in url

    calls = []

    def fake(url, token=None, extra=None, timeout=12, data=None,
             method=None):
        calls.append(url)
        if "ExchangeToken" in url:
            return {"Result": {"Token": "new-jwt", "RefreshToken": "refresh-2",
                               "TokenExpireAt": int((now + 7200) * 1000)}}
        if token == "old-jwt":
            raise urllib.error.HTTPError(url, 401, "", {}, None)
        return {"code": 0, "user_entitlement_pack_list": [{
            "entitlement_base_info": {
                "product_type": 1, "quota": {"credits_limit": 100}},
            "usage": {"credits_amount": 40},
            "expire_time": now + 86400}]}

    original_http = quota._http_json
    original_session = quota.trae_session
    original_save = quota._save_private_json
    saved = []
    quota._http_json = fake
    quota._save_private_json = lambda path, data: saved.append(dict(data))
    try:
        quota.trae_session = lambda: {
            "origin": quota.TRAE_ORIGIN, "access_token": "old-jwt",
            "refresh_token": "refresh-1", "expires": now - 1}
        metrics, plan, error = quota.trae_online(now=now)
        assert not error and metrics[0]["text"] == "60/100", (metrics, error)
        assert calls[0].endswith("/cloudide/api/v3/trae/oauth/ExchangeToken")
        assert saved[-1]["refresh_token"] == "refresh-2"
    finally:
        quota._http_json = original_http
        quota.trae_session = original_session
        quota._save_private_json = original_save


def test_copilot_device_login():
    original = quota._post_form

    def fake(url, form, timeout=15):
        if url == quota.COPILOT_DEVICE_URL:
            return {"device_code": "dc", "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 1, "expires_in": 900}
        return {"access_token": "gho_device"}

    try:
        quota._post_form = fake
        start = quota.copilot_device_start()
        assert start["user_code"] == "ABCD-1234"
        assert quota.copilot_device_poll("dc", 1) == ("gho_device", 1)
        quota._post_form = lambda *a, **k: {"error": "authorization_pending"}
        assert quota.copilot_device_poll("dc", 5) == (None, 5)
        quota._post_form = lambda *a, **k: {"error": "slow_down"}
        assert quota.copilot_device_poll("dc", 5) == (None, 10)
    finally:
        quota._post_form = original

    quota._save_copilot_session("gho_session")
    token, login = quota.copilot_token(Path(tempfile.mkdtemp()))
    assert token == "gho_session"


def _autostart_home():
    home = Path(tempfile.mkdtemp())
    os.environ["XDG_CONFIG_HOME"] = str(home / "config")
    return home


def test_autostart_entry_is_cwd_independent():
    # UKUI autostart launches from $HOME, where `-m island` cannot import the
    # source tree. `--version` returns before QApplication, so this proves the
    # entry resolves without opening a second surface on the running desktop.
    proc = subprocess.run(autostart.command().split() + ["--version"],
                          cwd=str(Path(tempfile.mkdtemp())),
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          timeout=60)
    out = proc.stdout.decode()
    assert proc.returncode == 0, out
    assert "No module named" not in out
    assert __version__ in out


def test_autostart_ensure_repairs_dead_entries_only():
    original = os.environ.get("XDG_CONFIG_HOME")
    try:
        home = _autostart_home()
        path = autostart._entry_path()
        dead = ["%s -m island" % sys.executable,                    # old release
                "/nonexistent/ukui-dynamic-island",                 # uninstalled deb
                "%s /moved-away/run.py" % sys.executable,           # moved checkout
                "%s -m island --self-test" % sys.executable]
        for exec_line in dead:
            path.unlink(missing_ok=True)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("[Desktop Entry]\nExec=%s\n" % exec_line,
                            encoding="utf-8")
            assert autostart.ensure() is True, exec_line
            assert ("Exec=%s" % autostart.command()) in path.read_text(encoding="utf-8")
            assert path.stat().st_mode & 0o777 == 0o644
            assert autostart.ensure() is False                      # idempotent

        # Opt-in stays: no entry, or an empty one, is never created here.
        for text in ("", "\n"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            assert autostart.ensure() is False
            assert path.read_text(encoding="utf-8") == text
        path.unlink()
        assert autostart.ensure() is False and not path.exists()

        # A live entry for another build is left alone, not stolen.
        other = home / "config" / "other-island"
        other.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        other.chmod(0o755)
        path.write_text("[Desktop Entry]\nExec=%s\n" % other, encoding="utf-8")
        assert autostart.ensure() is False
        assert path.read_text(encoding="utf-8") == "[Desktop Entry]\nExec=%s\n" % other

        assert autostart._launchable(autostart.command()) is True
        assert autostart._launchable("%s -m island" % sys.executable) is False
    finally:
        if original is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = original


if __name__ == "__main__":
    test_themes()
    test_geometry()
    test_config_roundtrip()
    test_spring_and_morph()
    test_sources_and_weather()
    test_music_metadata()
    test_productivity_store()
    test_logging()
    test_todo_repeat_and_clip_pin()
    test_mail_parsing()
    test_meeting_invite()
    test_meeting_notice()
    test_todo_remind_on()
    test_todo_meeting_details()
    test_mail_mark_seen_reply()
    test_mail_operation_queue()
    test_calendar_parsing()
    test_stock_parsing()
    test_stock_session()
    test_quota_parsing()
    test_codex_quota_snapshot_and_claude_history()
    test_workbuddy_usage()
    test_activity_parsing()
    test_online_quota()
    test_trae_and_workbuddy_online()
    test_copilot_quota()
    test_trae_session()
    test_copilot_device_login()
    test_monitor_sources()
    test_autostart_entry_is_cwd_independent()
    test_autostart_ensure_repairs_dead_entries_only()
    print("OK: themes, geometry, config, motion, sources, weather, music, "
          "productivity, mail, calendar, quota, activity, online quota")
