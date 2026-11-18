"""All painting. Pure: inputs are theme + shape + state, no IO."""
import math

from PySide2.QtCore import QPointF, QRectF, Qt
from PySide2.QtGui import (QColor, QFont, QFontDatabase, QFontMetrics,
                           QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

FAMILY_CACHE = {}


def ui_font(px: float, weight=QFont.Normal) -> QFont:
    family = FAMILY_CACHE.get("family")
    if family is None:
        families = QFontDatabase().families()
        for candidate in ("Noto Sans CJK SC", "Noto Sans SC", "Source Han Sans SC",
                          "WenQuanYi Micro Hei", "Droid Sans Fallback", "DejaVu Sans"):
            if candidate in families:
                family = candidate
                break
        else:
            family = QFont().family()
        FAMILY_CACHE["family"] = family
    font = QFont(family)
    font.setPixelSize(max(1, int(round(px))))
    font.setWeight(weight)
    return font


def text_width(text: str, px: float, weight=QFont.Normal) -> int:
    return QFontMetrics(ui_font(px, weight)).horizontalAdvance(text)


def elide(text: str, px: float, width: float, weight=QFont.Normal) -> str:
    return QFontMetrics(ui_font(px, weight)).elidedText(text, Qt.ElideRight, int(width))


def wrap_text(text: str, px: float, width: float, weight=QFont.Normal):
    """Greedy character wrap; matches the reference project's break-anywhere."""
    if not text:
        return []
    metrics = QFontMetrics(ui_font(px, weight))
    rows = []
    line = ""
    for char in str(text):
        if char == "\n":
            rows.append(line)
            line = ""
            continue
        candidate = line + char
        if line and metrics.horizontalAdvance(candidate) > width:
            rows.append(line)
            line = char
        else:
            line = candidate
    if line:
        rows.append(line)
    return rows


def marquee_offset(text_width: float, room: float, elapsed: float,
                   speed: float = 24.0, gap: float = 24.0) -> float:
    if text_width <= room or room <= 0:
        return 0.0
    return (elapsed * speed) % (text_width + gap)


def seek_seconds(x: float, left: float, width: float, length: float) -> float:
    if width <= 0 or length <= 0:
        return 0.0
    return max(0.0, min(length, (x - left) / width * length))


def paint_marquee(painter: QPainter, rect: QRectF, text: str, theme, px: float,
                  elapsed: float, weight=QFont.Normal,
                  token: str = "textPrimary") -> None:
    width = text_width(text, px, weight)
    if width <= rect.width():
        paint_text(painter, rect, text, theme, px, weight, token=token)
        return
    offset = marquee_offset(width, rect.width(), elapsed)
    painter.save()
    painter.setClipRect(rect)
    painter.setPen(theme.color(token))
    painter.setFont(ui_font(px, weight))
    painter.drawText(QPointF(rect.left() - offset, rect.center().y() + px * 0.35), text)
    painter.drawText(QPointF(rect.left() - offset + width + 24, rect.center().y() + px * 0.35),
                     text)
    painter.restore()


def surface_path(shape) -> QPainterPath:
    r = shape.rect
    p = QPainterPath()
    if shape.style == "notch" and shape.shoulder > 0.5:
        s, c = shape.shoulder, shape.bottom_radius
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
    top = min(shape.top_radius, r.height() / 2, r.width() / 2)
    bottom = min(shape.bottom_radius, r.height() / 2, r.width() / 2)
    p.moveTo(r.left() + top, r.top())
    p.lineTo(r.right() - top, r.top())
    p.quadTo(r.right(), r.top(), r.right(), r.top() + top)
    p.lineTo(r.right(), r.bottom() - bottom)
    p.quadTo(r.right(), r.bottom(), r.right() - bottom, r.bottom())
    p.lineTo(r.left() + bottom, r.bottom())
    p.quadTo(r.left(), r.bottom(), r.left(), r.bottom() - bottom)
    p.lineTo(r.left(), r.top() + top)
    p.quadTo(r.left(), r.top(), r.left() + top, r.top())
    p.closeSubpath()
    return p


def paint_surface(painter: QPainter, path: QPainterPath, theme, accent=None) -> None:
    mat = theme.material
    kind = mat.get("kind", "opaque")
    rect = path.boundingRect()
    painter.save()
    if kind == "glass":
        tint = QColor(mat.get("tint", "#FFFFFF"))
        alpha = float(mat.get("alpha", 0.6))
        top = QColor(tint)
        top.setAlphaF(alpha * 0.72)
        bottom = QColor(tint)
        bottom.setAlphaF(alpha)
        gradient = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.fillPath(path, gradient)
    elif kind == "fluid":
        base = QColor(mat.get("tint", "#1A1A1D"))
        base.setAlphaF(float(mat.get("alpha", 0.55)))
        painter.fillPath(path, base)
        glow = QRadialGradient(QPointF(rect.center().x() - rect.width() * 0.2, rect.center().y()),
                               max(rect.width(), 1) * 0.6)
        c = QColor(accent or theme.color("accent"))
        c.setAlphaF(float(mat.get("glow", 0.25)))
        glow.setColorAt(0.0, c)
        c.setAlphaF(0.0)
        glow.setColorAt(1.0, c)
        painter.fillPath(path, glow)
    else:
        painter.fillPath(path, theme.color("surface"))

    rim = QColor(255, 255, 255,
                 int(255 * float(mat.get("rim", 0.12)))
                 if kind != "opaque" else 10)
    painter.setPen(QPen(rim, 1))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(path)
    painter.restore()


def paint_battery(painter: QPainter, x: float, cy: float, level: float, theme,
                  charging: bool = False, scale: float = 1.0) -> float:
    w, h = 18.0 * scale, 9.0 * scale
    body = QRectF(x, cy - h / 2, w, h)
    painter.setPen(QPen(theme.color("textSecondary"), 1.2 * scale))
    painter.setBrush(Qt.NoBrush)
    painter.drawRoundedRect(body, 2.2 * scale, 2.2 * scale)
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color("textSecondary"))
    painter.drawRoundedRect(QRectF(body.right() + scale, cy - 2 * scale,
                                   2 * scale, 4 * scale), scale, scale)
    level = max(0.0, min(1.0, level))
    color = theme.color("success") if charging else (
        theme.color("danger") if level < 0.15 else theme.color("textPrimary"))
    painter.setBrush(color)
    inner = body.adjusted(1.8 * scale, 1.8 * scale, -1.8 * scale, -1.8 * scale)
    painter.drawRoundedRect(QRectF(inner.left(), inner.top(),
                                   inner.width() * level, inner.height()), scale, scale)
    return w + 4 * scale


def mix_color(first: QColor, second: QColor, share: float) -> QColor:
    share = max(0.0, min(1.0, share))
    return QColor(
        round(first.red() + (second.red() - first.red()) * share),
        round(first.green() + (second.green() - first.green()) * share),
        round(first.blue() + (second.blue() - first.blue()) * share),
        round(first.alpha() + (second.alpha() - first.alpha()) * share),
    )


def ring_color(theme, level: float, normal_token: str = "accent") -> QColor:
    """BrimDeck's 80/92 levels, eased over a short band instead of jumping."""
    level = max(0.0, min(1.0, level))
    normal = theme.color(normal_token)
    warning = theme.color("warning")
    danger = theme.color("danger")
    if level >= 0.92:
        return danger
    if level >= 0.8:
        share = (level - 0.8) / 0.12
        return mix_color(warning, danger, share * share * (3.0 - 2.0 * share))
    if level >= 0.79:
        share = (level - 0.79) / 0.01
        return mix_color(normal, warning, share * share * (3.0 - 2.0 * share))
    return normal


def paint_ring_gauge(painter: QPainter, x: float, cy: float, size: float,
                     level: float, text: str, theme, token: str = "accent") -> float:
    """A percentage's ring, clockwise from the top, with its figure inside."""
    level = max(0.0, min(1.0, level))
    color = ring_color(theme, level, token)
    stroke = max(1.4, size * 0.11)
    rect = QRectF(x + stroke / 2, cy - size / 2 + stroke / 2,
                  size - stroke, size - stroke)
    painter.save()
    painter.setBrush(Qt.NoBrush)
    track = QPen(theme.color("ringTrack"), stroke)
    track.setCapStyle(Qt.RoundCap)
    painter.setPen(track)
    painter.drawEllipse(rect)
    if level > 0.002:
        pen = QPen(color, stroke)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        if level >= 0.999:
            painter.drawEllipse(rect)
        else:
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * level))
    painter.setPen(color if level >= 0.8 else theme.color("textPrimary"))
    painter.setFont(ui_font(max(1.0, size * 0.35), QFont.DemiBold))
    painter.drawText(QRectF(x, cy - size / 2, size, size), Qt.AlignCenter, text)
    painter.restore()
    return size


def paint_quota_rings(painter: QPainter, x: float, cy: float, size: float,
                      shares, theme, tokens=None) -> None:
    """Two concentric remaining-share rings, as the reference quota pages."""
    shares = [max(0.0, min(1.0, float(value))) for value in (shares or [])][:2]
    tokens = list(tokens or [])
    count = max(1, len(shares))
    stroke = max(1.8, size * (0.075 if count > 1 else 0.11))
    gap = max(1.6, size * 0.045)
    painter.save()
    painter.setBrush(Qt.NoBrush)
    for index in range(count):
        radius = size / 2.0 - stroke / 2.0 - 1.0
        if index:
            radius -= index * (stroke + gap)
        rect = QRectF(x - radius, cy - radius, radius * 2, radius * 2)
        track = QPen(theme.color("ringTrack"), stroke)
        track.setCapStyle(Qt.RoundCap)
        painter.setPen(track)
        painter.drawEllipse(rect)
        if index >= len(shares):
            continue
        share = shares[index]
        if share <= 0.002:
            continue
        token = tokens[index] if index < len(tokens) else "accent"
        color = ring_color(theme, 1.0 - share, token)
        pen = QPen(color, stroke)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        if share >= 0.999:
            painter.drawEllipse(rect)
        else:
            painter.drawArc(rect, 90 * 16, int(-360 * 16 * share))
    text = "--" if not shares else f"{shares[0] * 100:.0f}%"
    color = (theme.color("textTertiary") if not shares else
             theme.color("textPrimary"))
    painter.setPen(color)
    painter.setFont(ui_font(max(8.0, size * (0.27 if count > 1 else 0.30)),
                            QFont.DemiBold))
    painter.drawText(QRectF(x - size / 2, cy - size / 2, size, size),
                     Qt.AlignCenter, text)
    painter.restore()


def paint_weather_icon(painter: QPainter, x: float, cy: float, size: float,
                       kind: str, theme) -> float:
    """The pill's tiny weather mark: one glyph-sized vector, no background."""
    s = size
    pen = max(1.0, s * 0.09)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if kind == "sun":
        c = QPointF(x + s / 2, cy)
        r = s * 0.2
        painter.setPen(QPen(theme.color("warning"), pen))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(c, r, r)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0),
                       (-0.7, -0.7), (0.7, -0.7), (-0.7, 0.7), (0.7, 0.7)):
            painter.drawLine(QPointF(c.x() + dx * r * 1.45, c.y() + dy * r * 1.45),
                             QPointF(c.x() + dx * r * 1.95, c.y() + dy * r * 1.95))
        painter.restore()
        return size

    if kind == "fog":
        painter.setPen(QPen(theme.color("textSecondary"), pen, Qt.SolidLine, Qt.RoundCap))
        for dy, left, right in ((-0.2, 0.18, 0.78), (0.05, 0.1, 0.88), (0.3, 0.22, 0.72)):
            painter.drawLine(QPointF(x + s * left, cy + s * dy),
                             QPointF(x + s * right, cy + s * dy))
        painter.restore()
        return size

    cloud = QPainterPath()
    cloud.addEllipse(QRectF(x + s * 0.12, cy - s * 0.19, s * 0.38, s * 0.34))
    cloud.addEllipse(QRectF(x + s * 0.34, cy - s * 0.31, s * 0.44, s * 0.44))
    cloud.addRoundedRect(QRectF(x + s * 0.14, cy - s * 0.02, s * 0.7, s * 0.3),
                         s * 0.13, s * 0.13)
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color("textSecondary"))
    painter.drawPath(cloud.simplified())

    if kind == "rain":
        painter.setPen(QPen(theme.color("accent"), pen, Qt.SolidLine, Qt.RoundCap))
        for dx in (0.35, 0.55, 0.75):
            painter.drawLine(QPointF(x + s * dx, cy + s * 0.35),
                             QPointF(x + s * (dx - 0.08), cy + s * 0.52))
    elif kind == "snow":
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("textPrimary"))
        for dx, dy in ((0.32, 0.43), (0.52, 0.5), (0.72, 0.41)):
            painter.drawEllipse(QPointF(x + s * dx, cy + s * dy), pen * 0.65, pen * 0.65)
    elif kind == "thunder":
        bolt = QPainterPath()
        bolt.moveTo(x + s * 0.53, cy + s * 0.26)
        bolt.lineTo(x + s * 0.4, cy + s * 0.58)
        bolt.lineTo(x + s * 0.54, cy + s * 0.56)
        bolt.lineTo(x + s * 0.48, cy + s * 0.8)
        bolt.lineTo(x + s * 0.73, cy + s * 0.42)
        bolt.lineTo(x + s * 0.58, cy + s * 0.44)
        bolt.closeSubpath()
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("warning"))
        painter.drawPath(bolt)
    painter.restore()
    return size


def paint_equalizer(painter: QPainter, x: float, cy: float, theme,
                    phase: float = 0.0, size: float = 1.0) -> float:
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color("equalizer"))
    for i, base in enumerate((5.0, 10.0, 7.0, 12.0)):
        import math
        h = max(2.0, base * (0.55 + 0.45 * abs(math.sin(phase + i * 0.9))))
        painter.drawRoundedRect(
            QRectF(x + i * 6 * size, cy + (6 - h) * size, 3 * size, h * size),
            1.5 * size, 1.5 * size)
    return 22.0 * size


def paint_play(painter: QPainter, x: float, cy: float, size: float, theme,
               token: str = "textPrimary") -> None:
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color(token))
    path = QPainterPath()
    path.moveTo(x, cy - size / 2)
    path.lineTo(x + size * 0.85, cy)
    path.lineTo(x, cy + size / 2)
    path.closeSubpath()
    painter.drawPath(path)
    painter.restore()


def paint_pause(painter: QPainter, x: float, cy: float, size: float, theme,
                token: str = "textPrimary") -> None:
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color(token))
    width = size * 0.28
    painter.drawRoundedRect(QRectF(x, cy - size / 2, width, size), 1, 1)
    painter.drawRoundedRect(QRectF(x + size - width, cy - size / 2, width, size), 1, 1)
    painter.restore()


def paint_skip(painter: QPainter, x: float, cy: float, size: float, theme,
               forward: bool = True) -> None:
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color("textSecondary"))
    if not forward:
        painter.translate(x + size, 0)
        painter.scale(-1, 1)
        x = 0
    path = QPainterPath()
    path.moveTo(x, cy - size / 2)
    path.lineTo(x + size * 0.62, cy)
    path.lineTo(x, cy + size / 2)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawRoundedRect(QRectF(x + size * 0.66, cy - size / 2,
                                   size * 0.18, size), 1, 1)
    painter.restore()


def paint_panel(painter: QPainter, rect: QRectF, theme) -> None:
    painter.save()
    painter.setPen(QPen(theme.color("popupBorder"), 1))
    painter.setBrush(theme.color("popup"))
    painter.drawRoundedRect(rect, 14, 14)
    painter.restore()


def paint_text(painter: QPainter, rect: QRectF, text: str, theme, px: float,
               weight=QFont.Normal, align=Qt.AlignLeft | Qt.AlignVCenter,
               token: str = "textPrimary") -> None:
    painter.setPen(theme.color(token))
    painter.setFont(ui_font(px, weight))
    painter.drawText(rect, align, text)


def paint_button(painter: QPainter, rect: QRectF, text: str, theme,
                 active: bool = False, px: float = 9.5,
                 token: str = None) -> None:
    painter.save()
    painter.setPen(QPen(theme.color("outline"), 1) if not active else Qt.NoPen)
    painter.setBrush(theme.color("hover") if active else theme.color("fill"))
    painter.drawRoundedRect(rect, min(8.0, rect.height() / 2),
                            min(8.0, rect.height() / 2))
    painter.restore()
    paint_text(painter, rect, text, theme, px, QFont.DemiBold, Qt.AlignCenter,
               token=token or ("accent" if active else "textSecondary"))


def paint_bar(painter: QPainter, rect: QRectF, ratio: float, theme,
              token: str = "accent") -> None:
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color("track"))
    painter.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
    ratio = max(0.0, min(1.0, ratio))
    if ratio > 0:
        painter.setBrush(theme.color(token))
        painter.drawRoundedRect(QRectF(rect.left(), rect.top(),
                                       rect.width() * ratio, rect.height()),
                                rect.height() / 2, rect.height() / 2)
    painter.restore()


def paint_pet(painter: QPainter, x: float, cy: float, size: float, theme,
              mood: str = "awake", phase: float = 0.0) -> None:
    """The island's small companion: one vector face, no image assets."""
    s = size
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color("textPrimary"))
    painter.drawEllipse(QPointF(x + s / 2, cy), s * 0.46, s * 0.42)
    ink = theme.color("surface")
    painter.setBrush(ink)
    blink = (phase % 4.6) > 4.4 and mood not in ("music", "focus")
    for offset in (-0.17, 0.17):
        if blink:
            painter.setPen(QPen(ink, max(1.0, s * 0.07)))
            painter.drawLine(QPointF(x + s * (0.5 + offset) - s * 0.05, cy - s * 0.06),
                             QPointF(x + s * (0.5 + offset) + s * 0.05, cy - s * 0.06))
            painter.setPen(Qt.NoPen)
        else:
            painter.drawEllipse(QPointF(x + s * (0.5 + offset), cy - s * 0.07),
                                s * 0.065, s * 0.09)
    painter.setPen(QPen(ink, max(1.0, s * 0.055), Qt.SolidLine, Qt.RoundCap))
    if mood == "music":
        painter.setBrush(ink)
        painter.drawEllipse(QPointF(x + s * 0.5, cy + s * 0.17), s * 0.09, s * 0.12)
    elif mood == "focus":
        painter.drawLine(QPointF(x + s * 0.4, cy + s * 0.17),
                         QPointF(x + s * 0.6, cy + s * 0.17))
    elif mood == "happy":
        path = QPainterPath()
        path.moveTo(x + s * 0.4, cy + s * 0.13)
        path.quadTo(x + s * 0.5, cy + s * 0.28, x + s * 0.6, cy + s * 0.13)
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(path)
    else:
        painter.drawArc(QRectF(x + s * 0.38, cy + s * 0.06, s * 0.24, s * 0.16),
                        200 * 16, 140 * 16)
    painter.restore()


def paint_chevron(painter: QPainter, x: float, cy: float, direction: float,
                  theme, alpha: float = 1.0) -> None:
    color = theme.color("textSecondary")
    color.setAlphaF(max(0.0, min(1.0, alpha)))
    painter.save()
    painter.setPen(QPen(color, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(QPointF(x, cy - 5), QPointF(x + 5 * direction, cy))
    painter.drawLine(QPointF(x + 5 * direction, cy), QPointF(x, cy + 5))
    painter.restore()


def paint_gear(painter: QPainter, cx: float, cy: float, size: float, theme) -> None:
    import math
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(QPen(theme.color("textSecondary"), max(1.1, size * 0.12),
                        Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    painter.drawEllipse(QPointF(cx, cy), size * 0.33, size * 0.33)
    for index in range(6):
        angle = math.tau * index / 6
        inner = size * 0.38
        outer = size * 0.48
        painter.drawLine(QPointF(cx + math.cos(angle) * inner,
                                 cy + math.sin(angle) * inner),
                         QPointF(cx + math.cos(angle) * outer,
                                 cy + math.sin(angle) * outer))
    painter.drawEllipse(QPointF(cx, cy), size * 0.09, size * 0.09)
    painter.restore()


def paint_checklist(painter: QPainter, x: float, cy: float, size: float, theme,
                    token: str = "success") -> None:
    painter.save()
    color = theme.color(token)
    painter.setPen(QPen(color, max(1.0, size * 0.11), Qt.SolidLine, Qt.RoundCap))
    for row in (-1, 1):
        y = cy + row * size * 0.24
        box = QRectF(x, y - size * 0.14, size * 0.28, size * 0.28)
        painter.drawRoundedRect(box, size * 0.05, size * 0.05)
        painter.drawLine(QPointF(box.left() + size * 0.07, box.center().y()),
                         QPointF(box.left() + size * 0.13, box.bottom() - size * 0.05))
        painter.drawLine(QPointF(box.left() + size * 0.13, box.bottom() - size * 0.05),
                         QPointF(box.right() - size * 0.04, box.top() + size * 0.05))
        painter.drawLine(QPointF(x + size * 0.42, y),
                         QPointF(x + size * 0.92, y))
    painter.restore()


def paint_envelope(painter: QPainter, x: float, cy: float, size: float, theme,
                   token: str = "accent") -> None:
    painter.save()
    color = theme.color(token)
    painter.setPen(QPen(color, max(1.0, size * 0.1), Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    body = QRectF(x, cy - size * 0.32, size, size * 0.64)
    painter.drawRoundedRect(body, size * 0.08, size * 0.08)
    flap = QPainterPath()
    flap.moveTo(body.left(), body.top() + size * 0.08)
    flap.lineTo(body.center().x(), body.center().y() + size * 0.04)
    flap.lineTo(body.right(), body.top() + size * 0.08)
    painter.drawPath(flap)
    painter.restore()


def paint_tomato(painter: QPainter, cx: float, cy: float, size: float, theme,
                 token: str = "danger") -> None:
    painter.save()
    color = theme.color(token)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(cx, cy + size * 0.09), size * 0.42,
                        size * 0.35)
    highlight = QColor(255, 255, 255, 60)
    painter.setBrush(highlight)
    painter.drawEllipse(QPointF(cx - size * 0.12, cy - size * 0.02),
                        size * 0.1, size * 0.06)
    leaf = theme.color("success")
    painter.setBrush(leaf)
    for direction in (-1, 1):
        leaf_path = QPainterPath()
        leaf_path.moveTo(cx, cy - size * 0.26)
        leaf_path.quadTo(cx + direction * size * 0.36, cy - size * 0.4,
                         cx + direction * size * 0.32, cy - size * 0.18)
        leaf_path.quadTo(cx + direction * size * 0.16, cy - size * 0.16,
                         cx, cy - size * 0.26)
        painter.drawPath(leaf_path)
    painter.setPen(QPen(leaf, max(1.0, size * 0.08), Qt.SolidLine,
                        Qt.RoundCap))
    painter.drawLine(QPointF(cx, cy - size * 0.26),
                     QPointF(cx, cy - size * 0.43))
    painter.restore()


def paint_file(painter: QPainter, cx: float, cy: float, size: float, theme,
               token: str = "textSecondary") -> None:
    painter.save()
    color = theme.color(token)
    painter.setPen(QPen(color, max(1.1, size * 0.075), Qt.SolidLine,
                        Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    width, height, fold = size * 0.62, size * 0.8, size * 0.2
    left, top = cx - width / 2, cy - height / 2
    path = QPainterPath()
    path.moveTo(left, top)
    path.lineTo(left + width - fold, top)
    path.lineTo(left + width, top + fold)
    path.lineTo(left + width, top + height)
    path.lineTo(left, top + height)
    path.closeSubpath()
    painter.drawPath(path)
    painter.drawLine(QPointF(left + width - fold, top),
                     QPointF(left + width - fold, top + fold))
    painter.drawLine(QPointF(left + width - fold, top + fold),
                     QPointF(left + width, top + fold))
    painter.drawLine(QPointF(left + width * 0.22, top + height * 0.62),
                     QPointF(left + width * 0.78, top + height * 0.62))
    painter.drawLine(QPointF(left + width * 0.22, top + height * 0.78),
                     QPointF(left + width * 0.62, top + height * 0.78))
    painter.restore()


def paint_drop(painter: QPainter, cx: float, cy: float, size: float, theme,
               token: str = "accent") -> None:
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color(token))
    drop = QPainterPath()
    drop.moveTo(cx, cy - size * 0.5)
    drop.cubicTo(cx + size * 0.42, cy - size * 0.06,
                 cx + size * 0.38, cy + size * 0.38, cx, cy + size * 0.38)
    drop.cubicTo(cx - size * 0.38, cy + size * 0.38,
                 cx - size * 0.42, cy - size * 0.06, cx, cy - size * 0.5)
    painter.drawPath(drop)
    painter.restore()


def paint_spark(painter: QPainter, cx: float, cy: float, size: float, theme,
                token: str = "accent") -> None:
    """A small four-point spark, the AI activity mark."""
    path = QPainterPath()
    outer, inner = size * 0.48, size * 0.26
    for index in range(8):
        angle = -math.pi / 2 + index * math.pi / 4
        radius = outer if index % 2 == 0 else inner
        point = QPointF(cx + radius * math.cos(angle),
                        cy + radius * math.sin(angle))
        if index == 0:
            path.moveTo(point)
        else:
            path.lineTo(point)
    path.closeSubpath()
    painter.save()
    painter.setPen(Qt.NoPen)
    painter.setBrush(theme.color(token))
    painter.drawPath(path)
    painter.restore()


def paint_tray(painter: QPainter, cx: float, cy: float, size: float, theme) -> None:
    painter.save()
    painter.setPen(QPen(theme.color("textTertiary"), max(1.2, size * 0.07),
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    tray = QPainterPath()
    tray.moveTo(cx - size * 0.42, cy - size * 0.24)
    tray.lineTo(cx - size * 0.2, cy - size * 0.24)
    tray.lineTo(cx - size * 0.1, cy - size * 0.1)
    tray.lineTo(cx + size * 0.42, cy - size * 0.1)
    tray.lineTo(cx + size * 0.32, cy + size * 0.28)
    tray.lineTo(cx - size * 0.32, cy + size * 0.28)
    tray.closeSubpath()
    painter.drawPath(tray)
    painter.restore()


def paint_plus(painter: QPainter, cx: float, cy: float, size: float, theme,
               token: str = "textSecondary") -> None:
    painter.save()
    painter.setPen(QPen(theme.color(token), max(1.2, size * 0.12),
                        Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(cx - size / 2, cy), QPointF(cx + size / 2, cy))
    painter.drawLine(QPointF(cx, cy - size / 2), QPointF(cx, cy + size / 2))
    painter.restore()


def paint_close(painter: QPainter, cx: float, cy: float, size: float, theme,
                token: str = "textTertiary") -> None:
    painter.save()
    painter.setPen(QPen(theme.color(token), max(1.0, size * 0.12),
                        Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(cx - size / 2, cy - size / 2),
                     QPointF(cx + size / 2, cy + size / 2))
    painter.drawLine(QPointF(cx + size / 2, cy - size / 2),
                     QPointF(cx - size / 2, cy + size / 2))
    painter.restore()


def paint_pencil(painter: QPainter, cx: float, cy: float, size: float, theme,
                 token: str = "textSecondary") -> None:
    painter.save()
    painter.setPen(QPen(theme.color(token), max(1.0, size * 0.1),
                        Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    painter.drawLine(QPointF(cx - size * 0.42, cy + size * 0.42),
                     QPointF(cx + size * 0.3, cy - size * 0.36))
    painter.drawLine(QPointF(cx - size * 0.42, cy + size * 0.42),
                     QPointF(cx - size * 0.24, cy + size * 0.48))
    painter.drawLine(QPointF(cx + size * 0.3, cy - size * 0.36),
                     QPointF(cx + size * 0.42, cy - size * 0.3))
    painter.drawLine(QPointF(cx + size * 0.28, cy - size * 0.26),
                     QPointF(cx - size * 0.2, cy + size * 0.26))
    painter.restore()


def paint_pin(painter: QPainter, cx: float, cy: float, size: float, theme,
              token: str = "accent") -> None:
    painter.save()
    color = theme.color(token)
    painter.setPen(Qt.NoPen)
    painter.setBrush(color)
    painter.drawEllipse(QPointF(cx, cy - size * 0.3), size * 0.2, size * 0.16)
    body = QPainterPath()
    body.moveTo(cx - size * 0.24, cy - size * 0.14)
    body.lineTo(cx + size * 0.24, cy - size * 0.14)
    body.lineTo(cx + size * 0.1, cy + size * 0.2)
    body.lineTo(cx - size * 0.1, cy + size * 0.2)
    body.closeSubpath()
    painter.drawPath(body)
    painter.setPen(QPen(color, max(1.0, size * 0.1), Qt.SolidLine, Qt.RoundCap))
    painter.drawLine(QPointF(cx, cy + size * 0.18),
                     QPointF(cx, cy + size * 0.46))
    painter.restore()


def paint_clipboard(painter: QPainter, cx: float, cy: float, size: float, theme,
                    token: str = "textTertiary") -> None:
    painter.save()
    color = theme.color(token)
    painter.setPen(QPen(color, max(1.0, size * 0.08), Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    body = QRectF(cx - size * 0.34, cy - size * 0.4, size * 0.68, size * 0.8)
    painter.drawRoundedRect(body, size * 0.1, size * 0.1)
    clip = QRectF(cx - size * 0.16, cy - size * 0.48, size * 0.32, size * 0.18)
    painter.drawRoundedRect(clip, size * 0.05, size * 0.05)
    painter.restore()


def paint_bell(painter: QPainter, cx: float, cy: float, size: float, theme,
               token: str = "textPrimary") -> None:
    painter.save()
    color = theme.color(token)
    painter.setPen(QPen(color, max(1.0, size * 0.1), Qt.SolidLine, Qt.RoundCap,
                        Qt.RoundJoin))
    painter.setBrush(Qt.NoBrush)
    bell = QPainterPath()
    bell.moveTo(cx - size * 0.34, cy + size * 0.18)
    bell.quadTo(cx - size * 0.22, cy + size * 0.02, cx - size * 0.22, cy - size * 0.14)
    bell.quadTo(cx - size * 0.2, cy - size * 0.38, cx, cy - size * 0.38)
    bell.quadTo(cx + size * 0.2, cy - size * 0.38, cx + size * 0.22, cy - size * 0.14)
    bell.quadTo(cx + size * 0.22, cy + size * 0.02, cx + size * 0.34, cy + size * 0.18)
    bell.closeSubpath()
    painter.drawPath(bell)
    painter.drawLine(QPointF(cx, cy - size * 0.45), QPointF(cx, cy - size * 0.38))
    painter.drawLine(QPointF(cx - size * 0.08, cy + size * 0.3),
                     QPointF(cx + size * 0.08, cy + size * 0.3))
    painter.restore()
