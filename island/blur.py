"""KWin blur hint probe; UKUI may not advertise it, so callers fall back."""
import shutil
import subprocess


ATOM = "_KDE_NET_WM_BLUR_BEHIND_REGION"


def supported():
    if not shutil.which("xprop"):
        return False
    try:
        out = subprocess.run(["xprop", "-root", "_NET_SUPPORTED"],
                             capture_output=True, text=True, timeout=2).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return ATOM in out


def apply(winid, rect):
    """Set a blur region on the window; True only when xprop accepted it."""
    if not shutil.which("xprop"):
        return False
    x, y, width, height = (int(value) for value in rect)
    try:
        done = subprocess.run(
            ["xprop", "-id", str(winid), "-f", ATOM, "32c", "-set", ATOM,
             f"{x}, {y}, {width}, {height}"],
            capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def clear(winid):
    try:
        subprocess.run(["xprop", "-id", str(winid), "-remove", ATOM],
                       capture_output=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        pass
