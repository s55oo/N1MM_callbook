"""Enumerate VHFCtest4WIN's top-level window and every child control,
printing class name, control id, rectangle and current text.

Run it with VHFCtest4WIN open and a callsign (and locator) typed into
the entry fields but NOT logged. Paste me the output.
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

EnumWindows = user32.EnumWindows
EnumChildWindows = user32.EnumChildWindows
GetWindowTextW = user32.GetWindowTextW
GetClassNameW = user32.GetClassNameW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
GetDlgCtrlID = user32.GetDlgCtrlID
GetWindowRect = user32.GetWindowRect

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

WM_GETTEXT = 0x000D
WM_GETTEXTLENGTH = 0x000E


def text_of(hwnd):
    # try GetWindowText first, then WM_GETTEXT (works for more control types)
    n = GetWindowTextLengthW(hwnd)
    buf = ctypes.create_unicode_buffer(n + 1)
    GetWindowTextW(hwnd, buf, n + 1)
    if buf.value:
        return buf.value
    ln = user32.SendMessageW(hwnd, WM_GETTEXTLENGTH, 0, 0)
    buf = ctypes.create_unicode_buffer(ln + 1)
    user32.SendMessageW(hwnd, WM_GETTEXT, ln + 1, buf)
    return buf.value


def cls_of(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    GetClassNameW(hwnd, buf, 256)
    return buf.value


def rect_of(hwnd):
    r = wintypes.RECT()
    GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right - r.left, r.bottom - r.top)


def dump_children(parent, title):
    print("\n=== window: {!r}  class={}  hwnd={} ===".format(title, cls_of(parent), parent))
    rows = []

    @WNDENUMPROC
    def cb(hwnd, lparam):
        rows.append((rect_of(hwnd)[1], rect_of(hwnd)[0], hwnd))
        return True

    EnumChildWindows(parent, cb, 0)
    for _, _, hwnd in sorted(rows):
        x, y, w, h = rect_of(hwnd)
        vis = "vis" if IsWindowVisible(hwnd) else "hid"
        print("  id={:>6}  {:<20} {:>4},{:<4} {:>3}x{:<3} {}  text={!r}".format(
            GetDlgCtrlID(hwnd), cls_of(hwnd), x, y, w, h, vis, text_of(hwnd)[:60]))


tops = []


@WNDENUMPROC
def top_cb(hwnd, lparam):
    if not IsWindowVisible(hwnd):
        return True
    t = text_of(hwnd)
    c = cls_of(hwnd)
    if "vhfc" in t.lower() or "vhfc" in c.lower() or "reg1" in t.lower():
        tops.append((hwnd, t))
    return True


EnumWindows(top_cb, 0)

if not tops:
    print("No VHFCtest4WIN window found. Listing ALL visible top-level windows:")

    @WNDENUMPROC
    def all_cb(hwnd, lparam):
        if IsWindowVisible(hwnd):
            t = text_of(hwnd)
            if t.strip():
                print("  hwnd={} class={} text={!r}".format(hwnd, cls_of(hwnd), t[:70]))
        return True

    EnumWindows(all_cb, 0)
else:
    for hwnd, t in tops:
        dump_children(hwnd, t)
