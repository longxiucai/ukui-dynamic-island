"""Small local productivity store: todos, water, clipboard and shelf paths."""
import hashlib
import json
import os
import tempfile
from datetime import date, datetime
from pathlib import Path

from island import config


MAX_TODOS = 100
MAX_CLIPS = 30
MAX_PINNED = 5
MAX_CLIP_CHARS = 20_000
MAX_SHELF = 20
# 剪贴图片：单张字节数和张数都设上限，免得天天截图把内存和临时目录撑爆
MAX_CLIP_BYTES = 12_000_000
MAX_CLIP_IMAGES = 6
WATER_GOAL = 2000
WATER_STEP = 250
WEEKDAY_TEXT = "一二三四五六日"
MEETING_FIELDS = (("code", 32), ("place", 60), ("link", 300))


def clean_meeting(value):
    """Keep only the invite details a todo can show, each length-capped."""
    raw = value if isinstance(value, dict) else {}
    out = {}
    for key, limit in MEETING_FIELDS:
        text = str(raw.get(key) or "").strip()
        if text:
            out[key] = text[:limit]
    return out


def repeat_days(value):
    if not isinstance(value, (list, tuple)):
        return []
    days = sorted({int(day) for day in value
                   if isinstance(day, int) and not isinstance(day, bool)
                   and 0 <= day <= 6})
    return days if len(days) < 7 else list(range(7))


def repeat_tag(days):
    days = tuple(repeat_days(days))
    if not days:
        return ""
    if days == tuple(range(7)):
        return "每天"
    if days == (0, 1, 2, 3, 4):
        return "工作日"
    if days == (5, 6):
        return "周末"
    return "周" + "".join(WEEKDAY_TEXT[day] for day in days)


class Productivity:
    def __init__(self, path=None, image_dir=None):
        self.path = Path(path) if path else config.state_dir() / "productivity.json"
        # 剪贴暂存和剪贴板同寿命：放 /tmp，重启后由系统清，不用我们自己扫。
        # 名字不能和 SingleInstance 的 /tmp 套接字撞上。
        self.image_dir = Path(image_dir) if image_dir else (
            Path(tempfile.gettempdir())
            / ("ukui-dynamic-island-clips-%d" % os.getuid()))
        self.load_error = ""
        self.todos = []
        self.water_date = ""
        self.water_ml = 0
        self.clips = []
        self.shelf = []
        self._clip_blobs = {}
        self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("root is not an object")
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError, TypeError) as exc:
            self.load_error = f"{self.path}: {type(exc).__name__}: {exc}"
            raw = {}
        for row in raw.get("todos", []):
            if isinstance(row, dict) and isinstance(row.get("text"), str):
                text = row["text"].strip()
                if text:
                    self.todos.append({
                        "text": text,
                        "done": bool(row.get("done")),
                        "repeat": repeat_days(row.get("repeat")),
                        "done_on": str(row.get("done_on") or ""),
                        "remind": str(row.get("remind") or ""),
                        "remind_on": str(row.get("remind_on") or ""),
                        "meeting": clean_meeting(row.get("meeting")),
                    })
        water = raw.get("water") or {}
        self.water_date = str(water.get("date") or "")
        try:
            self.water_ml = max(0, min(WATER_GOAL, int(water.get("ml") or 0)))
        except (TypeError, ValueError):
            self.water_ml = 0
        for row in raw.get("clips", []):
            if isinstance(row, dict) and isinstance(row.get("text"), str) and row["text"].strip():
                kind = str(row.get("kind") or "text")
                if kind != "text":
                    continue        # 图片只活在内存里，重启不假装还在
                self.clips.append({"text": row["text"],
                                   "at": str(row.get("at") or ""),
                                   "pinned": bool(row.get("pinned")),
                                   "kind": "text", "size": ""})
        self.clips = self.clips[:MAX_CLIPS]
        staging = str(self.image_dir) + os.sep
        for value in raw.get("shelf", []):
            if isinstance(value, str) and value and value not in self.shelf:
                if value.startswith(staging) and not os.path.exists(value):
                    continue    # /tmp 被清掉了，这张暂存卡片也就没了
                self.shelf.append(value)
        self.shelf = self.shelf[:MAX_SHELF]
        self._today()

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "todos": self.todos,
            "water": {"date": self.water_date, "ml": self.water_ml},
            "clips": self.clips,
            "shelf": self.shelf,
        }
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".productivity-",
                                   suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def _today(self):
        today = date.today().isoformat()
        if self.water_date != today:
            self.water_date = today
            self.water_ml = 0

    def add_todo(self, text, repeat=None, remind="", remind_on="", meeting=None):
        text = str(text or "").strip()[:200]
        if not text:
            return False
        self.todos.insert(0, {"text": text, "done": False,
                              "repeat": repeat_days(repeat), "done_on": "",
                              "remind": str(remind or ""),
                              "remind_on": str(remind_on or ""),
                              "meeting": clean_meeting(meeting)})
        self.todos = self.todos[:MAX_TODOS]
        self._save()
        return True

    def update_todo(self, index, text, repeat=None, remind=""):
        text = str(text or "").strip()[:200]
        if not text or not 0 <= index < len(self.todos):
            return False
        item = self.todos[index]
        done = self.todo_done(item)
        item["text"] = text
        item["repeat"] = repeat_days(repeat)
        item["remind"] = str(remind or "")
        item["done"] = bool(done and not item["repeat"])
        today = date.today()
        item["done_on"] = (today.isoformat() if done and item["repeat"]
                           and today.weekday() in item["repeat"] else "")
        self._save()
        return True

    def todo_done(self, item, day=None):
        day = day or date.today()
        if item.get("repeat"):
            return item.get("done_on") == day.isoformat()
        return bool(item.get("done"))

    def todo_due(self, item, day=None):
        day = day or date.today()
        remind_on = item.get("remind_on")
        if remind_on and not item.get("repeat"):
            return remind_on == day.isoformat()
        repeat = item.get("repeat") or []
        return not repeat or day.weekday() in repeat

    def display_order(self, day=None):
        day = day or date.today()

        def key(index):
            item = self.todos[index]
            due = self.todo_due(item, day)
            done = self.todo_done(item, day)
            return (0 if due and not done else 1 if due else 2, index)

        return sorted(range(len(self.todos)), key=key)

    def progress(self, day=None):
        day = day or date.today()
        due = [item for item in self.todos if self.todo_due(item, day)]
        return sum(1 for item in due if self.todo_done(item, day)), len(due)

    def toggle_todo(self, index, day=None):
        day = day or date.today()
        if 0 <= index < len(self.todos):
            item = self.todos[index]
            if item.get("repeat"):
                if not self.todo_due(item, day):
                    return False
                item["done_on"] = "" if item.get("done_on") == day.isoformat() \
                    else day.isoformat()
            else:
                item["done"] = not item["done"]
            self._save()
            return True
        return False

    def remove_todo(self, index):
        if 0 <= index < len(self.todos):
            self.todos.pop(index)
            self._save()
            return True
        return False

    def clear_done_todos(self, day=None):
        day = day or date.today()
        kept = []
        changed = False
        for item in self.todos:
            if not self.todo_done(item, day):
                kept.append(item)
            elif item.get("repeat"):
                item["done_on"] = ""
                item["done"] = False
                kept.append(item)
                changed = True
            else:
                changed = True
        if changed:
            self.todos = kept
            self._save()

    def water_percent(self):
        self._today()
        return min(1.0, self.water_ml / float(WATER_GOAL))

    def add_water(self, amount=WATER_STEP):
        self._today()
        value = max(0, min(WATER_GOAL, self.water_ml + int(amount)))
        if value == self.water_ml:
            return False
        self.water_ml = value
        self._save()
        return True

    def undo_water(self, amount=WATER_STEP):
        return self.add_water(-min(int(amount), self.water_ml))

    def record_clip(self, text, at=None):
        text = str(text or "")
        if not text.strip() or len(text) > MAX_CLIP_CHARS:
            return False
        if self.clips and self.clips[0]["text"] == text:
            return False
        pinned = False
        same = [item for item in self.clips if item["text"] == text]
        for item in same:
            pinned = pinned or bool(item.get("pinned"))
            self._drop_image(item)      # 图片标题可能正好等于这段文字
        self.clips = [item for item in self.clips if item["text"] != text]
        self.clips.insert(0, {"text": text,
                              "at": at or datetime.now().strftime("%H:%M"),
                              "pinned": pinned, "kind": "text",
                              "size": ""})
        for item in self.clips[MAX_CLIPS:]:
            self._drop_image(item)
        self.clips = self.clips[:MAX_CLIPS]
        self._save()
        return True

    def record_clip_image(self, blob, width, height, at=None):
        """剪贴板图片进历史：只在内存里留 PNG 字节，不默认写盘。

        截图天天有，全部落盘会把状态目录塞满；只有"上架"才存成文件。
        """
        if not blob or len(blob) > MAX_CLIP_BYTES or width <= 0 or height <= 0:
            return False
        key = hashlib.sha256(blob).hexdigest()[:16]
        size = "%dx%d" % (int(width), int(height))
        if self.clips and self.clips[0].get("key") == key:
            return False
        kept = next((item for item in self.clips if item.get("key") == key),
                    None)
        if kept:
            self.clips.remove(kept)
            kept["at"] = at or datetime.now().strftime("%H:%M")
        else:
            kept = {"text": "图片 " + size,
                    "at": at or datetime.now().strftime("%H:%M"),
                    "pinned": False, "kind": "image", "key": key, "size": size}
        self.clips.insert(0, kept)
        self._clip_blobs[key] = blob
        stale = self.clips[MAX_CLIPS:]
        self.clips = self.clips[:MAX_CLIPS]
        for item in stale:
            self._drop_image(item)
        for item in [row for row in self.clips
                     if row.get("kind") == "image"][MAX_CLIP_IMAGES:]:
            self._drop_image(item)
            self.clips.remove(item)
        self._save()
        return True

    def clip_blob(self, key):
        """图片条目的 PNG 字节；重启后内存清空就没有了。"""
        return self._clip_blobs.get(key)

    def clip_to_shelf(self, item):
        """把剪贴图片存成 png 并放进取物架，返回该路径；失败返回 ""。"""
        if not item or item.get("kind") != "image":
            return ""
        blob = self._clip_blobs.get(item.get("key") or "")
        if not blob:
            return ""
        try:
            self.image_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            if self.image_dir.stat().st_uid != os.getuid():  # 别人抢先占了这个名字
                return ""
            os.chmod(self.image_dir, 0o700)
            path = self.image_dir / (item["key"] + ".png")
            if not path.exists():
                fd, tmp = tempfile.mkstemp(dir=str(self.image_dir),
                                           suffix=".png")
                os.close(fd)
                try:
                    Path(tmp).write_bytes(blob)
                    os.chmod(tmp, 0o600)
                    os.replace(tmp, path)
                finally:
                    if os.path.exists(tmp):
                        os.unlink(tmp)
        except OSError:
            return ""
        self.add_shelf(str(path))
        return str(path)

    def _drop_image(self, item):
        """图片条目被挤掉/删除时回收内存字节；已上架的文件留给置物架。"""
        self._clip_blobs.pop(item.get("key") or "", None)

    def _drop_staging(self, path):
        """下架：剪贴图片只是我们自己暂存的副本，卡片没了就该删掉。

        只认我们自己的暂存目录，用户拖进置物架的文件永远不碰。
        """
        if not path or not str(path).startswith(str(self.image_dir) + os.sep):
            return
        try:
            os.unlink(path)
        except OSError:
            pass

    def remove_clip(self, index):
        if 0 <= index < len(self.clips):
            self._drop_image(self.clips[index])
            self.clips.pop(index)
            self._save()
            return True
        return False

    def clear_clips(self):
        kept = [item for item in self.clips if item.get("pinned")]
        if len(kept) != len(self.clips):
            for item in self.clips:
                if item not in kept:
                    self._drop_image(item)
            self.clips = kept
            self._save()

    def toggle_pin(self, index):
        if not 0 <= index < len(self.clips):
            return False
        item = self.clips[index]
        if not item.get("pinned"):
            if sum(1 for clip in self.clips if clip.get("pinned")) >= MAX_PINNED:
                return False
            item["pinned"] = True
            self.clips.remove(item)
            self.clips.insert(0, item)
        else:
            item["pinned"] = False
        self._save()
        return True

    def add_shelf(self, path):
        value = str(Path(path).expanduser())
        if not value or value in self.shelf or not Path(value).exists():
            return False
        self.shelf.insert(0, value)
        for dropped in self.shelf[MAX_SHELF:]:
            self._drop_staging(dropped)   # 被挤掉的卡片别留下没人引用的暂存
        self.shelf = self.shelf[:MAX_SHELF]
        self._save()
        return True

    def remove_shelf(self, index):
        if 0 <= index < len(self.shelf):
            path = self.shelf.pop(index)
            self._drop_staging(path)
            self._save()
            return True
        return False

    def clear_shelf(self):
        if self.shelf:
            for path in self.shelf:
                self._drop_staging(path)
            self.shelf = []
            self._save()
