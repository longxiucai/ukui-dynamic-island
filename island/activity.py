"""Live turn state for Codex and Claude, read from their local session records.

Only accounting and turn events are read; reasoning text is never shown.
The newest record is tailed incrementally so an idle app costs one stat a poll.
"""
import json
import time
from datetime import datetime
from pathlib import Path

from PySide2.QtCore import QThread, Signal


ACTIVE = ("thinking", "working", "responding")
STALE_SECONDS = 15 * 60
CODEX_TOOLS = {
    "exec_command": "正在执行",
    "shell": "正在执行",
    "apply_patch": "正在改文件",
    "web_search": "正在搜索",
    "update_plan": "正在规划",
}
CLAUDE_TOOLS = {
    "Bash": "正在执行",
    "Edit": "正在改文件",
    "MultiEdit": "正在改文件",
    "Write": "正在改文件",
    "NotebookEdit": "正在改文件",
    "Read": "正在读取",
    "Grep": "正在搜索",
    "Glob": "正在搜索",
    "WebSearch": "正在搜索",
    "WebFetch": "正在搜索",
    "TodoWrite": "正在规划",
}


def _timestamp(value):
    if isinstance(value, (int, float)):
        return float(value) / 1000.0 if value > 10_000_000_000 else float(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _detail(text, limit=160):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


def empty(provider="Codex"):
    return {
        "provider": provider,
        "state": "idle",
        "label": "空闲",
        "detail": "",
        "active": False,
        "at": 0.0,
        "session": "",
        "turn": "",
        "model": "",
    }


def parse_codex(state, event, now):
    if not isinstance(event, dict):
        return
    kind = event.get("type")
    payload = event.get("payload")
    if not isinstance(payload, dict):
        return
    stamp = _timestamp(event.get("timestamp")) or now
    payload_type = payload.get("type")

    if kind == "session_meta":
        state["session"] = str(payload.get("id") or payload.get("session_id")
                               or state["session"])
        return
    if kind == "turn_context":
        state["model"] = str(payload.get("model") or state["model"])
        state["turn"] = str(payload.get("turn_id") or state["turn"])
        return
    if kind == "response_item":
        name = payload.get("name")
        if payload_type in ("function_call", "custom_tool_call") and name:
            state.update(state="working",
                         label=CODEX_TOOLS.get(name, "正在处理"), detail="",
                         active=True, at=stamp)
        elif payload_type == "reasoning":
            state.update(state="thinking", label="正在思考", detail="",
                         active=True, at=stamp)
        return
    if kind != "event_msg":
        return

    if payload_type == "task_started":
        state.update(state="working", label="开始处理", detail="",
                     active=True, at=stamp,
                     turn=str(payload.get("turn_id") or state["turn"]))
    elif payload_type == "user_message":
        state.update(state="thinking", label="收到任务", detail="",
                     active=True, at=stamp)
    elif payload_type == "agent_reasoning":
        state.update(state="thinking", label="正在思考", detail="",
                     active=True, at=stamp)
    elif payload_type == "agent_message":
        state.update(state="responding", label="正在回答",
                     detail=_detail(payload.get("message")),
                     active=True, at=stamp)
    elif payload_type == "patch_apply_end":
        state.update(state="working", label="正在改文件", detail="",
                     active=True, at=stamp)
    elif payload_type in ("exec_command_begin", "exec_command_end"):
        state.update(state="working", label="正在执行", detail="",
                     active=True, at=stamp)
    elif payload_type == "task_complete":
        state.update(state="completed", label="任务完成",
                     detail=_detail(payload.get("last_agent_message")),
                     active=False, at=stamp,
                     turn=str(payload.get("turn_id") or state["turn"]))
    elif payload_type == "turn_aborted":
        state.update(state="aborted", label="已中断", detail="",
                     active=False, at=stamp)


def parse_claude(state, event, now):
    """Best effort: Claude Code writes its records per streamed message."""
    if not isinstance(event, dict):
        return
    kind = event.get("type")
    message = event.get("message")
    message = message if isinstance(message, dict) else {}
    stamp = _timestamp(event.get("timestamp")) or now
    state["session"] = str(event.get("sessionId") or state["session"])
    state["model"] = str(message.get("model") or state["model"])
    content = message.get("content")
    blocks = [item for item in content if isinstance(item, dict)] \
        if isinstance(content, list) else []

    if kind == "user":
        if isinstance(content, str):
            state.update(state="thinking", label="收到任务", detail="",
                         active=True, at=stamp)
        return
    if kind == "assistant":
        text = [str(item.get("text") or "") for item in blocks
                if item.get("type") == "text"]
        tools = [item for item in blocks if item.get("type") == "tool_use"]
        if tools:
            name = tools[-1].get("name")
            state.update(state="working",
                         label=CLAUDE_TOOLS.get(name, "正在处理"), detail="",
                         active=True, at=stamp)
        elif text and any(item.strip() for item in text):
            state.update(state="responding", label="正在回答",
                         detail=_detail(text[-1]), active=True, at=stamp)
        elif any(item.get("type") == "thinking" for item in blocks):
            state.update(state="thinking", label="正在思考", detail="",
                         active=True, at=stamp)
        return
    if kind == "system" and event.get("subtype") == "turn_duration":
        state.update(state="completed", label="任务完成", detail="",
                     active=False, at=stamp)


class Activity(QThread):
    updated = Signal(dict)

    def __init__(self, home=None, interval=0.8, parent=None):
        super().__init__(parent)
        self.home = Path(home or Path.home())
        self.interval = interval
        self._path = None
        self._parser = None
        self._offset = 0
        self._state = empty()
        self._last = None

    def _sources(self):
        return (
            ("Codex", self.home / ".codex" / "sessions",
             "*/*/*/*.jsonl", parse_codex),
            ("Claude", self.home / ".claude" / "projects",
             "*/*.jsonl", parse_claude),
        )

    def _newest(self):
        live = []
        for provider, root, pattern, parser in self._sources():
            try:
                files = list(root.glob(pattern))
            except OSError:
                continue
            for path in files:
                try:
                    modified = path.stat().st_mtime
                except OSError:
                    continue
                if time.time() - modified <= 6 * 3600:
                    live.append((modified, provider, path, parser))
        if not live:
            return None
        _, provider, path, parser = max(live, key=lambda item: item[0])
        return provider, path, parser

    def _reset(self):
        self._state = empty()
        self._offset = 0
        self._path = None

    def _read(self, path, initial):
        try:
            size = path.stat().st_size
        except OSError:
            return
        start = max(0, size - 128_000) if initial else self._offset
        if size < start:
            self._state = empty(self._state["provider"])
            start = 0
        try:
            with open(path, "rb") as handle:
                handle.seek(start)
                data = handle.read()
        except OSError:
            return
        end = data.rfind(b"\n")
        if end < 0:
            return
        if initial and start:
            first = data.find(b"\n")
            data = data[first + 1:] if first >= 0 else b""
        else:
            data = data[:end + 1]
        self._offset = start + end + 1
        now = time.time()
        for line in data.splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            self._parser(self._state, event, now)
        if not self._state["session"]:
            self._state["session"] = path.stem

    def scan(self, now=None):
        now = now or time.time()
        newest = self._newest()
        if newest is None:
            self._reset()
            return self.result(now)
        provider, path, parser = newest
        if path != self._path:
            self._state = empty(provider)
            self._path = path
            self._parser = parser
            self._offset = 0
            self._read(path, True)
        else:
            self._read(path, False)
        return self.result(now)

    def result(self, now=None):
        now = now or time.time()
        state = dict(self._state)
        state["age"] = max(0.0, now - state["at"]) if state["at"] else None
        if state["active"] and state["age"] is not None \
                and state["age"] > STALE_SECONDS:
            state.update(state="idle", label="空闲", detail="", active=False)
        return state

    def run(self):
        while not self.isInterruptionRequested():
            result = self.scan()
            if self.isInterruptionRequested():
                break
            if result != self._last:
                self._last = dict(result)
                self.updated.emit(result)
            self.msleep(max(200, int(self.interval * 1000)))
