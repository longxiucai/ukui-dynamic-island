"""MPRIS now-playing over jeepney: polling, controls and cover cache."""
import hashlib
import os
import queue
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from jeepney import DBusAddress, Properties, new_method_call
from jeepney.io.blocking import open_dbus_connection
from PySide2.QtCore import QThread, Signal

from island import lyrics


PLAYER_PATH = "/org/mpris/MediaPlayer2"
PLAYER_IFACE = "org.mpris.MediaPlayer2.Player"


def unwrap(value):
    if isinstance(value, tuple) and len(value) == 2 and isinstance(value[0], str):
        return value[1]
    return value


def parse_metadata(raw):
    raw = unwrap(raw) or {}
    title = clean_title(str(unwrap(raw.get("xesam:title")) or ""))
    artist = unwrap(raw.get("xesam:artist")) or []
    if isinstance(artist, str):
        artist = [artist]
    return {
        "title": title,
        "artist": " / ".join(str(item) for item in artist if item),
        "album": str(unwrap(raw.get("xesam:album")) or ""),
        "length": (unwrap(raw.get("mpris:length")) or 0) / 1_000_000,
        "art_url": str(unwrap(raw.get("mpris:artUrl")) or ""),
        "track_id": str(unwrap(raw.get("mpris:trackid")) or ""),
    }


def parse_state(properties):
    props = {key: unwrap(value) for key, value in (properties or {}).items()}
    state = parse_metadata(props.get("Metadata"))
    state.update({
        "status": str(props.get("PlaybackStatus") or "Stopped"),
        "position": (props.get("Position") or 0) / 1_000_000,
        "can_next": bool(props.get("CanGoNext", False)),
        "can_prev": bool(props.get("CanGoPrevious", False)),
        "can_seek": bool(props.get("CanSeek", False)),
    })
    return state


def clean_title(text):
    text = text.strip().lstrip("▶⏸").strip()
    for separator in (" - ", " – ", " -", " –"):
        if separator in text:
            head, tail = text.rsplit(separator, 1)
            if any(word in tail for word in ("Chrome", "Chromium", "Firefox", "Edge",
                                             "Browser", "浏览器")):
                text = head
            break
    return text


def player_label(name):
    low = name.lower()
    for key, label in (("chromium", "Chrome/Chromium"), ("chrome", "Chrome"),
                       ("firefox", "Firefox"), ("vlc", "VLC"),
                       ("spotify", "Spotify"), ("rhythmbox", "Rhythmbox"),
                       ("mpv", "mpv")):
        if key in low:
            return label
    return "MPRIS"


def format_time(seconds):
    seconds = max(0, int(seconds or 0))
    return f"{seconds // 60}:{seconds % 60:02d}"


def parse_window_title(title):
    title = title.strip()
    if title.startswith("▶"):
        status = "Playing"
    elif title.startswith("⏸"):
        status = "Paused"
    else:
        return None
    name = clean_title(title)
    if not name:
        return None
    return {"title": name, "artist": "", "album": "", "length": 0,
            "position": 0, "art_url": "", "art_path": "", "status": status,
            "can_next": False, "can_prev": False, "player": "", "app": "浏览器",
            "source": "window", "can_seek": False}


def window_title_state():
    """Browser fallback: Chromium forks here do not expose MPRIS."""
    try:
        out = subprocess.run(["xdotool", "search", "--name", "^[▶⏸]",
                              "getwindowname", "%@"],
                             capture_output=True, text=True, timeout=1).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for title in out.splitlines():
        state = parse_window_title(title)
        if state:
            return state
    return None


def _cover_dir():
    path = Path.home() / ".cache" / "ukui-island" / "covers"
    path.mkdir(parents=True, exist_ok=True)
    return path


def art_path(url):
    if not url:
        return ""
    if url.startswith("file://"):
        path = urllib.parse.unquote(url[7:])
        return path if os.path.exists(path) else ""
    name = hashlib.sha1(url.encode("utf-8")).hexdigest() + Path(
        urllib.parse.urlparse(url).path).suffix[:5]
    path = _cover_dir() / name
    if path.exists():
        return str(path)
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "ukui-island/0.1"})
        with urllib.request.urlopen(request, timeout=4) as response:
            data = response.read(5_000_000)
        path.write_bytes(data)
    except (OSError, ValueError):
        return ""
    return str(path)


class Music(QThread):
    updated = Signal(object)

    def __init__(self, interval=1.0, parent=None):
        super().__init__(parent)
        self.interval = interval
        self._commands = queue.Queue()
        self._active = ""
        self._last = None
        self._window_state = None
        self._window_at = 0.0

    def _window(self):
        if time.monotonic() - self._window_at >= 2.0:
            self._window_state = window_title_state()
            self._window_at = time.monotonic()
        return self._window_state

    def command(self, name):
        self._commands.put(name)

    def seek(self, seconds):
        self._commands.put(("seek", float(seconds)))

    def _players(self, conn):
        address = DBusAddress("/org/freedesktop/DBus",
                              bus_name="org.freedesktop.DBus",
                              interface="org.freedesktop.DBus")
        reply = conn.send_and_get_reply(new_method_call(address, "ListNames"), timeout=1)
        return [name for name in reply.body[0]
                if name.startswith("org.mpris.MediaPlayer2.")]

    def _state(self, conn, name):
        address = DBusAddress(PLAYER_PATH, bus_name=name, interface=PLAYER_IFACE)
        reply = conn.send_and_get_reply(Properties(address).get_all(), timeout=1)
        state = parse_state(reply.body[0])
        state["player"] = name
        state["app"] = player_label(name)
        state["art_path"] = art_path(state["art_url"])
        state["lyric"] = lyrics.lookup(state["title"], state["artist"],
                                       state["length"])
        return state

    def _read(self, conn):
        names = self._players(conn)
        states = []
        for name in names:
            try:
                states.append(self._state(conn, name))
            except Exception:
                continue
        if not states:
            return self._window()
        playing = [item for item in states if item["status"] == "Playing"]
        window = self._window() if not playing else None
        if window:
            self._active = ""
            return window
        active = playing[0] if playing else states[0]
        self._active = active["player"]
        return active

    def _run_command(self, player, method):
        if not player:
            return
        address = DBusAddress(PLAYER_PATH, bus_name=player, interface=PLAYER_IFACE)
        with open_dbus_connection(bus="SESSION") as conn:
            conn.send_and_get_reply(new_method_call(address, method), timeout=1)

    def _seek(self, player, seconds):
        if not player:
            return
        state = self._last or {}
        target = max(0.0, float(seconds))
        micros = int(round(target * 1_000_000))
        address = DBusAddress(PLAYER_PATH, bus_name=player, interface=PLAYER_IFACE)
        track_id = state.get("track_id") or ""
        with open_dbus_connection(bus="SESSION") as conn:
            if track_id.startswith("/"):
                try:
                    conn.send_and_get_reply(new_method_call(
                        address, "SetPosition", "ox", (track_id, micros)), timeout=1)
                    return
                except Exception:
                    pass
            current = float(state.get("position") or 0)
            offset = int(round((target - current) * 1_000_000))
            if offset:
                conn.send_and_get_reply(new_method_call(
                    address, "Seek", "x", (offset,)), timeout=1)

    def run(self):
        conn = None
        while not self.isInterruptionRequested():
            failed = False
            try:
                if conn is None:
                    conn = open_dbus_connection(bus="SESSION")
                while not self._commands.empty():
                    try:
                        item = self._commands.get_nowait()
                        if isinstance(item, tuple) and item[0] == "seek":
                            self._seek(self._active, item[1])
                        else:
                            self._run_command(self._active, item)
                    except Exception:
                        pass
                state = self._read(conn)
            except Exception:
                failed = True
                state = self._last
                try:
                    if conn is not None:
                        conn.close()
                except Exception:
                    pass
                conn = None
            if not failed and state != self._last:
                self._last = state
                self.updated.emit(state)
            for _ in range(10):
                if self.isInterruptionRequested():
                    return
                time.sleep(self.interval / 10.0)
        if conn is not None:
            conn.close()
