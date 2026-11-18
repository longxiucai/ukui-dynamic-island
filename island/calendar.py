"""Minimal ICS parsing plus a CalDAV/ICS reader over urllib."""
import base64
import os
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from PySide2.QtCore import QThread, Signal


def unfold(text):
    lines = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line)
    return lines


def parse_dt(value):
    value = (value or "").strip()
    if not value:
        return None, True
    all_day = "T" not in value
    value = value.split(":", 1)[-1] if "TZID=" in value and ":" in value else value
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S", "%Y%m%d"):
        try:
            parsed = datetime.strptime(value[:16], fmt)
            if fmt.endswith("Z"):
                parsed = (parsed.replace(tzinfo=timezone.utc)
                          .astimezone().replace(tzinfo=None))
            return parsed, all_day
        except ValueError:
            continue
    return None, all_day


def parse_ics(text):
    events = []
    current = None
    for line in unfold(text or ""):
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                start, all_day = parse_dt(current.get("DTSTART", ""))
                end, _ = parse_dt(current.get("DTEND", ""))
                if start:
                    events.append({
                        "start": start,
                        "end": end or (start + (timedelta(days=1) if all_day
                                                else timedelta(hours=1))),
                        "all_day": all_day,
                        "summary": current.get("SUMMARY", "(无标题)"),
                        "place": current.get("LOCATION", ""),
                    })
            current = None
            continue
        if current is None or ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.split(";", 1)[0].upper()
        if key in ("DTSTART", "DTEND", "SUMMARY", "LOCATION"):
            current[key] = value.replace("\\,", ",").replace("\\n", " ").strip()
    return events


def upcoming(events, now=None, days=7, limit=8):
    now = now or datetime.now()
    until = now + timedelta(days=days)
    rows = [event for event in events
            if event["end"] >= now - timedelta(hours=1) and event["start"] <= until]
    rows.sort(key=lambda item: item["start"])
    return rows[:limit]


def event_text(event):
    start = event["start"]
    if event["all_day"]:
        return start.strftime("%m-%d") + " 全天"
    today = datetime.now().date()
    day = "今天" if start.date() == today else start.strftime("%m-%d")
    return f"{day} {start.strftime('%H:%M')}"


def _local_source(url):
    if url.startswith("file://"):
        return urllib.parse.unquote(url[7:])
    return url if os.path.isfile(url) else ""


def _read_url(url, user="", password="", method="GET", data=None, headers=None,
              timeout=10):
    request = urllib.request.Request(url, data=data, method=method)
    request.add_header("User-Agent", "ukui-dynamic-island/0.5")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    if user:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        request.add_header("Authorization", "Basic " + token)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _caldav_report(url, user, password):
    now = datetime.utcnow()
    body = f"""<?xml version="1.0" encoding="utf-8" ?>
<C:calendar-query xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">
  <D:prop><C:calendar-data/></D:prop>
  <C:filter><C:comp-filter name="VCALENDAR"><C:comp-filter name="VEVENT">
    <C:time-range start="{now:%Y%m%dT%H%M%SZ}"
                  end="{(now + timedelta(days=7)):%Y%m%dT%H%M%SZ}"/>
  </C:comp-filter></C:comp-filter></C:filter>
</C:calendar-query>""".encode()
    raw = _read_url(url, user, password, "REPORT", body,
                    {"Depth": "1", "Content-Type": "application/xml; charset=utf-8"})
    root = ET.fromstring(raw)
    chunks = []
    for node in root.iter():
        if node.tag.endswith("calendar-data") and node.text:
            chunks.append(node.text)
    return parse_ics("\n".join(chunks))


def load_calendar(url, user="", password=""):
    if not url:
        return {"status": "unconfigured", "error": "未配置日历", "items": []}
    try:
        local = _local_source(url)
        if local:
            with open(local, encoding="utf-8", errors="replace") as handle:
                events = parse_ics(handle.read())
        elif user:
            try:
                events = _caldav_report(url, user, password)
            except Exception:
                events = parse_ics(_read_url(url, user, password).decode(
                    "utf-8", "replace"))
        else:
            events = parse_ics(_read_url(url).decode("utf-8", "replace"))
        return {"status": "ok", "error": "", "items": upcoming(events)}
    except Exception as exc:
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}",
                "items": []}


class Calendar(QThread):
    updated = Signal(dict)

    def __init__(self, cfg, interval=900, parent=None):
        super().__init__(parent)
        self.cfg = dict(cfg)
        self.interval = interval
        self._refreshing = False

    def refresh(self):
        self._refreshing = True

    def run(self):
        while not self.isInterruptionRequested():
            result = load_calendar(
                self.cfg.get("calendar_url", ""),
                self.cfg.get("calendar_user", ""),
                self.cfg.get("calendar_password", ""))
            if self.isInterruptionRequested():
                break
            result["at"] = time.strftime("%H:%M")
            self.updated.emit(result)
            self._refreshing = False
            waited = 0.0
            while waited < self.interval and not self.isInterruptionRequested():
                if self._refreshing:
                    self._refreshing = False
                    break
                self.msleep(250)
                waited += 0.25
