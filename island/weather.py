"""Weather from Open-Meteo, with wttr.in used only for IP-based location."""
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


WMO = {
    0: "晴", 1: "晴间多云", 2: "多云", 3: "阴", 45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨", 56: "冻雨", 57: "冻雨",
    61: "小雨", 63: "中雨", 65: "大雨", 66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒", 80: "阵雨",
    81: "阵雨", 82: "强阵雨", 85: "阵雪", 86: "阵雪", 95: "雷阵雨",
    96: "雷阵雨", 99: "雷暴",
}


def text_for_code(code):
    try:
        return WMO.get(int(code), "未知")
    except (TypeError, ValueError):
        return "未知"


def _number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _get_json(url, timeout=8):
    request = urllib.request.Request(
        url, headers={"User-Agent": "ukui-dynamic-island/0.1"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def search_city(name):
    name = str(name or "").strip()
    if not name:
        return []
    queries = [name]
    if any("\u4e00" <= char <= "\u9fff" for char in name):
        if name.endswith("市"):
            queries.append(name[:-1])
        elif not name.endswith(("县", "区")):
            queries.append(name + "市")
    places = []
    for query in queries:
        url = ("https://geocoding-api.open-meteo.com/v1/search?"
               + urllib.parse.urlencode(
                   {"name": query, "count": 8, "language": "zh",
                    "format": "json"}))
        for item in _get_json(url).get("results") or []:
            lat = _number(item.get("latitude"))
            lon = _number(item.get("longitude"))
            if lat is None or lon is None:
                continue
            region = str(item.get("admin1") or item.get("admin2") or "")
            country = str(item.get("country") or "")
            place = {
                "name": str(item.get("name") or query),
                "region": region or country,
                "country": country,
                "population": _number(item.get("population")) or 0.0,
                "lat": lat,
                "lon": lon,
            }
            if not any(abs(place["lat"] - seen["lat"]) < 1e-5
                       and abs(place["lon"] - seen["lon"]) < 1e-5
                       for seen in places):
                places.append(place)
    places.sort(key=lambda item: item["population"], reverse=True)
    return places[:8]


def geocode_one(name):
    places = search_city(name)
    return places[0] if places else None


def locate():
    try:
        data = _get_json("https://ipinfo.io/json", timeout=6)
        lat, lon = (_number(part) for part in str(data.get("loc")).split(","))
        if lat is not None and lon is not None:
            return {
                "name": str(data.get("city") or data.get("region")
                            or "当前位置"),
                "region": str(data.get("region") or data.get("country") or ""),
                "lat": lat,
                "lon": lon,
            }
    except Exception:
        pass
    base = os.environ.get(
        "UKUI_ISLAND_WEATHER_URL", "https://wttr.in").rstrip("/")
    area = ((_get_json(f"{base}/?format=j1", timeout=6)
             .get("nearest_area") or [{}])[0])

    def first(key):
        values = area.get(key) or [{}]
        return str((values[0] or {}).get("value") or "").strip()

    lat, lon = _number(area.get("latitude")), _number(area.get("longitude"))
    if lat is None or lon is None:
        raise LookupError("无法按网络出口定位")
    return {
        "name": first("areaName") or first("region") or "当前位置",
        "region": first("region") or first("country"),
        "lat": lat,
        "lon": lon,
    }


def parse_forecast(payload, spot=None):
    spot = spot or {}
    current = payload.get("current") or {}
    daily = payload.get("daily") or {}
    temp = _number(current.get("temperature_2m"))
    if temp is None:
        return None
    days = []
    times = daily.get("time") or []
    for index, date in enumerate(times[:7]):
        def day(key):
            values = daily.get(key) or []
            return values[index] if index < len(values) else None

        code = day("weather_code")
        text = text_for_code(code)
        days.append({
            "date": str(date),
            "text": text,
            "kind": kind(text),
            "code": code,
            "high": _number(day("temperature_2m_max")),
            "low": _number(day("temperature_2m_min")),
            "precip": _number(day("precipitation_probability_max")),
            "sunrise": str(day("sunrise") or "")[-5:],
            "sunset": str(day("sunset") or "")[-5:],
        })
    today = days[0] if days else {}
    text = text_for_code(current.get("weather_code"))
    return {
        "place": str(spot.get("name") or ""),
        "region": str(spot.get("region") or ""),
        "lat": spot.get("lat"),
        "lon": spot.get("lon"),
        "temp": temp,
        "text": text,
        "kind": kind(text),
        "code": current.get("weather_code"),
        "feels": _number(current.get("apparent_temperature")),
        "humidity": _number(current.get("relative_humidity_2m")),
        "wind": _number(current.get("wind_speed_10m")),
        "high": today.get("high"),
        "low": today.get("low"),
        "sunrise": today.get("sunrise") or "",
        "sunset": today.get("sunset") or "",
        "daily": days,
        "at": time.time(),
    }


def forecast(lat, lon, spot=None):
    url = ("https://api.open-meteo.com/v1/forecast?"
           + urllib.parse.urlencode({
               "latitude": f"{float(lat):.4f}",
               "longitude": f"{float(lon):.4f}",
               "current": ("temperature_2m,relative_humidity_2m,"
                           "apparent_temperature,weather_code,wind_speed_10m"),
               "daily": ("weather_code,temperature_2m_max,"
                         "temperature_2m_min,sunrise,sunset,"
                         "precipitation_probability_max"),
               "timezone": "auto",
               "forecast_days": 7,
           }))
    return parse_forecast(_get_json(url), spot)


def _cache_path():
    return config.state_dir() / "weather.json"


def load_cache(max_age=900, place=None, errors=None, key=None):
    try:
        data = json.loads(_cache_path().read_text(encoding="utf-8"))
        weather = dict(data.get("weather") or {})
        if key is not None and data.get("key") != key:
            return None
        if key is None and place is not None and weather.get("place") != place:
            return None
        if max_age is None or time.time() - float(data.get("at", 0)) <= max_age:
            weather.setdefault("at", data.get("at"))
            return weather
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as exc:
        if errors is not None:
            errors.append(f"{type(exc).__name__}: {exc}")
    return None


class Weather(QThread):
    updated = Signal(dict)

    def __init__(self, cfg, interval=900, parent=None):
        super().__init__(parent)
        self.auto = bool(cfg.get("weather_auto"))
        self.place = str(cfg.get("weather_city") or "")
        self.lat = cfg.get("weather_lat")
        self.lon = cfg.get("weather_lon")
        self.interval = interval
        self._wake = threading.Event()
        self._force = False

    def set_place(self, place, lat=None, lon=None):
        self.auto = False
        self.place = str(place or "")
        self.lat = lat
        self.lon = lon
        self._wake.set()

    def set_auto(self):
        self.auto = True
        self._wake.set()

    def refresh(self):
        self._force = True
        self._wake.set()

    def _location(self):
        if self.auto:
            return "auto", locate()
        if self.lat is not None and self.lon is not None:
            return (f"{float(self.lat):.3f},{float(self.lon):.3f}",
                    {"name": self.place or "当前位置", "region": "",
                     "lat": float(self.lat), "lon": float(self.lon)})
        spot = geocode_one(self.place)
        if spot is None:
            raise LookupError(f"找不到城市：{self.place}")
        return None, spot

    def _sleep(self, seconds):
        for _ in range(int(seconds)):
            if self.isInterruptionRequested():
                return
            if self._wake.wait(1.0):
                self._wake.clear()
                return

    def run(self):
        while not self.isInterruptionRequested():
            delay = self.interval
            cache_errors = []
            force = self._force
            self._force = False
            try:
                key, spot = self._location()
            except Exception as exc:
                error = f"{type(exc).__name__}: {exc}"
                stale = load_cache(
                    None, None if self.auto else self.place,
                    key="auto" if self.auto else None)
                if stale is not None:
                    self.updated.emit({**stale, "stale": True, "error": error})
                else:
                    self.updated.emit({
                        "place": self.place or "自动定位", "temp": None,
                        "text": "不可用", "stale": True, "error": error})
                self._sleep(60)
                continue
            place = spot.get("name") or self.place
            cached = (None if force else load_cache(
                self.interval, place, cache_errors, key))
            cache_error = "; ".join(dict.fromkeys(cache_errors))
            if cached is not None:
                self.updated.emit({**cached, "stale": False,
                                   "cache_error": cache_error})
            else:
                stale = load_cache(None, place, cache_errors, key)
                cache_error = "; ".join(dict.fromkeys(cache_errors))
                if stale is not None and not force:
                    self.updated.emit({**stale, "stale": True,
                                       "cache_error": cache_error})
                error = ""
                try:
                    weather = forecast(spot["lat"], spot["lon"], spot)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    weather = None
                if weather is not None:
                    try:
                        _cache_path().write_text(
                            json.dumps({"at": time.time(),
                                        "key": key or place,
                                        "weather": weather}),
                            encoding="utf-8")
                    except OSError as exc:
                        weather["cache_error"] = f"{type(exc).__name__}: {exc}"
                    self.updated.emit({**weather, "stale": False,
                                       "cache_error": cache_error})
                elif stale is None:
                    self.updated.emit({"place": place, "text": "不可用",
                                       "temp": None, "stale": True,
                                       "cache_error": cache_error,
                                       "error": error or "没有返回数据"})
                    delay = 60
                else:
                    self.updated.emit({**stale, "stale": True,
                                       "cache_error": cache_error,
                                       "error": error or "刷新失败"})
            self._sleep(delay)


class CitySearch(QThread):
    found = Signal(str, list)

    def __init__(self, text, parent=None):
        super().__init__(parent)
        self.text = str(text or "")

    def run(self):
        try:
            self.found.emit(self.text, search_city(self.text))
        except Exception:
            self.found.emit(self.text, [])
