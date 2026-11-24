"""~/.config/autostart entry, opt-in only, self-repairing for the build that runs."""
import os
import shlex
import sys
from pathlib import Path

from island import APP_ID, APP_NAME


def _entry_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{APP_ID}.desktop"


def command() -> str:
    if getattr(sys, "frozen", False):
        # Launching through a symlink (/usr/bin, ~/.local/bin) must still record
        # the real binary, so the entry survives that link being replaced.
        return str(Path(sys.executable).resolve())
    # Autostart runs from $HOME, so `-m island` cannot find the source tree;
    # run.py resolves its own directory and works from any cwd.
    entry = Path(__file__).resolve().parent.parent / "run.py"
    return f"{sys.executable} {entry}"


def enabled() -> bool:
    return _entry_path().exists()


def _write() -> None:
    path = _entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={APP_NAME}\n"
        f"Exec={command()}\n"
        "Terminal=false\n"
        "X-GNOME-Autostart-enabled=true\n",
        encoding="utf-8",
    )
    os.chmod(path, 0o644)


def set_enabled(on: bool) -> None:
    if on:
        _write()
        return
    _entry_path().unlink(missing_ok=True)


def _launchable(exec_line: str) -> bool:
    """Whether UKUI could still run this Exec from its own $HOME cwd."""
    try:
        parts = shlex.split(exec_line)
    except ValueError:
        return False
    if not parts:
        return False
    if not os.path.isfile(parts[0]) or not os.access(parts[0], os.X_OK):
        return False
    for arg in parts[1:]:
        # `-m island` needs the package on sys.path, which the autostarter's
        # $HOME cwd never provides; an argument that is not a readable file is
        # just as dead.
        if arg.startswith("-") or not Path(arg).is_file():
            return False
    return True


def ensure() -> bool:
    """Point an existing, dead autostart entry at the running build.

    Never creates an entry: autostart stays opt-in.

    UKUI starts the entry from $HOME, so a moved checkout, an uninstalled deb,
    or an older release that wrote `-m island` boots silently to nothing. The
    first launch fixes it. A working Exec is left alone, so running one build
    for a quick test never steals the entry from the build the user picked.
    """
    try:
        text = _entry_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    if not text.strip():
        return False
    for line in text.splitlines():
        if line.startswith("Exec=") and _launchable(line[5:]):
            return False
    if not _launchable(command()):
        return False
    _write()
    return True
