"""X11 bits Qt5 does not expose: input shapes, EWMH keep-above, show-desktop."""
import ctypes
import ctypes.util

SHAPE_INPUT, SHAPE_SET = 2, 0
CLIENT_MESSAGE, SUBSTRUCTURE = 33, 0x00180000
STATE_ADD = 1
ICONIC_STATE = 3


class _ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong),
                ("send_event", ctypes.c_int), ("display", ctypes.c_void_p),
                ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("data", ctypes.c_long * 5)]


class _Event(ctypes.Union):
    _fields_ = [("cm", _ClientMessage), ("pad", ctypes.c_long * 24)]


def _run(callback):
    try:
        lib = ctypes.util.find_library("X11")
        if not lib:
            return False
        x11 = ctypes.CDLL(lib)
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XFlush.argtypes = [ctypes.c_void_p]
        dpy = x11.XOpenDisplay(None)
        if not dpy:
            return False
        try:
            return callback(x11, dpy)
        finally:
            x11.XCloseDisplay(dpy)
    except (OSError, AttributeError):
        return False


def clear_input_shape(winid):
    """Drop the leftover input region so it follows the window again."""
    def apply(x11, dpy):
        lib = ctypes.util.find_library("Xext")
        if not lib:
            return False
        xext = ctypes.CDLL(lib)
        xext.XShapeCombineMask.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_ulong, ctypes.c_int]
        xext.XShapeCombineMask.restype = None
        xext.XShapeCombineMask(dpy, winid, SHAPE_INPUT, 0, 0, 0, SHAPE_SET)
        x11.XFlush(dpy)
        return True
    return _run(apply)


def drop_input_region(winid):
    """Pass input through: set the input region to no rectangles at all.

    Unlike Qt.WindowTransparentForInput this does not recreate the native
    window, so later resizes still reach the X server.
    """
    def apply(x11, dpy):
        lib = ctypes.util.find_library("Xext")
        if not lib:
            return False
        xext = ctypes.CDLL(lib)
        xext.XShapeCombineRectangles.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
            ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int,
            ctypes.c_int]
        xext.XShapeCombineRectangles.restype = None
        xext.XShapeCombineRectangles(dpy, winid, SHAPE_INPUT, 0, 0, None, 0,
                                     SHAPE_SET, 0)
        x11.XFlush(dpy)
        return True
    return _run(apply)


def keep_above(winid):
    """Re-assert _NET_WM_STATE_ABOVE after KWin has dropped it."""
    def apply(x11, dpy):
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                   ctypes.c_long, ctypes.c_void_p]
        state = x11.XInternAtom(dpy, b"_NET_WM_STATE", False)
        above = x11.XInternAtom(dpy, b"_NET_WM_STATE_ABOVE", False)
        event = _Event()
        event.cm.type = CLIENT_MESSAGE
        event.cm.send_event = 1
        event.cm.display = dpy
        event.cm.window = winid
        event.cm.message_type = state
        event.cm.format = 32
        event.cm.data[0] = STATE_ADD
        event.cm.data[1] = above
        event.cm.data[3] = 1
        x11.XSendEvent(dpy, x11.XDefaultRootWindow(dpy), False, SUBSTRUCTURE,
                       ctypes.byref(event))
        x11.XFlush(dpy)
        return True
    return _run(apply)


def set_window_type(winid, dock):
    """Switch between dock and Qt's utility type for show-desktop."""
    def apply(x11, dpy):
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XChangeProperty.argtypes = [
            ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong,
            ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_int]
        x11.XChangeProperty.restype = ctypes.c_int
        names = ((b"_NET_WM_WINDOW_TYPE_DOCK",) if dock else
                 (b"_NET_WM_WINDOW_TYPE_UTILITY",
                  b"_KDE_NET_WM_WINDOW_TYPE_OVERRIDE",
                  b"_NET_WM_WINDOW_TYPE_NORMAL"))
        prop = x11.XInternAtom(dpy, b"_NET_WM_WINDOW_TYPE", False)
        value = (ctypes.c_ulong * len(names))(
            *(x11.XInternAtom(dpy, name, False) for name in names))
        x11.XChangeProperty(dpy, winid, prop, 4, 32, 0,
                            value, len(names))
        x11.XFlush(dpy)
        return True
    return _run(apply)


def showing_desktop():
    """True while KWin's show-desktop/peek is active."""
    def apply(x11, dpy):
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        return bool(_read_first(x11, dpy, x11.XDefaultRootWindow(dpy),
                                b"_NET_SHOWING_DESKTOP"))
    return _run(apply)


def minimized(winid):
    """True when the WM keeps the window in Iconic state.

    Qt 的 isMinimized() 不能用：showNormal() 一调用它就翻回 False，而 KWin
    那边还是 Iconic，岛照样不出现，恢复分支也就再也不跑第二次。
    """
    def apply(x11, dpy):
        return _read_first(x11, dpy, winid, b"WM_STATE") == ICONIC_STATE
    return _run(apply)


def active_window():
    """The window the WM currently gives keyboard focus to, or 0."""
    def apply(x11, dpy):
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        return _read_first(x11, dpy, x11.XDefaultRootWindow(dpy),
                           b"_NET_ACTIVE_WINDOW") or 0
    return _run(apply)


def activate(winid):
    """Ask the WM to un-hide and raise us via _NET_ACTIVE_WINDOW.

    showNormal()、XMapWindow、去掉 _NET_WM_STATE_HIDDEN 都实测救不回被
    KWin 最小化的窗口，只有这个请求有效。
    """
    def apply(x11, dpy):
        x11.XInternAtom.restype = ctypes.c_ulong
        x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
        x11.XDefaultRootWindow.restype = ctypes.c_ulong
        x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        x11.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int,
                                   ctypes.c_long, ctypes.c_void_p]
        event = _Event()
        event.cm.type = CLIENT_MESSAGE
        event.cm.send_event = 1
        event.cm.display = dpy
        event.cm.window = winid
        event.cm.message_type = x11.XInternAtom(dpy, b"_NET_ACTIVE_WINDOW", False)
        event.cm.format = 32
        event.cm.data[0] = 2  # source: not the user, KWin may still refuse
        x11.XSendEvent(dpy, x11.XDefaultRootWindow(dpy), False, SUBSTRUCTURE,
                       ctypes.byref(event))
        x11.XFlush(dpy)
        return True
    return _run(apply)


def _read_first(x11, dpy, window, name):
    """First long of a window property, or None when it is missing."""
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XGetWindowProperty.restype = ctypes.c_int
    x11.XGetWindowProperty.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
        ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
        ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
        ctypes.POINTER(ctypes.POINTER(ctypes.c_ulong))]
    x11.XFree.argtypes = [ctypes.c_void_p]
    prop = x11.XInternAtom(dpy, name, False)
    kind, fmt = ctypes.c_ulong(), ctypes.c_int()
    count, after = ctypes.c_ulong(), ctypes.c_ulong()
    data = ctypes.POINTER(ctypes.c_ulong)()
    status = x11.XGetWindowProperty(
        dpy, window, prop, 0, 1, False, 0,
        ctypes.byref(kind), ctypes.byref(fmt), ctypes.byref(count),
        ctypes.byref(after), ctypes.byref(data))
    if status != 0 or not data:
        return None
    try:
        return data[0] if count.value else None
    finally:
        x11.XFree(data)


def remap(winid):
    """Ask the WM to map again after show-desktop unmapped the window."""
    def apply(x11, dpy):
        x11.XMapWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XMapWindow(dpy, winid)
        x11.XFlush(dpy)
        return True
    return _run(apply)
