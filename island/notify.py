"""Watch desktop notifications with dbus-monitor (no QtDBus in PySide2)."""
import os
import pty
import re
import select
import shutil
import subprocess
import time

from PySide2.QtCore import QThread, Signal


MONITOR = ("dbus-monitor", "--session",
           "type='method_call',interface='org.freedesktop.Notifications',"
           "member='Notify'")
STRING_RE = re.compile(r'^\s+string "(.*)"$')


class NotifyWatcher(QThread):
    notified = Signal(dict)
    failed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.proc = None

    def stop(self):
        self.requestInterruption()
        proc = self.proc
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass

    def run(self):
        if not shutil.which("dbus-monitor"):
            self.failed.emit("缺少 dbus-monitor")
            return
        try:
            master, slave = pty.openpty()
        except OSError as exc:
            self.failed.emit(str(exc))
            return
        try:
            self.proc = subprocess.Popen(
                MONITOR, stdout=slave, stderr=subprocess.DEVNULL)
        except OSError as exc:
            os.close(master)
            os.close(slave)
            self.failed.emit(str(exc))
            return
        os.close(slave)
        strings = []
        buffer = ""
        while not self.isInterruptionRequested():
            try:
                ready, _, _ = select.select([master], [], [], 0.5)
            except (OSError, ValueError):
                break
            if not ready:
                continue
            try:
                data = os.read(master, 4096)
            except OSError:
                break
            if not data:
                break
            buffer += data.decode("utf-8", "replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.rstrip("\r")
                if "member=Notify" in line:
                    strings = []
                    continue
                match = STRING_RE.match(line)
                if not match:
                    continue
                strings.append(match.group(1))
                if len(strings) >= 4:
                    app, _icon, summary, body = strings[:4]
                    self.notified.emit({
                        "app": app or "系统",
                        "summary": summary or "通知",
                        "body": body,
                        "at": time.strftime("%H:%M"),
                    })
                    strings = []
        try:
            os.close(master)
        except OSError:
            pass
        if self.proc is not None and self.proc.poll() is None:
            try:
                self.proc.terminate()
            except OSError:
                pass
        elif not self.isInterruptionRequested() and self.proc is not None:
            self.failed.emit(f"dbus-monitor 已退出（{self.proc.returncode}）")
