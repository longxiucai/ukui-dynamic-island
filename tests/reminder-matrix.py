"""Render reminder states to one PNG. Offscreen, no desktop needed.

    QT_QPA_PLATFORM=offscreen .build-venv/bin/python tests/reminder-matrix.py
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = tempfile.mkdtemp(prefix="island-reminders-")
os.environ["UKUI_ISLAND_CONFIG_DIR"] = tmp + "/config"
os.environ["UKUI_ISLAND_STATE_DIR"] = tmp + "/state"

from PySide2.QtCore import QRectF, Qt  # noqa: E402
from PySide2.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide2.QtWidgets import QApplication  # noqa: E402

from island import config, theme  # noqa: E402
from island.window import IslandWindow  # noqa: E402


def window():
    cfg = dict(config.DEFAULTS)
    cfg.update({"style": "notch", "theme": "classic"})
    win = IslandWindow(cfg, theme.load("classic"))
    win.set_data({"battery": 0.80, "charging": False, "volume": 0.55,
                  "memory": 0.36, "cpu": 0.21, "disk": 0.42,
                  "temperature": 48, "gpu": None, "net_down": 15_000,
                  "net_up": 7_000, "online": True,
                  "weather": {"temp": 15, "text": "多云", "place": "北京"}})
    return win


def focus_state(win, rest=False):
    if rest:
        win.focus = {"phase": "rest", "running": False,
                     "remaining": 5 * 60, "total": 5 * 60}
        win._focus_done = True
        win._enqueue_alert("focus", "专注结束 · 该休息了", "", "focus")
        return "focus"
    win.focus = {"phase": "focus", "running": True,
                 "remaining": 24 * 60 + 30, "total": 25 * 60}
    return "focus"


def set_mail(win):
    win.set_mail({"status": "ok", "error": "", "at": "12:30", "items": [
        {"sender": "GitHub", "subject": "[ukui-island] code 482913",
         "date": "12:20", "code": "482913", "preview": ""},
        {"sender": "王工", "subject": "本周评审", "date": "12:10",
         "code": "", "preview": "明天下午三点开会"}]})
    win._enqueue_alert("mail", "验证码邮件", "GitHub", "mail",
                       key=win._mail_key(win.mail["items"][0]))


def capture(win, page, detail=None):
    win.set_expanded(False, animate=False)
    win._apply_geometry(animate=False)
    compact = win.grab()
    win.set_page(page)
    if detail is not None:
        win._mail_detail = detail
    win.set_expanded(True, animate=False)
    win._apply_geometry(animate=False)
    expanded = win.grab()
    assert not compact.isNull() and not expanded.isNull()
    return compact, expanded


def main():
    app = QApplication([])
    rows = []

    win = window()
    page = focus_state(win)
    rows.append(("专注进行中", *capture(win, page)))
    win.close()

    win = window()
    page = focus_state(win, rest=True)
    rows.append(("专注结束", *capture(win, page)))
    win.close()

    win = window()
    win._water_pending = True
    win.productivity.water_ml = 1500
    win._enqueue_alert("water", "喝水时间到了", "补充 250 ml 水分", "water")
    rows.append(("喝水提醒", *capture(win, "water")))
    win.close()

    win = window()
    set_mail(win)
    rows.append(("验证码邮件", *capture(win, "mail")))
    win.close()

    win = window()
    set_mail(win)
    rows.append(("验证码详情", *capture(win, "mail", detail=0)))
    win.close()

    width, row_h = 1000, 200
    sheet = QImage(width, row_h * len(rows) + 16, QImage.Format_ARGB32)
    sheet.fill(QColor("#202430"))
    painter = QPainter(sheet)
    painter.setRenderHint(QPainter.Antialiasing)
    title_font = QFont("Noto Sans CJK SC", 10)
    body_font = QFont("Noto Sans CJK SC", 9)
    for index, (label, compact, expanded) in enumerate(rows):
        top = 8 + index * row_h
        painter.setFont(title_font)
        painter.setPen(QColor("#d8deeb"))
        painter.drawText(QRectF(16, top, 600, 22), Qt.AlignLeft | Qt.AlignVCenter,
                         label)
        painter.drawPixmap(70, top + 55, compact)
        painter.drawPixmap(520, top + 20, expanded)
        painter.setFont(body_font)
        painter.setPen(QColor("#9aa4b2"))
        painter.drawText(QRectF(70, top + 104, compact.width(), 20),
                         Qt.AlignHCenter | Qt.AlignTop, "收起")
        painter.drawText(QRectF(520, top + 172, expanded.width(), 20),
                         Qt.AlignHCenter | Qt.AlignTop, "展开")
    painter.end()

    out = ROOT / "screenshots" / "reminder-matrix.png"
    if not sheet.save(str(out)):
        print(f"FAIL: cannot save {out}")
        return 1
    print(f"{out} {sheet.width()}x{sheet.height()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
