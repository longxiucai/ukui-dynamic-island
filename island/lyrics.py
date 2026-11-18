"""NetEase lyric lookup: match by title + duration, return timed LRC lines."""
import json
import re
import time
import urllib.parse
import urllib.request


SEARCH_URL = "https://music.163.com/api/search/get?s={}&type=1&limit=10"
LYRIC_URL = ("https://music.163.com/api/song/lyric?os=pc&id={}"
             "&lv=-1&kv=-1&tv=-1")
HEADERS = {"User-Agent": "Mozilla/5.0", "Referer": "https://music.163.com/"}
TIME_RE = re.compile(r"\[(\d{1,2}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
WORD_RE = re.compile(r"<\d{1,3}:\d{1,2}(?:[.:]\d{1,3})?>")
OFFSET_RE = re.compile(r"\[offset:\s*([+-]?\d+)\s*\]", re.IGNORECASE)
META_RE = re.compile(r"^(作词|作曲|编曲|制作|监制|混音|母带|录音|吉他|贝斯"
                     r"|和声|出品|发行|词|曲|演唱|原唱|OP|SP)\s*[:：]",
                     re.IGNORECASE)
INSTRUMENTAL_RE = re.compile(r"纯音乐|此歌曲为没有填词的")

_CACHE = {}
_RETRY = {}


def parse_lrc(text):
    text = text or ""
    offset = OFFSET_RE.search(text)
    offset = int(offset.group(1)) / 1000.0 if offset else 0.0
    lines = []
    for raw in text.splitlines():
        stamps = TIME_RE.findall(raw)
        content = WORD_RE.sub("", TIME_RE.sub("", raw)).strip()
        if not stamps or not content or META_RE.match(content):
            continue
        for minute, second, frac in stamps:
            ms = int((frac or "0").ljust(3, "0")[:3])
            lines.append((max(0.0, int(minute) * 60 + int(second)
                              + ms / 1000.0 + offset), content))
    lines.sort()
    return lines


def current_line(lines, position):
    text = ""
    for start, content in lines or ():
        if start > position + 0.15:
            break
        text = content
    return text


def current(lines, position):
    """The active lyric line plus its time range, for wrapping/paging."""
    index = -1
    for i, (start, _content) in enumerate(lines or ()):
        if start > position + 0.15:
            break
        index = i
    if index < 0:
        return None
    start, text = lines[index]
    end = lines[index + 1][0] if index + 1 < len(lines) else None
    return {"index": index, "text": text, "start": start, "end": end}


def _norm(text):
    return re.sub(r"[\s·]+", "", str(text or "")).lower()


def candidates(songs, title, length, tolerance=2.0):
    target = _norm(title)
    picked = []
    for song in songs or ():
        if _norm(song.get("name")) != target:
            continue
        diff = abs(float(song.get("duration") or 0) / 1000.0 - length)
        if diff <= tolerance and song.get("id"):
            picked.append((diff, song["id"]))
    picked.sort()
    return [song_id for _, song_id in picked]


def _get_json(url, timeout=4):
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read(2_000_000).decode("utf-8"))


def _fetch(title, artist, length):
    query = urllib.parse.quote(f"{title} {artist}".strip())
    songs = (_get_json(SEARCH_URL.format(query)).get("result") or {}).get("songs")
    for song_id in candidates(songs, title, length)[:3]:
        reply = _get_json(LYRIC_URL.format(song_id))
        if reply.get("pureMusic"):
            return []
        lines = parse_lrc((reply.get("lrc") or {}).get("lyric"))
        if lines and all(INSTRUMENTAL_RE.search(content) or META_RE.match(content)
                         for _, content in lines):
            return []
        if lines:
            return lines
    return []


def lookup(title, artist, length):
    """Timed lines for the track, empty when unmatched. Cached per track."""
    if not title or not length:
        return []
    key = (str(title).strip().lower(), str(artist).strip().lower(),
           int(round(float(length))))
    if key in _CACHE:
        return _CACHE[key]
    now = time.monotonic()
    if _RETRY.get(key, 0) > now:
        return []
    try:
        lines = _fetch(title, artist, length)
    except Exception:
        _RETRY[key] = now + 300
        return []
    _CACHE[key] = lines
    return lines
