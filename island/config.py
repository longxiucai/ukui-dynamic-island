"""Settings on disk: atomic writes, 0600, validated on load."""
import json
import os
import tempfile
from pathlib import Path

STYLES = ("notch", "capsule", "line")

DEFAULTS = {
    "theme": "classic",
    "style": "notch",
    "scale": 100,
    "offset_x": 0,
    "clock_12h": False,
    "show_seconds": False,
    "clock_period": 0,
    "show_weekday": False,
    "clock_english": False,
    "autostart": False,
    "show_weather": True,
    "show_monitor": True,
    "weather_city": "北京",
    "focus_minutes": 25,
    "rest_minutes": 5,
    "focus_remind": True,
    "water_remind": True,
    "water_minutes": 45,
    "mail_remind": True,
    "mail_host": "",
    "mail_port": 993,
    "mail_user": "",
    "mail_password": "",
    "mail_tls": True,
    "mail_sync_operations": False,
    "calendar_url": "",
    "calendar_user": "",
    "calendar_password": "",
    "quota_url": "",
    "quota_token": "",
    "codex_online": False,
    "claude_online": False,
    "workbuddy_online": False,
    "trae_online": False,
    "copilot_online": False,
    "show_pet": True,
    "click_through": False,
    "hide_fullscreen": True,
    "enable_blur": True,
}


def _dir(env: str, fallback: str) -> Path:
    override = os.environ.get(env)
    base = Path(override) if override else Path.home() / fallback
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_dir() -> Path:
    return _dir("UKUI_ISLAND_CONFIG_DIR", ".config/ukui-dynamic-island")


def config_path() -> Path:
    return config_dir() / "config.json"


def state_dir() -> Path:
    return _dir("UKUI_ISLAND_STATE_DIR", ".local/state/ukui-dynamic-island")


def _clean(raw: dict) -> dict:
    cfg = dict(DEFAULTS)
    theme = raw.get("theme")
    if isinstance(theme, str) and 0 < len(theme) <= 64:
        cfg["theme"] = theme
    if raw.get("style") in STYLES:
        cfg["style"] = raw["style"]
    if isinstance(raw.get("scale"), int):
        cfg["scale"] = max(80, min(140, raw["scale"]))
    if isinstance(raw.get("offset_x"), int):
        cfg["offset_x"] = max(-2000, min(2000, raw["offset_x"]))
    for key in ("clock_12h", "show_seconds", "show_weekday", "clock_english",
                "show_weather", "show_monitor", "autostart", "mail_tls",
                "show_pet",
                "click_through", "hide_fullscreen", "enable_blur",
                "focus_remind", "water_remind", "mail_remind",
                "mail_sync_operations", "codex_online", "claude_online",
                "workbuddy_online", "trae_online", "copilot_online"):
        if isinstance(raw.get(key), bool):
            cfg[key] = raw[key]
    if (isinstance(raw.get("clock_period"), int)
            and not isinstance(raw.get("clock_period"), bool)
            and 0 <= raw["clock_period"] <= 2):
        cfg["clock_period"] = raw["clock_period"]
    city = raw.get("weather_city")
    if isinstance(city, str) and 0 < len(city) <= 64:
        cfg["weather_city"] = city
    for key in ("mail_host", "mail_user", "mail_password", "calendar_url",
                "calendar_user", "calendar_password", "quota_url",
                "quota_token"):
        value = raw.get(key)
        if isinstance(value, str) and len(value) <= 512:
            cfg[key] = value
    if (isinstance(raw.get("mail_port"), int)
            and not isinstance(raw.get("mail_port"), bool)
            and 1 <= raw["mail_port"] <= 65535):
        cfg["mail_port"] = raw["mail_port"]
    for key, low, high in (("focus_minutes", 1, 180), ("rest_minutes", 1, 60),
                           ("water_minutes", 5, 180)):
        if (isinstance(raw.get(key), int) and not isinstance(raw.get(key), bool)
                and low <= raw[key] <= high):
            cfg[key] = raw[key]
    return cfg


def load() -> dict:
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("config root is not an object")
    except FileNotFoundError:
        return dict(DEFAULTS)
    except Exception:
        return dict(DEFAULTS)
    return _clean(raw)


def save(cfg: dict) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".config-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
