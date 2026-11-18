"""Small local productivity store: todos, water, clipboard and shelf paths."""
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
WATER_GOAL = 2000
WATER_STEP = 250
WEEKDAY_TEXT = "一二三四五六日"


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
    def __init__(self, path=None):
        self.path = Path(path) if path else config.state_dir() / "productivity.json"
        self.todos = []
        self.water_date = ""
        self.water_ml = 0
        self.clips = []
        self.shelf = []
        self._load()

    def _load(self):
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
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
                    })
        water = raw.get("water") or {}
        self.water_date = str(water.get("date") or "")
        try:
            self.water_ml = max(0, min(WATER_GOAL, int(water.get("ml") or 0)))
        except (TypeError, ValueError):
            self.water_ml = 0
        for row in raw.get("clips", []):
            if isinstance(row, dict) and isinstance(row.get("text"), str) and row["text"].strip():
                self.clips.append({"text": row["text"],
                                   "at": str(row.get("at") or ""),
                                   "pinned": bool(row.get("pinned"))})
        self.clips = self.clips[:MAX_CLIPS]
        for value in raw.get("shelf", []):
            if isinstance(value, str) and value and value not in self.shelf:
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

    def add_todo(self, text, repeat=None, remind=""):
        text = str(text or "").strip()[:200]
        if not text:
            return False
        self.todos.insert(0, {"text": text, "done": False,
                              "repeat": repeat_days(repeat), "done_on": "",
                              "remind": str(remind or "")})
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
        for item in self.clips:
            if item["text"] == text:
                pinned = bool(item.get("pinned"))
                break
        self.clips = [item for item in self.clips if item["text"] != text]
        self.clips.insert(0, {"text": text,
                              "at": at or datetime.now().strftime("%H:%M"),
                              "pinned": pinned})
        self.clips = self.clips[:MAX_CLIPS]
        self._save()
        return True

    def remove_clip(self, index):
        if 0 <= index < len(self.clips):
            self.clips.pop(index)
            self._save()
            return True
        return False

    def clear_clips(self):
        kept = [item for item in self.clips if item.get("pinned")]
        if len(kept) != len(self.clips):
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
        self.shelf = self.shelf[:MAX_SHELF]
        self._save()
        return True

    def remove_shelf(self, index):
        if 0 <= index < len(self.shelf):
            self.shelf.pop(index)
            self._save()
            return True
        return False

    def clear_shelf(self):
        if self.shelf:
            self.shelf = []
            self._save()
