"""Turn a copied meeting invite into a suggested todo (stdlib only)."""
import re
from datetime import datetime


FULLWIDTH = str.maketrans("：０１２３４５６７８９", ":0123456789")
ESCAPE_RE = re.compile(r"\\(?=[^\w])")
ENTITY_RE = re.compile(r"&#(?:x([0-9a-fA-F]{1,6})|(\d{1,7}));")
TITLE_RE = re.compile(r"会议[ \t]*(?:主题|议题)[ \t]*[:：][ \t]*([^\n]{1,80})")
WHEN_RE = re.compile(r"会议[ \t]*(?:时间|日期)[ \t]*[:：][^\n]{0,120}")
DATE_RE = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})[^\d\n]{0,4}"
                     r"(\d{1,2}):(\d{2})")
CJK_DATE_RE = re.compile(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})日")
CLOCK_RE = re.compile(r"(上午|中午|下午|晚上)?\s*(\d{1,2}):(\d{2})(?!\d)")
NOTICE_RE = re.compile(r"(?:通知|定于|将于|大会|开会)")
HEAD_RE = re.compile(r"(?:通知|大会|例会|会议)$")
BODY_RE = re.compile(r"[:。]")
HEAD_LINES = 4
HEAD_CHARS = 40
PLACE_LABEL_RE = re.compile(r"^\s*(?:[〇一二三四五六七八九十0-9]+\s*[、.．]\s*)?"
                            r"地\s*点\s*$")
SECTION_RE = re.compile(r"^\s*(?:[〇一二三四五六七八九十0-9]+\s*[、.．])")
MENTION_RE = re.compile(r"^(?:@[^\s@]*\s*)+")
PLACE_LINES = 3
PLACE_SKIP = ("会议号", "号码", "链接", "http")
KINDS = ("会议", "大会", "例会", "开会")
CODE_RE = re.compile(r"(?:腾讯会议|飞书会议|钉钉会议|会议号码|会议号)[ \t]*"
                     r"[:：]?[ \t]*([0-9][0-9 \-]{6,}[0-9])")
LINK_RE = re.compile(r"https?://\S+")
PLACE_RE = re.compile(r"(?:会议[ \t]*(?:地点|室)|房间号|会议室|地点)[ \t]*"
                      r"[:：][ \t]*([^\n]{1,60})")
MAX_CHARS = 20_000


def _entity(match):
    """Decode a numeric HTML entity left behind by a rich-text copy."""
    hexa = match.group(1)
    code = int(hexa, 16) if hexa else int(match.group(2))
    return chr(code) if 32 <= code < 0x10000 else " "


def _clock(match):
    """Return (hour, minute) honouring an 上午/下午 prefix, else None."""
    hour, minute = int(match.group(2)), int(match.group(3))
    if match.group(1) in ("下午", "晚上") and hour < 12:
        hour += 12
    elif match.group(1) == "上午" and hour == 12:
        hour = 0
    return (hour, minute) if hour < 24 and minute < 60 else None


def _plain(value):
    """Undo what a rich-text copy leaves: full width, entities, escapes."""
    value = value.translate(FULLWIDTH)
    value = ENTITY_RE.sub(_entity, value)
    return ESCAPE_RE.sub("", value)


def _notice(value):
    """Read a free-text 「关于召开…的通知」: (title, date, clock) or None."""
    if not NOTICE_RE.search(value):
        return None
    stamp = CJK_DATE_RE.search(value)
    clock = CLOCK_RE.search(value)
    if not stamp or not clock:
        return None
    time_of_day = _clock(clock)
    if not time_of_day:
        return None
    lines = [MENTION_RE.sub("", " ".join(row.split())).strip()
             for row in value.splitlines()][:HEAD_LINES]
    plain = ""
    for row in lines:
        if HEAD_RE.search(row) and not BODY_RE.search(row):
            return (row, tuple(map(int, stamp.groups())), time_of_day)
        if (not plain and row and not BODY_RE.search(row)
                and len(row) <= HEAD_CHARS):
            plain = row
    if plain:
        return (plain, tuple(map(int, stamp.groups())), time_of_day)
    return None


def _place_block(value):
    """Join the lines under a standalone 「地点」 label into one place."""
    lines = value.splitlines()
    for number, line in enumerate(lines):
        if not PLACE_LABEL_RE.match(line):
            continue
        found = []
        for row in lines[number + 1:]:
            text = " ".join(row.split())
            if (not text or SECTION_RE.match(text)
                    or any(word in text for word in PLACE_SKIP)):
                break
            found.append(text)
            if len(found) >= PLACE_LINES:
                break
        return "；".join(found)
    return ""


def parse_meeting(text):
    """Return {"text", "title", "remind", "past", "code"} for an invite, else None.

    Handles a labelled invite (腾讯/飞书/企微) and a free-text 会议通知 with
    「2026年11月12日 下午16:00」 plus a 地点 block.
    shortcut: 纯英文或日历卡片格式不识别。
    """
    value = _plain(str(text or ""))
    if not value or len(value) > MAX_CHARS:
        return None
    if not any(kind in value for kind in KINDS):
        return None
    now = datetime.now()
    title = TITLE_RE.search(value)
    when = WHEN_RE.search(value)
    place = PLACE_RE.search(value)
    if title and when:
        stamp = DATE_RE.search(when.group(0))
        if stamp:
            date = tuple(map(int, stamp.groups()[:3]))
            clock = (int(stamp.group(4)), int(stamp.group(5)))
        else:
            cjk = CJK_DATE_RE.search(when.group(0))
            span = CLOCK_RE.search(when.group(0))
            clock = _clock(span) if span else None
            if not clock:
                return None
            date = (tuple(map(int, cjk.groups())) if cjk
                    else (now.year, now.month, now.day))
        name = title.group(1).strip()
    else:
        found = _notice(value)
        if not found:
            return None
        name, date, clock = found
    try:
        start = datetime(*date, *clock)
    except ValueError:
        return None
    code = CODE_RE.search(value)
    number = code.group(1).replace(" ", "").replace("-", "") if code else ""
    link = LINK_RE.search(value)
    month, day, hour, minute = date[1], date[2], clock[0], clock[1]
    place_text = place.group(1).strip() if place else _place_block(value)
    label = f"{month:02d}/{day:02d} {hour:02d}:{minute:02d} {name}"
    remind = "" if start <= now else f"{hour:02d}:{minute:02d}"
    return {
        "text": label[:200],
        "title": name[:80],
        "remind": remind,
        "remind_on": start.date().isoformat() if remind else "",
        "past": start <= now,
        "code": number,
        "place": place_text,
        "link": (link.group(0).rstrip("。，,;)）]") if link else "")[:300],
    }
