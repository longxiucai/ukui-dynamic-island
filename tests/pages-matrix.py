"""Render the nine expanded pages to one PNG. Offscreen, no desktop needed.

    QT_QPA_PLATFORM=offscreen .build-venv/bin/python tests/pages-matrix.py
"""
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

tmp = tempfile.mkdtemp(prefix="island-pages-")
os.environ["UKUI_ISLAND_CONFIG_DIR"] = tmp + "/config"
os.environ["UKUI_ISLAND_STATE_DIR"] = tmp + "/state"

from PySide2.QtGui import QColor, QImage, QPainter  # noqa: E402
from PySide2.QtWidgets import QApplication  # noqa: E402

from island import __version__, config, theme  # noqa: E402
from island.window import PAGES, IslandWindow  # noqa: E402


def calendar_event(base, hour, summary):
    start = base.replace(hour=hour) + (
        timedelta(days=1) if hour < base.hour else timedelta())
    return {"summary": summary, "start": start,
            "end": start + timedelta(hours=1), "all_day": False, "place": ""}


def main():
    app = QApplication([])
    win = IslandWindow(dict(config.DEFAULTS), theme.load("classic"))
    now = int(time.time())
    base = datetime.now().replace(minute=0, second=0, microsecond=0)
    win.set_data({"battery": 0.82, "charging": False, "volume": 0.46,
                  "memory": 0.37, "cpu": 0.83, "disk": 0.62, "temperature": 54,
                  "gpu": None, "net_down": 1_240_000, "net_up": 320_000,
                  "online": True,
                  "weather": {"temp": 13, "text": "小雨", "place": "长沙"}})
    win.set_music({"title": "晴天", "artist": "周杰伦", "status": "Playing",
                   "position": 42, "length": 215, "can_seek": True,
                   "player": "org.mpris.MediaPlayer2.spotify",
                   "lyric": [(0.0, "故事的小黄花")]})
    win.productivity.add_todo("整理桌面")
    win.productivity.add_todo("写周报")
    win.productivity.add_todo("买牛奶")
    win.productivity.add_water(750)
    win.productivity.record_clip("剪贴板测试")
    win.productivity.add_shelf("/etc/hosts")
    win.set_mail({"status": "ok", "error": "", "at": "12:30", "items": [
        {"sender": "GitHub", "subject": "[ukui-island] code 482913",
         "date": "12:20", "code": "482913", "preview": ""},
        {"sender": "王工", "subject": "本周评审", "date": "12:10",
         "code": "", "preview": "明天下午三点开会"},
        {"sender": "设计组", "subject": "新版灵动岛评审", "date": "11:40",
         "code": "", "preview": "请查收附件"}]})
    win.set_calendar({"status": "ok", "error": "", "at": "12:30", "items": [
        calendar_event(base, 14, "产品评审 · 3F"),
        calendar_event(base, 16, "与客户对齐"),
        calendar_event(base, 19, "健身")]})
    win.set_quota({"providers": [
        {"id": "codex", "label": "Codex", "plan": "Free", "status": "ok",
         "error": "", "updated": now - 120,
         "metrics": [
             {"label": "30 天", "used": 0.74, "remaining": 0.26,
              "text": "26%", "kind": "percent", "reset": now + 86400,
              "reset_text": "12月3日 09:15 重置"},
             {"label": "5 小时", "used": 0.2, "remaining": 0.8,
              "text": "80%", "kind": "percent", "reset": None,
              "reset_text": "等待刷新"}],
         "usage": {"today": 1_240_000, "sessions": 3},
         "note": "本机官方配额快照"},
        {"id": "claude", "label": "Claude", "plan": "本地记录", "status": "ok",
         "error": "", "updated": now - 300,
         "metrics": [{"label": "今日 Token", "used": 0.0, "remaining": 1.0,
                      "text": "2.20M", "kind": "balance", "reset": None,
                      "reset_text": "本机用量"}],
         "usage": {"today": 2_200_000, "sessions": 4},
         "note": "未找到桌面版额度缓存"},
        {"id": "workbuddy", "label": "WorkBuddy", "plan": "个人版",
         "status": "ok", "error": "", "updated": now - 60,
         "metrics": [{"label": "套餐积分", "used": 0.36, "remaining": 0.64,
                      "text": "640/1000", "kind": "percent", "reset": None,
                      "reset_text": "2 个资源包"}],
         "usage": {"today": 360_000, "sessions": 2},
         "note": "官网积分"},
        {"id": "trae", "label": "Trae CN", "plan": "Pro", "status": "ok",
         "error": "", "updated": now - 600,
         "metrics": [{"label": "套餐积分", "used": 0.52, "remaining": 0.48,
                      "text": "480/1000", "kind": "percent", "reset": None,
                      "reset_text": "3 个权益包"}],
         "usage": {"today": 520_000, "sessions": 5},
         "note": "官方积分"}]})
    win.add_notification({"app": "微信", "summary": "在吗", "body": "",
                          "at": "12:28"})
    win.set_expanded(True, animate=False)
    win.grab()
    time.sleep(0.2)

    grabs = []
    for page, _ in PAGES:
        win.set_page(page)
        time.sleep(0.3)
        app.processEvents()
        grabs.append(win.grab())
    assert len(grabs) == 9 and all(not pix.isNull() for pix in grabs)

    cell_w, cell_h, gap = 452, 156, 16
    sheet = QImage(cell_w * 3 + gap * 2 + 16, cell_h * 3 + gap * 2 + 16,
                   QImage.Format_ARGB32)
    sheet.fill(QColor("#202430"))
    painter = QPainter(sheet)
    for index, pix in enumerate(grabs):
        painter.drawPixmap(8 + (index % 3) * (cell_w + gap),
                           8 + (index // 3) * (cell_h + gap), pix)
    painter.end()

    out = ROOT / "screenshots" / f"pages-{__version__}.png"
    if not sheet.save(str(out)):
        print(f"FAIL: cannot save {out}")
        return 1
    print(f"{out} {sheet.width()}x{sheet.height()}")
    win.close()
    win.deleteLater()
    return 0


if __name__ == "__main__":
    sys.exit(main())
