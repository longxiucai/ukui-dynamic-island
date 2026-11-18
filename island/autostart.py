"""~/.config/autostart entry, opt-in only."""
import os
import sys
from pathlib import Path

from island import APP_ID, APP_NAME


def _entry_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "autostart" / f"{APP_ID}.desktop"


def command() -> str:
    if getattr(sys, "frozen", False):
        return sys.executable
    return f"{sys.executable} -m island"


def enabled() -> bool:
    return _entry_path().exists()


def set_enabled(on: bool) -> None:
    path = _entry_path()
    if not on:
        path.unlink(missing_ok=True)
        return
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
