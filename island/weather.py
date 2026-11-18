"""Current weather from wttr.in, cached on disk and refreshed off the UI thread."""
import json
import os
import threading
import time
import urllib.parse
import urllib.request

from PySide2.QtCore import QThread, Signal

from island import config


CONDITIONS = {
    "Sunny": "晴", "Clear": "晴", "Partly cloudy": "多云", "Cloudy": "阴",
    "Overcast": "阴", "Mist": "薄雾", "Fog": "雾", "Freezing fog": "冻雾",
    "Patchy rain possible": "可能有雨", "Patchy rain nearby": "局部有雨",
    "Light drizzle": "毛毛雨", "Light rain": "小雨", "Moderate rain": "中雨",
    "Heavy rain": "大雨", "Light rain shower": "阵雨",
    "Moderate or heavy rain shower": "强阵雨", "Thundery outbreaks possible": "雷阵雨",
    "Patchy light snow": "小雪", "Light snow": "小雪", "Moderate snow": "中雪",
    "Heavy snow": "大雪", "Blowing snow": "风吹雪", "Smoke": "烟霾", "Haze": "霾",
    "Dust": "浮尘", "Sand": "沙尘",
}


def describe(text):
    text = str(text or "").strip()
    if text in CONDITIONS:
        return CONDITIONS[text]
    low = text.lower()
    for key, word in (("thunder", "雷雨"), ("snow", "雪"), ("sleet", "雨夹雪"),
                      ("rain", "雨"), ("drizzle", "毛毛雨"), ("fog", "雾"),
                      ("mist", "薄雾"), ("cloud", "多云"), ("overcast", "阴"),
                      ("clear", "晴"), ("sunny", "晴"), ("smoke", "烟霾"),
                      ("haze", "霾")):
        if key in low:
            return word
    return text or "未知"


def kind(text):
    text = str(text or "")
    if "雷" in text:
        return "thunder"
    if "雪" in text:
        return "snow"
    if "雨" in text:
        return "rain"
    if any(word in text for word in ("雾", "霾", "尘", "沙")):
        return "fog"
    if any(word in text for word in ("阴", "云")):
        return "cloud"
    return "sun"


def parse_current(payload, place=""):
    try:
        current = payload["current_condition"][0]
        desc = current.get("weatherDesc", [{}])[0].get("value", "")
        return {"temp": float(current["temp_C"]),
                "text": describe(desc),
                "place": place}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def _cache_path():
    return config.state_dir() / "weather.json"


def load_cache(max_age=900, place=None):
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        if place is not None and data.get("weather", {}).get("place") != place:
            return None
        if max_age is None or time.time() - float(data.get("at", 0)) <= max_age:
            return data.get("weather")
    except (OSError, ValueError, TypeError):
        pass
    return None


def _fetch(place):
    base = os.environ.get("UKUI_ISLAND_WEATHER_URL", "https://wttr.in")
    url = f"{base}/{urllib.parse.quote(place)}?format=j1&lang=zh"
    request = urllib.request.Request(url, headers={"User-Agent": "ukui-dynamic-island/0.1"})
    with urllib.request.urlopen(request, timeout=4) as response:
        return parse_current(json.loads(response.read().decode("utf-8")), place)


class Weather(QThread):
    updated = Signal(dict)

    def __init__(self, cfg, interval=900, parent=None):
        super().__init__(parent)
        self.place = cfg["weather_city"]
        self.interval = interval
        self._wake = threading.Event()

    def set_place(self, place):
        self.place = place
        self._wake.set()

    def run(self):
        while not self.isInterruptionRequested():
            delay = self.interval
            cached = load_cache(self.interval, self.place)
            if cached is not None:
                self.updated.emit(cached)
            else:
                stale = load_cache(None, self.place)
                if stale is not None:
                    self.updated.emit(stale)
                try:
                    weather = _fetch(self.place)
                except Exception:
                    weather = None
                if weather is not None:
                    try:
                        _cache_path().write_text(
                            json.dumps({"at": time.time(), "weather": weather}),
                            encoding="utf-8")
                    except OSError:
                        pass
                    self.updated.emit(weather)
                elif stale is None:
                    self.updated.emit({"place": self.place, "text": "不可用", "temp": None})
                    delay = 60
            for _ in range(delay):
                if self.isInterruptionRequested():
                    return
                if self._wake.wait(1.0):
                    self._wake.clear()
                    break
