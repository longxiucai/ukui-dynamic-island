"""Collapsed geometry, ported from BrimDeck's CollapsedGeometry (DIP values)."""
from dataclasses import dataclass

from PySide2.QtCore import QRectF

BASE_HEIGHT = 32.0
NOTCH_W, NOTCH_MIN_W, NOTCH_H, NOTCH_INSET = 238.0, 72.0, 32.0, 30.0
NOTCH_CORNER, NOTCH_SHOULDER = 12.0, 16.0
CAPSULE_W, CAPSULE_MIN_W, CAPSULE_H, CAPSULE_INSET, CAPSULE_TOP = 196.0, 48.0, 32.0, 16.0, 5.0
LINE_W, LINE_MIN_W, LINE_H, LINE_TOP = 56.0, 24.0, 4.0, 4.0
PANEL_W, PANEL_H, PANEL_RADIUS = 420.0, 140.0, 22.0
EDGE = 2.0
SHADOW = 8.0


@dataclass(frozen=True)
class Shape:
    style: str
    rect: QRectF       # surface, in window-local coordinates
    scale: float
    inset: float
    bottom_radius: float
    top_radius: float
    shoulder: float

    @property
    def bounds(self) -> QRectF:
        r = QRectF(self.rect)
        if self.shoulder:
            r.setLeft(r.left() - self.shoulder)
            r.setRight(r.right() + self.shoulder)
        return r


def resolve(style: str, screen_width: float, scale_pct: int = 100,
            content_width: float = 0.0, offset_x: int = 0) -> Shape:
    s = max(80, min(140, scale_pct)) / 100.0
    scale = s
    panel_width = min(PANEL_W, max(1.0, screen_width - 16.0))
    if style == "capsule":
        height = CAPSULE_H * scale
        width = max(CAPSULE_MIN_W * scale, content_width + 2 * CAPSULE_INSET * scale)
        width = min(width, panel_width, screen_width)
        left = (screen_width - width) / 2 + offset_x
        rect = QRectF(left, CAPSULE_TOP, width, height)
        return Shape(style, rect, height / BASE_HEIGHT, CAPSULE_INSET * height / BASE_HEIGHT,
                     height / 2, height / 2, 0.0)
    if style == "line":
        width = min(LINE_W * scale, screen_width)
        left = (screen_width - width) / 2 + offset_x
        rect = QRectF(left, LINE_TOP, width, LINE_H)
        return Shape(style, rect, 1.0, 0.0, LINE_H / 2, LINE_H / 2, 0.0)
    height = NOTCH_H * scale
    width = max(NOTCH_MIN_W * scale, content_width + 2 * NOTCH_INSET * scale)
    width = min(width, panel_width, screen_width)
    left = (screen_width - width) / 2 + offset_x
    rect = QRectF(left, 0.0, width, height)
    return Shape(style, rect, height / BASE_HEIGHT, NOTCH_INSET * height / BASE_HEIGHT,
                 NOTCH_CORNER * scale, 0.0, NOTCH_SHOULDER * scale)


def window_rect(shape: Shape, panel: QRectF = None) -> QRectF:
    """Screen-space window box: union of the surface and the open panel.

    Padding is constant so the box changes only with the surface itself; an
    animated shadow margin would move or resize the window after the morph.
    """
    r = QRectF(shape.bounds)
    if panel is not None:
        r = r.united(panel)
    r.adjust(-EDGE, -EDGE, EDGE, SHADOW)
    if r.top() < 0:
        r.setTop(0)
    return r


def expanded(style: str, screen_width: float, scale_pct: int = 100,
             offset_x: int = 0) -> Shape:
    """The surface at rest open: the collapsed pill grown into the details panel."""
    base = resolve(style, screen_width, scale_pct, offset_x=offset_x)
    width = min(PANEL_W, max(1.0, screen_width - 16.0))
    left = (screen_width - width) / 2 + offset_x
    rect = QRectF(left, base.rect.top(), width, PANEL_H)
    return Shape(style, rect, PANEL_H / BASE_HEIGHT, 16.0,
                 PANEL_RADIUS, PANEL_RADIUS, 0.0)


def morph(base: Shape, open_shape: Shape, width: float, height: float) -> Shape:
    """The surface part way between the two, keyed on height progress."""
    span = open_shape.rect.height() - base.rect.height()
    t = 0.0 if span <= 0 else max(0.0, min(1.0, (height - base.rect.height()) / span))
    left = base.bounds.center().x() - width / 2
    rect = QRectF(left, base.rect.top(), width, height)
    return Shape(base.style, rect, height / BASE_HEIGHT, base.inset,
                 base.bottom_radius + (open_shape.bottom_radius - base.bottom_radius) * t,
                 base.top_radius + (open_shape.top_radius - base.top_radius) * t,
                 base.shoulder * (1.0 - smoothstep(0.0, 0.32, t)))


def smoothstep(a: float, b: float, x: float) -> float:
    if b <= a:
        return 1.0 if x >= b else 0.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)
