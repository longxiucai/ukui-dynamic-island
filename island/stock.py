"""Realtime quote and intraday line for one configured security."""
import json
import os
import re
import time
import urllib.request
from datetime import datetime, timedelta

from PySide2.QtCore import QThread, Signal


QUOTE_URL = os.environ.get("UKUI_ISLAND_STOCK_QUOTE_URL",
                           "https://qt.gtimg.cn/q={}")
MINUTE_URL = os.environ.get("UKUI_ISLAND_STOCK_MINUTE_URL",
                            "https://web.ifzq.gtimg.cn/appstock/app/minute/query?code={}")
CODE = re.compile(r"^(sh|sz|bj)\d{6}$|^hk\d{5}$|^us[A-Za-z][A-Za-z0-9.\-]*$")
STAMP_RE = re.compile(r"^(\d{4})\D?(\d{2})\D?(\d{2})")
# 连续交易时段（当地分钟）：沪深 09:30-15:00、港股 09:30-16:00、美股 09:30-16:00。
# 区间含午休，因为午休时涨跌仍是当天有效行情；节假日靠行情日期判断。
SESSIONS = {"cn": (570, 900), "hk": (570, 960), "us": (570, 960)}
# shortcut: 沪深港直接用本机时间（Kylin 桌面在 CST），只有美股换算美东时间；
# 若要在非 CST 机器上看沪深港，改成全部按 market 偏移换算。
US_UTC_OFFSET = -5.0


def market_of(code):
    """Session table key for a Tencent symbol, or "" when unknown."""
    text = str(code or "").lower()
    if text.startswith(("sh", "sz", "bj")):
        return "cn"
    if text.startswith("hk"):
        return "hk"
    if text.startswith("us"):
        return "us"
    return ""


def stamp_date(raw):
    """Exchange stamp -> YYYYMMDD, or "" when unreadable."""
    match = STAMP_RE.match(str(raw or "").strip())
    return "".join(match.groups()) if match else ""


def _nth_weekday(year, month, weekday, n):
    day = datetime(year, month, 1)
    day += timedelta(days=(weekday - day.weekday()) % 7, weeks=n - 1)
    return day


def _us_summer(date):
    """US DST: 2nd Sunday of March 02:00 to 1st Sunday of November 02:00."""
    day = date.replace(hour=2, minute=0, second=0, microsecond=0)
    return (_nth_weekday(day.year, 3, 6, 2) <= day
            < _nth_weekday(day.year, 11, 6, 1))


def local_now(code, now=None):
    """Wall-clock time on the exchange, or the machine clock when unknown."""
    now = now or datetime.now()
    if market_of(code) != "us":
        return now
    standard = now + timedelta(hours=US_UTC_OFFSET - _local_utc_offset(now))
    return standard + timedelta(hours=1.0 if _us_summer(standard) else 0.0)


def _local_utc_offset(now):
    """Machine UTC offset in hours; the Kylin desktop has no DST."""
    return now.astimezone().utcoffset().total_seconds() / 3600.0


def in_session(code, now=None, grace_minutes=15):
    """True during a trading day's session, plus grace minutes after close."""
    market = market_of(code)
    if market not in SESSIONS:
        return True
    local = local_now(code, now)
    if local.weekday() >= 5:
        return False
    start, end = SESSIONS[market]
    minutes = local.hour * 60 + local.minute
    return start <= minutes < end + max(0, int(grace_minutes))


def quote_fresh(code, date, now=None):
    """False when the quote stamp is not today for that market."""
    market = market_of(code)
    stamp = stamp_date(date)
    if not stamp or market not in SESSIONS:
        return True
    return stamp == local_now(code, now).strftime("%Y%m%d")


def chip_visible(code, date="", now=None, grace_minutes=15, enabled=True):
    """Whether the collapsed pill may show today's change."""
    if not enabled:
        return True
    return (in_session(code, now, grace_minutes)
            and quote_fresh(code, date, now))


def normalize_code(value):
    """Canonical Tencent symbol, or "" when the input cannot be queried."""
    text = str(value or "").strip()
    low = text.lower()
    if re.fullmatch(r"(sh|sz|bj)\d{6}", low):
        return low
    if re.fullmatch(r"hk\d{5}", low):
        return low
    if re.fullmatch(r"us[a-z][a-z0-9.\-]*", low):
        return "us" + text[2:].upper()
    if re.fullmatch(r"\d{6}", text):
        prefix = ("sh" if text[0] in "69" else
                  "bj" if text[0] in "48" else "sz")
        return prefix + text
    if re.fullmatch(r"\d{5}", text):
        return "hk" + text
    if re.fullmatch(r"[a-z][a-z0-9.\-]{0,9}", low):
        return "us" + text.upper()
    return ""


def _get(url, encoding="utf-8"):
    request = urllib.request.Request(
        url, headers={"User-Agent": "ukui-dynamic-island/0.6"})
    with urllib.request.urlopen(request, timeout=6) as response:
        return response.read().decode(encoding, errors="replace")


def _number(value):
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_quote(text):
    """Tencent qt payload -> quote dict. Raises ValueError on a bad payload."""
    start, end = text.find('"'), text.rfind('"')
    if start < 0 or end <= start:
        raise ValueError("行情返回格式不正确")
    fields = text[start + 1:end].split("~")
    if len(fields) < 35:
        raise ValueError("行情字段不完整")
    price = _number(fields[3])
    prev_close = _number(fields[4])
    if price is None or prev_close is None:
        raise ValueError("行情价格缺失")
    raw_stamp = fields[30].strip()
    if " " in raw_stamp:
        stamp = raw_stamp.rsplit(" ", 1)[-1][:5]
    else:
        stamp = raw_stamp[8:12] if len(raw_stamp) >= 12 else ""
    return {
        "status": "ok",
        "name": fields[1] or fields[2],
        "price": price,
        "prev_close": prev_close,
        "change": _number(fields[31]) or 0.0,
        "change_pct": _number(fields[32]) or 0.0,
        "high": _number(fields[33]),
        "low": _number(fields[34]),
        "date": stamp_date(raw_stamp),
        "at": (stamp if ":" in stamp else
               f"{stamp[:2]}:{stamp[2:]}" if len(stamp) == 4 else ""),
    }


def parse_minutes(payload, code):
    """Tencent minute payload -> [[HHMM, price], ...]."""
    data = ((payload.get("data") or {}).get(code) or {}).get("data") or {}
    points = []
    for row in data.get("data") or []:
        fields = str(row).split()
        if len(fields) < 2:
            continue
        price = _number(fields[1])
        if price is None or price <= 0:
            continue
        points.append([fields[0], price])
    return points


def fetch(code):
    code = normalize_code(code)
    if not CODE.fullmatch(code or ""):
        raise ValueError("代码格式不正确")
    quote = parse_quote(_get(QUOTE_URL.format(code), "gbk"))
    quote["code"] = code
    try:
        quote["points"] = parse_minutes(
            json.loads(_get(MINUTE_URL.format(code))), code)
    except Exception:
        quote["points"] = []
    return quote


class Stock(QThread):
    updated = Signal(dict)

    def __init__(self, cfg, interval=60, parent=None):
        super().__init__(parent)
        self.code = normalize_code(cfg.get("stock_code"))
        self.interval = interval
        self._refreshing = False

    def refresh(self):
        self._refreshing = True

    def run(self):
        while not self.isInterruptionRequested():
            try:
                result = fetch(self.code)
            except Exception as exc:
                result = {"status": "error", "code": self.code,
                          "error": str(exc), "points": []}
            if self.isInterruptionRequested():
                break
            self.updated.emit(result)
            waited = 0.0
            while waited < self.interval and not self.isInterruptionRequested():
                if self._refreshing:
                    self._refreshing = False
                    break
                self.msleep(250)
                waited += 0.25
