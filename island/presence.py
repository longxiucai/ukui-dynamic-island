"""Hide while a fullscreen window is active, via EWMH properties."""
import shutil
import subprocess

from PySide2.QtCore import QThread, Signal


def _xprop(args):
    try:
        return subprocess.run(["xprop", *args], capture_output=True, text=True,
                              timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def active_fullscreen():
    if not shutil.which("xprop"):
        return False
    active = _xprop(["-root", "_NET_ACTIVE_WINDOW"])
    window = ""
    if "#" in active:
        window = active.split("#", 1)[1].strip().split()[0]
    if not window or window in ("0x0", "0"):
        return False
    state = _xprop(["-id", window, "_NET_WM_STATE"])
    if "_NET_WM_STATE_FULLSCREEN" not in state:
        return False
    kind = _xprop(["-id", window, "_NET_WM_WINDOW_TYPE"])
    return "DESKTOP" not in kind and "DOCK" not in kind


class Presence(QThread):
    fullscreen = Signal(bool)

    def __init__(self, interval=2.0, parent=None):
        super().__init__(parent)
        self.interval = interval
        self._last = None

    def run(self):
        while not self.isInterruptionRequested():
            value = active_fullscreen()
            if value != self._last:
                self._last = value
                self.fullscreen.emit(value)
            for _ in range(int(self.interval * 10)):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)
