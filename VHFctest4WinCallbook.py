# SPDX-License-Identifier: Unlicense
"""VHFCtest4WIN pre-log locator check.

The side-by-side locator lookup of ``n1mm_VHFcallbook`` (QRZCQ.com,
HamQTH.com and the public QRZ.com page, shown next to each other and
turning green when they agree) - but driven by **VHFCtest4WIN** instead of
N1MM Logger+.

VHFCtest4WIN (S52AA's VHF contest logger) broadcasts the callsign in its
entry field on its multi-op sharing port (UDP **6767**) as the operator
types it. This app reads that broadcast, so the locator lookup runs
*while the callsign is being entered* - before the QSO is logged - and a
wrong QRA locator shows up while it can still be fixed. Plain
``n1mm_VHFcallbook`` only reacts once a contact is actually logged.

**Administrator / UAC:** VHFCtest4WIN keeps UDP 6767 open with an
exclusive lock, so the only way to read the broadcast while it is running
is a Windows raw capture socket, which needs elevation. When VHFCtest4WIN
is already running this app therefore **relaunches itself elevated** - one
UAC prompt, click *Yes*. If you decline it still opens, and the window
tells you what to do. (No prompt when VHFCtest4WIN is not up yet, or is on
another PC on the multi-op network - an ordinary listener is used then.)

Same optional paid QRZ.com XML slot as the other apps (set
``qrz_username`` / ``qrz_password`` in ``VHFctest4WinCallbook.cfg``;
needs a QRZ XML subscription). Lookups are cached in
``VHFctest4WinCallbook_cache.json``.

Made by S55OO with AI assistance.

Version: 1.1

Usage:
    python VHFctest4WinCallbook.py [--config VHFctest4WinCallbook.cfg]
"""

__version__ = "1.1"

import ctypes
import os
import socket
import sys

import n1mm_callbook as cb
import n1mm_VHFcallbook as vhf

V4W_PORT = 6767


def _port_bindable(port):
    """True when an ordinary UDP listener can be opened on *port* - i.e.
    VHFCtest4WIN is not currently holding it and no elevation is needed."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def _is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return True  # not Windows / can't tell - don't attempt to elevate


def _relaunch_elevated():
    """Start an elevated copy of this app (one UAC prompt). Returns True if
    the elevated process is launching and this one should exit, False to
    keep running unprivileged (the window then shows a hint)."""
    if getattr(sys, "frozen", False):
        target, params = sys.executable, "--elevated"
    else:
        target = sys.executable
        params = '"{}" --elevated'.format(os.path.abspath(sys.argv[0]))
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", target, params, None, 1
        )
    except (AttributeError, OSError):
        return False
    return rc > 32  # ShellExecute error codes are all <= 32


class VHFctest4WinApp(vhf.VHFApp):
    VERSION = __version__
    APP_TITLE = "VHFCtest4WIN Callbook"

    def _build(self):
        # Same window as the VHF callbook, but the title bar names the
        # VHFCtest4WIN sharing port (6767) rather than the N1MM one.
        super()._build()
        self.root.title(
            "{}  -  UDP {}  v{}".format(
                self.APP_TITLE, self.vhfctest_port or V4W_PORT, self.VERSION
            )
        )


def main():
    # If VHFCtest4WIN already holds 6767 and we are not elevated, the raw
    # capture socket would fail - relaunch with a UAC prompt instead.
    if (
        "--elevated" not in sys.argv
        and not _is_admin()
        and not _port_bindable(V4W_PORT)
        and _relaunch_elevated()
    ):
        return
    cb.run(
        VHFctest4WinApp,
        "VHFctest4WinCallbook.cfg",
        "VHFctest4WinCallbook_cache.json",
        "VHFCtest4WIN pre-log locator check",
        always_vhfctest=True,
    )


if __name__ == "__main__":
    main()
