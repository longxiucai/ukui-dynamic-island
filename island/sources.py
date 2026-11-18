"""Slow reads live off the UI thread: system readings and network rates."""
import glob
import os
import subprocess
import time

from PySide2.QtCore import QThread, Signal


def read_battery():
    for path in sorted(glob.glob("/sys/class/power_supply/BAT*")):
        try:
            with open(f"{path}/capacity") as f:
                level = int(f.read().strip()) / 100.0
            with open(f"{path}/status") as f:
                status = f.read().strip()
        except (OSError, ValueError):
            continue
        return level, status == "Charging"
    return None, False


def _percent(text):
    for token in text.split():
        token = token.rstrip("]")
        if token.endswith("%"):
            try:
                return int(token[:-1]) / 100.0
            except ValueError:
                return None
    return None


def read_volume():
    try:
        out = subprocess.run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    level = _percent(out)
    if level is not None:
        return level
    try:
        sinks = subprocess.run(["pactl", "list", "sinks"], capture_output=True,
                               text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        sinks = ""
    for line in sinks.splitlines():
        if line.strip().startswith(("Volume:", "音量")):
            return _percent(line)
    if not sinks:
        try:
            out = subprocess.run(["amixer", "get", "Master"], capture_output=True,
                                 text=True, timeout=2).stdout
        except (OSError, subprocess.SubprocessError):
            return None
        for line in out.splitlines():
            if "[" in line and "%]" in line:
                return _percent(line)
    return None


def read_muted():
    try:
        out = subprocess.run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        out = ""
    if "yes" in out.lower():
        return True
    if "no" in out.lower():
        return False
    try:
        sinks = subprocess.run(["pactl", "list", "sinks"], capture_output=True,
                               text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    for line in sinks.splitlines():
        if line.strip().startswith(("Mute:", "静音")):
            return "yes" in line.lower() or "是" in line
    return None


def set_volume(level):
    percent = int(max(0.0, min(1.0, float(level))) * 100)
    try:
        done = subprocess.run(["pactl", "set-sink-volume", "@DEFAULT_SINK@",
                               f"{percent}%"], capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return percent / 100.0 if done.returncode == 0 else None


def set_muted(muted):
    try:
        done = subprocess.run(["pactl", "set-sink-mute", "@DEFAULT_SINK@",
                               "1" if muted else "0"], capture_output=True,
                              timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    return bool(muted) if done.returncode == 0 else None


def read_memory():
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                key, _, rest = line.partition(":")
                info[key] = int(rest.split()[0])
    except (OSError, ValueError, IndexError):
        return None
    total = info.get("MemTotal")
    available = info.get("MemAvailable")
    if not total or available is None:
        return None
    return 1.0 - available / total


def cpu_times(line):
    """(idle, total) tick counts from the first line of /proc/stat."""
    fields = [int(value) for value in line.split()[1:]]
    if len(fields) < 4:
        return None
    return fields[3] + (fields[4] if len(fields) > 4 else 0), sum(fields)


_PREV_CPU = None


def read_cpu():
    global _PREV_CPU
    try:
        with open("/proc/stat") as f:
            now = cpu_times(f.readline())
    except (OSError, ValueError, IndexError):
        return None
    previous, _PREV_CPU = _PREV_CPU, now
    if previous is None or now is None:
        return None
    idle = now[0] - previous[0]
    total = now[1] - previous[1]
    return None if total <= 0 else max(0.0, min(1.0, 1.0 - idle / total))


def default_interface():
    try:
        with open("/proc/net/route") as f:
            next(f)
            for line in f:
                fields = line.split()
                if len(fields) > 7 and fields[1] == "00000000" and fields[7] == "00000000":
                    return fields[0]
    except (OSError, StopIteration, IndexError):
        pass
    return None


def net_bytes():
    received = sent = 0
    names = [default_interface()]
    if names[0] is None:
        names = os.listdir("/sys/class/net")
    for name in names:
        if name == "lo":
            continue
        try:
            with open(f"/sys/class/net/{name}/statistics/rx_bytes") as f:
                received += int(f.read())
            with open(f"/sys/class/net/{name}/statistics/tx_bytes") as f:
                sent += int(f.read())
        except (OSError, ValueError):
            continue
    return received, sent


_PREV_NET = None


def read_net():
    """(down, up) bytes per second since the previous sample."""
    global _PREV_NET
    now = time.monotonic()
    received, sent = net_bytes()
    previous, _PREV_NET = _PREV_NET, (now, received, sent)
    if previous is None:
        return None, None
    elapsed = now - previous[0]
    if elapsed <= 0:
        return None, None
    down = max(0.0, (received - previous[1]) / elapsed)
    up = max(0.0, (sent - previous[2]) / elapsed)
    return down, up


def read_network():
    names = [default_interface()]
    if names[0] is None:
        try:
            names = [name for name in os.listdir("/sys/class/net") if name != "lo"]
        except OSError:
            return None
    for name in names:
        try:
            with open(f"/sys/class/net/{name}/operstate") as f:
                if f.read().strip() != "up":
                    continue
            carrier = f"/sys/class/net/{name}/carrier"
            if os.path.exists(carrier):
                with open(carrier) as f:
                    if f.read().strip() != "1":
                        continue
        except OSError:
            continue
        return True
    return False


def format_rate(value):
    if value is None:
        return "--"
    if value >= 1e6:
        return f"{value / 1e6:.1f}M"
    if value >= 1e3:
        return f"{value / 1e3:.0f}K"
    return f"{value:.0f}B"


def read_disk(path="/"):
    try:
        stat = os.statvfs(path)
    except OSError:
        return None
    total = stat.f_blocks * stat.f_frsize
    free = stat.f_bavail * stat.f_frsize
    return None if total <= 0 else 1.0 - free / total


def read_temperature():
    """Hottest plausible hwmon input; sensor scales differ, 1000 is the norm."""
    hottest = None
    for path in glob.glob("/sys/class/hwmon/hwmon*/temp*_input"):
        try:
            with open(path) as f:
                raw = int(f.read().strip())
        except (OSError, ValueError):
            continue
        value = raw / 1000.0 if raw > 200 else float(raw)
        if 0 < value < 120:
            hottest = value if hottest is None else max(hottest, value)
    return hottest


def read_gpu():
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    row = out.strip().splitlines()[0] if out.strip() else ""
    parts = [part.strip() for part in row.split(",")]
    if len(parts) != 3:
        return None
    try:
        used, total = int(parts[1]), int(parts[2])
        return {"util": int(parts[0]) / 100.0,
                "mem": None if total <= 0 else used / float(total)}
    except ValueError:
        return None


class Sampler(QThread):
    sampled = Signal(dict)

    def __init__(self, interval_ms: int = 2000, monitor_enabled=True,
                 parent=None):
        super().__init__(parent)
        self.interval_ms = interval_ms
        self.monitor_enabled = bool(monitor_enabled)

    def set_monitor_enabled(self, enabled):
        self.monitor_enabled = bool(enabled)

    def sample(self):
        data = {
            "battery": None,
            "charging": False,
            "volume": None,
            "muted": None,
            "memory": None,
            "cpu": None,
            "disk": None,
            "temperature": None,
            "gpu": None,
            "net_down": None,
            "net_up": None,
            "online": None,
        }
        level, charging = read_battery()
        data.update(battery=level, charging=charging,
                    volume=read_volume(), muted=read_muted())
        if self.monitor_enabled:
            down, up = read_net()
            data.update(memory=read_memory(), cpu=read_cpu(),
                        disk=read_disk(), temperature=read_temperature(),
                        gpu=read_gpu(), net_down=down, net_up=up,
                        online=read_network())
        return data

    def run(self):
        while not self.isInterruptionRequested():
            self.sampled.emit(self.sample())
            for _ in range(max(1, self.interval_ms // 100)):
                if self.isInterruptionRequested():
                    return
                self.msleep(100)
