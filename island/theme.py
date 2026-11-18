"""Theme files: JSON with // comments, `base` inheritance, contrast safety."""
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide2.QtGui import QColor

REQUIRED = {"surface", "textPrimary", "textSecondary", "textTertiary", "accent",
            "onAccent", "danger", "warning", "success", "clock", "equalizer",
            "hairline", "track", "ringTrack", "fill", "hover", "pressed",
            "outline", "popup", "popupBorder", "input", "shadow", "indicator"}

TEXT_TOKENS = ("textPrimary", "textSecondary", "textTertiary", "clock", "equalizer")


def resource_dir() -> Path:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        return Path(base)
    return Path(__file__).resolve().parent.parent


def themes_dir() -> Path:
    return resource_dir() / "themes"


def _strip_comments(text: str) -> str:
    # shortcut: only whole-line comments, no "//" handling inside strings;
    # every bundled theme keeps comments on their own line.
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def _read(theme_id: str) -> dict:
    if not re.fullmatch(r"[a-zA-Z0-9._-]{1,64}", theme_id):
        raise ValueError(f"invalid theme id: {theme_id!r}")
    path = themes_dir() / f"{theme_id}.json"
    return json.loads(_strip_comments(path.read_text(encoding="utf-8")))


def _merge(theme_id: str, seen=None) -> dict:
    seen = seen or set()
    if theme_id in seen:
        raise ValueError(f"theme base cycle at {theme_id}")
    seen.add(theme_id)
    raw = _read(theme_id)
    base_id = raw.get("base")
    if base_id:
        base = _merge(base_id, seen)
        colors = dict(base.get("colors", {}))
        colors.update(raw.get("colors", {}))
        material = raw.get("material") or base.get("material") or {"kind": "opaque"}
        merged = dict(base)
        merged.update(raw)
        merged["colors"] = colors
        merged["material"] = material
        return merged
    return raw


def _luminance(c: QColor) -> float:
    def channel(v: float) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * channel(c.red()) + 0.7152 * channel(c.green()) + 0.0722 * channel(c.blue())


def contrast(a: QColor, b: QColor) -> float:
    la, lb = _luminance(a), _luminance(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def _towards(c: QColor, target: int, step: float) -> QColor:
    return QColor(
        round(c.red() + (target - c.red()) * step),
        round(c.green() + (target - c.green()) * step),
        round(c.blue() + (target - c.blue()) * step),
        c.alpha(),
    )


def _ensure_contrast(colors: dict, minimums: dict) -> None:
    bg = colors.get("surface", QColor("#000000"))
    dark_bg = _luminance(bg) < 0.5
    for token, minimum in minimums.items():
        c = colors.get(token)
        if c is None:
            continue
        target = 255 if dark_bg else 0
        for _ in range(20):
            if contrast(c, bg) >= minimum:
                break
            c = _towards(c, target, 0.12)
        colors[token] = c


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    material: dict
    colors: dict

    def color(self, token: str) -> QColor:
        return QColor(self.colors.get(token, QColor("#FF00FF")))

    def with_accent(self, accent: QColor) -> "Theme":
        colors = dict(self.colors)
        if self.material.get("kind") == "fluid":
            colors["accent"] = QColor(accent)
        return Theme(self.id, self.name, self.material, colors)


def list_themes() -> list:
    return sorted(path.stem for path in themes_dir().glob("*.json"))


def load(theme_id: str) -> Theme:
    merged = _merge(theme_id)
    colors = {}
    for token, value in merged.get("colors", {}).items():
        c = QColor(value)
        if not c.isValid():
            raise ValueError(f"{theme_id}: bad color for {token}: {value}")
        colors[token] = c
    missing = REQUIRED - set(colors)
    if missing:
        raise ValueError(f"{theme_id}: missing tokens {sorted(missing)}")
    _ensure_contrast(colors, {t: 4.5 for t in TEXT_TOKENS})
    _ensure_contrast(colors, {"accent": 3.0})
    material = dict(merged.get("material") or {"kind": "opaque"})
    return Theme(theme_id, merged.get("name", theme_id), material, colors)
