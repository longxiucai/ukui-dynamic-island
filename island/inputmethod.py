"""Give the bundled Qt a bridge to the desktop input method.

The app ships its own Qt, and PySide2 only carries the ibus and compose input
context plugins. Kylin/UKUI types through fcitx, so the bundled Qt finds no
bridge: Ctrl+Space switches nothing and every text field stays in English,
including the city box in settings. The distro's Qt5 plugin loads fine into
our Qt, so link that one file into a plugin directory of our own. Pointing Qt
at the whole system plugin tree is not an option: its older xcb platform
plugin would be preferred over ours and abort startup.
"""
import os
import platform
from pathlib import Path

CATEGORY = "platforminputcontexts"
SYSTEM_ROOTS = ("/usr/lib", "/usr/lib64", "/lib", "/usr/local/lib")


def plugin_dir():
    """Where the Qt we run on looks for input method plugins."""
    from PySide2.QtCore import QLibraryInfo
    return Path(QLibraryInfo.location(QLibraryInfo.PluginsPath)) / CATEGORY


def system_dirs():
    """Input method plugin directories the distribution ships."""
    out = []
    for base in SYSTEM_ROOTS:
        for candidate in (_multiarch_first(base)
                          + [Path(base) / "qt5" / "plugins"]):
            leaf = candidate / CATEGORY
            if leaf.is_dir():
                out.append(leaf)
    return out


def _multiarch_first(base):
    """Multiarch plugin roots, this machine's own first.

    A plain sort finds /usr/lib/i386-linux-gnu before x86_64 on a mixed
    install, and Qt cannot load a plugin of another architecture.
    """
    machine = platform.machine()
    found = sorted(Path(base).glob("*/qt5/plugins"))
    return ([p for p in found if machine in p.name]
            + [p for p in found if machine not in p.name])


def plugin_for(directory, module):
    """The plugin in `directory` that Qt registers as `module`, if any.

    Qt names these lib<module>platforminputcontextplugin.so, so compare that
    part exactly: a substring match would let fcitx5 answer for fcitx, and Qt
    would load a bridge pointed at a daemon that is not running.
    """
    suffix = "platforminputcontextplugin.so"
    try:
        names = sorted(os.listdir(str(directory)))
    except OSError:
        return None
    for name in names:
        stem = name[3:] if name.startswith("lib") else name
        if stem.endswith(suffix) and stem[:-len(suffix)] == module.lower():
            return Path(directory) / name
    return None


def ensure(log=lambda message: None):
    """Expose a system plugin for $QT_IM_MODULE to our Qt; return that path.

    Must run before QApplication exists: the xcb plugin picks the input
    method bridge while the platform integration starts up.
    """
    module = os.environ.get("QT_IM_MODULE", "").strip()
    if not module or plugin_for(plugin_dir(), module):
        return None
    source = next((found for found in (plugin_for(leaf, module)
                                       for leaf in system_dirs()) if found),
                  None)
    if source is None:
        log(f"input method: no {module} plugin for Qt on this system")
        return None
    from island import config
    root = Path(config.state_dir()) / "qt-plugins"
    category = root / CATEGORY
    link = category / source.name
    try:
        if category.is_symlink():
            # Stale bridge from an older version: a link to the whole system
            # directory. Unlink writes through it and would delete the real
            # plugin, so drop the link first (this cannot remove its target).
            category.unlink()
        category.mkdir(parents=True, exist_ok=True)
        if not link.is_symlink() or os.readlink(str(link)) != str(source):
            if link.exists() or link.is_symlink():
                link.unlink()
            link.symlink_to(str(source))
    except OSError as exc:
        log(f"input method: {source} not usable ({exc})")
        return None
    from PySide2.QtCore import QCoreApplication
    QCoreApplication.addLibraryPath(str(root))
    log(f"input method: {module} bridge from {source}")
    return str(link)
