"""Render the 3 形态 × 5 皮肤 matrix to one PNG. Offscreen, no desktop needed.

This is the visual contract for DESIGN.md: shape comes from BrimDeck's
CollapsedGeometry, palette/material from daozai's skins. Run:

    QT_QPA_PLATFORM=offscreen /usr/bin/python3 tests/style-theme-matrix.py
"""
import json
import re
import sys
from pathlib import Path

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QColor, QFont, QFontDatabase, QGuiApplication, QImage,
                         QLinearGradient, QPainter, QPainterPath, QPen,
                         QRadialGradient)

ROOT = Path(__file__).resolve().parent.parent
THEMES = ["classic", "cream", "glass-light", "glass-dark", "fluid"]
STYLES = [("notch", "刘海"), ("capsule", "胶囊"), ("line", "指示条")]

# CollapsedLimits / CollapsedGeometry, DIPs at scale 1.
NOTCH_W, NOTCH_H, NOTCH_INSET, NOTCH_CORNER, NOTCH_SHOULDER = 238, 32, 30, 12, 16
CAPSULE_W, CAPSULE_H, CAPSULE_INSET, CAPSULE_TOP = 196, 32, 16, 5
LINE_W, LINE_H, LINE_TOP = 56, 4, 4


def load_theme(name):
    text = (ROOT / "themes" / f"{name}.json").read_text(encoding="utf-8")
    text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    return json.loads(text)


def color(value):
    h = value.lstrip("#")
    a, rgb = ("FF", h) if len(h) == 6 else (h[:2], h[2:])
    return QColor(int(rgb[0:2], 16), int(rgb[2:4], 16), int(rgb[4:6], 16), int(a, 16))


def notch_path(r):
    s, c = NOTCH_SHOULDER, NOTCH_CORNER
    p = QPainterPath()
    p.moveTo(r.left() - s, r.top())
    p.quadTo(r.left(), r.top(), r.left(), r.top() + s)
    p.lineTo(r.left(), r.bottom() - c)
    p.quadTo(r.left(), r.bottom(), r.left() + c, r.bottom())
    p.lineTo(r.right() - c, r.bottom())
    p.quadTo(r.right(), r.bottom(), r.right(), r.bottom() - c)
    p.lineTo(r.right(), r.top() + s)
    p.quadTo(r.right(), r.top(), r.right() + s, r.top())
    p.closeSubpath()
    return p


def rounded_path(r, radius):
    p = QPainterPath()
    p.addRoundedRect(r, radius, radius)
    return p


def shape_rect(style, cx, top):
    if style == "notch":
        return QRectF(cx - NOTCH_W / 2, top, NOTCH_W, NOTCH_H)
    if style == "capsule":
        return QRectF(cx - CAPSULE_W / 2, top + CAPSULE_TOP, CAPSULE_W, CAPSULE_H)
    return QRectF(cx - LINE_W / 2, top + LINE_TOP, LINE_W, LINE_H)


def blur_crop(image, rect, radius=8):
    crop = image.copy(rect.toAlignedRect()).scaled(
        max(1, int(rect.width()) // radius), max(1, int(rect.height()) // radius),
        Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return crop.scaled(int(rect.width()), int(rect.height()), Qt.IgnoreAspectRatio,
                       Qt.SmoothTransformation)


def draw_surface(painter, path, rect, theme, backdrop):
    mat, c = theme["material"], theme["colors"]
    kind = mat["kind"]
    painter.save()
    if kind == "glass":
        painter.setClipPath(path)
        painter.drawImage(rect, blur_crop(backdrop, rect, mat.get("blur", 26) // 3))
        tint = color(mat["tint"])
        alpha = mat["alpha"]
        top = color(mat["tint"])
        top.setAlphaF(alpha * 0.72)
        bottom = color(mat["tint"])
        bottom.setAlphaF(alpha)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(path, gradient)
    elif kind == "fluid":
        painter.setClipPath(path)
        base = color(mat["tint"])
        base.setAlphaF(mat["alpha"])
        painter.fillPath(path, base)
        glow = QRadialGradient(rect.center() + QPointF(-rect.width() * 0.18, 0),
                               rect.width() * 0.55)
        accent = color(c["accent"])
        accent.setAlphaF(mat.get("glow", 0.25))
        glow.setColorAt(0.0, accent)
        accent.setAlphaF(0.0)
        glow.setColorAt(1.0, accent)
        painter.fillPath(path, glow)
    else:
        painter.fillPath(path, color(c["surface"]))

    painter.setClipping(False)
    rim_alpha = (int(255 * float(mat.get("rim", 0.12)))
                 if mat["kind"] != "opaque" else 10)
    rim = QPen(QColor(255, 255, 255, rim_alpha), 1)
    painter.setPen(rim)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()


def draw_ring(painter, center, radius, used, theme):
    c = theme["colors"]
    pen = QPen(color(c["ringTrack"]), 3, Qt.SolidLine, Qt.RoundCap)
    painter.setPen(pen)
    r = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    painter.drawArc(r, 0, 360 * 16)
    painter.setPen(QPen(color(c["accent"]), 3, Qt.SolidLine, Qt.RoundCap))
    painter.drawArc(r, 90 * 16, -int(used * 360 * 16))


def draw_equalizer(painter, x, cy, theme):
    painter.setPen(Qt.NoPen)
    painter.setBrush(color(theme["colors"]["equalizer"]))
    for i, h in enumerate((5, 10, 7, 12)):
        painter.drawRoundedRect(QRectF(x + i * 6, cy + 6 - h, 3, h), 1.5, 1.5)


def draw_content(painter, style, rect, theme, font):
    if style == "line":
        painter.save()
        painter.setClipPath(rounded_path(rect.adjusted(0.5, 0.5, -0.5, -0.5), 2))
        painter.fillRect(rect, color(theme["colors"]["indicator"]))
        accent = QRectF(rect.left(), rect.top(), rect.width() * 0.38, rect.height())
        painter.fillRect(accent, color(theme["colors"]["accent"]))
        painter.restore()
        return

    inset = (NOTCH_INSET if style == "notch" else CAPSULE_INSET) * rect.height() / 32
    left, right = rect.left() + inset, rect.right() - inset
    cy = rect.center().y()
    draw_ring(painter, QPointF(left + 11, cy), 9, 0.62, theme)

    painter.setPen(color(theme["colors"]["clock"]))
    painter.setFont(font)
    painter.drawText(QRectF(left + 30, rect.top(), 60, rect.height()),
                     Qt.AlignVCenter | Qt.AlignLeft, "09:41")
    draw_equalizer(painter, right - 18, cy, theme)


def wallpaper(w, h):
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, w, h)
    g.setColorAt(0.0, QColor("#101A33"))
    g.setColorAt(0.45, QColor("#1B2A4A"))
    g.setColorAt(1.0, QColor("#3B2450"))
    p.fillRect(img.rect(), g)
    for cx, cy, r, col in ((0.18, 0.25, 0.22, "#254B7A"), (0.62, 0.15, 0.20, "#6B3F86"),
                           (0.82, 0.70, 0.26, "#1E5B62"), (0.35, 0.85, 0.24, "#7A3550"),
                           (0.50, 0.50, 0.16, "#C98A4B")):
        rg = QRadialGradient(QPointF(w * cx, h * cy), max(w, h) * r)
        rg.setColorAt(0.0, QColor(col))
        rg.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.fillRect(img.rect(), rg)
    p.end()
    return img


def main():
    app = QGuiApplication(sys.argv)
    assert app
    scale = 2
    margin, cell_w, cell_h, gap, header = 118, 356, 128, 14, 46
    width = margin + len(THEMES) * (cell_w + gap) + gap
    height = header + len(STYLES) * (cell_h + gap) + gap

    app_font = "Noto Sans CJK SC"
    families = QFontDatabase().families()
    if app_font not in families:
        app_font = next((f for f in families if "CJK" in f or "WenQuanYi" in f), "Sans")
    label_font = QFont(app_font, 9)
    content_font = QFont(app_font, 13)
    content_font.setWeight(QFont.DemiBold)

    canvas = wallpaper(width * scale, height * scale)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.scale(scale, scale)
    painter.setPen(QColor(235, 238, 248, 220))
    painter.setFont(QFont(app_font, 11, QFont.Bold))
    painter.drawText(QRectF(0, 0, width, header), Qt.AlignCenter,
                     "UKUI 灵动岛 · 形态 × 皮肤")

    for row, (style, style_label) in enumerate(STYLES):
        y = header + row * (cell_h + gap)
        painter.setPen(QColor(225, 230, 245, 210))
        painter.setFont(label_font)
        painter.drawText(QRectF(8, y, margin - 16, cell_h),
                         Qt.AlignVCenter | Qt.AlignRight, style_label)
        for col, name in enumerate(THEMES):
            theme = load_theme(name)
            x = margin + col * (cell_w + gap)
            cx, top = x + cell_w / 2, y + 26
            rect = shape_rect(style, cx, top)

            painter.save()
            painter.translate(0, 0)
            if style == "notch":
                path = notch_path(rect)
            elif style == "capsule":
                path = rounded_path(rect, CAPSULE_H / 2)
            else:
                path = rounded_path(rect, LINE_H / 2)
            draw_surface(painter, path, rect, theme, canvas)
            draw_content(painter, style, rect, theme, content_font)
            painter.restore()

            painter.setPen(QColor(232, 236, 248, 200))
            painter.setFont(label_font)
            painter.drawText(QRectF(x, y + cell_h - 24, cell_w, 20), Qt.AlignCenter,
                             theme["name"])

    painter.end()
    out = ROOT / "screenshots" / "style-theme-matrix.png"
    canvas.save(str(out))
    print(f"{out}  {canvas.width()}x{canvas.height()}")


if __name__ == "__main__":
    sys.exit(main())
