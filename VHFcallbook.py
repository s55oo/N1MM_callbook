# SPDX-License-Identifier: Unlicense
"""VHF/UHF locator lookup - N1MM Logger+ and VHFCtest4WIN in one window.

Shows the QRA/maidenhead locator (e.g. JN76HD) of the worked station,
with the operator name in front of it, from every configured source side
by side - QRZCQ.com, HamQTH.com and the public QRZ.com page, plus the
paid QRZ.com XML service when credentials are set. A wrong locator stands
out against the others; when every source that answered agrees the row
collapses to a single locator in a larger green font ("Hans - JN76HD").

It listens on **both** the N1MM Logger+ broadcast (XML, UDP **12060**)
and VHFCtest4WIN's multi-op sharing broadcast (UDP **6767**) at the same
time, so it does not matter which logger you use: whichever sends the
worked callsign first drives the same lookup. The VHFCtest4WIN feed also
carries the callsign *as it is typed*, so the lookup runs before the QSO
is logged and a wrong QRA locator can be caught while it is editable.

The 6767 feed is **on by default**. When VHFCtest4WIN is already running
it holds 6767 exclusively, so the app relaunches itself elevated (one UAC
prompt, click *Yes*) to read the broadcast with a Windows raw capture
socket. If you decline it still opens and the window tells you what to do.
Put ``vhfctest_share=no`` in ``VHFcallbook.cfg`` to switch the 6767 feed
(and the prompt) off and run as a plain N1MM-only VHF callbook.

Lookups are cached in ``VHFcallbook_cache.json``.

Made by S55OO with AI assistance.

Version: 1.1

Usage:
    python VHFcallbook.py [--port 12060] [--config VHFcallbook.cfg]
"""

__version__ = "1.1"

import ctypes
import os
import socket
import subprocess
import sys

import n1mm_callbook as cb

V4W_PORT = 6767
CONFIG_NAME = "VHFcallbook.cfg"


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
    """Start an elevated copy of this app (one UAC prompt), forwarding the
    original command-line arguments. Returns True if the elevated process
    is launching and this one should exit, False to keep running
    unprivileged (the window then shows a hint)."""
    passthrough = [a for a in sys.argv[1:] if a != "--elevated"]
    if getattr(sys, "frozen", False):
        target = sys.executable
        params = subprocess.list2cmdline(passthrough + ["--elevated"])
    else:
        target = sys.executable
        params = subprocess.list2cmdline(
            [os.path.abspath(sys.argv[0])] + passthrough + ["--elevated"]
        )
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", target, params, None, 1
        )
    except (AttributeError, OSError):
        return False
    return rc > 32  # ShellExecute error codes are all <= 32


def _config_path(argv):
    """The --config path from *argv*, or the default next to the exe."""
    for i, a in enumerate(argv):
        if a == "--config" and i + 1 < len(argv):
            return argv[i + 1]
        if a.startswith("--config="):
            return a.split("=", 1)[1]
    return os.path.join(cb.app_dir(), CONFIG_NAME)


def _wants_v4w_feed(argv):
    """Whether the VHFCtest4WIN 6767 feed is enabled - on unless the .cfg
    sets ``vhfctest_share=no``. Read here (before the GUI) so the UAC
    self-relaunch can be skipped when the feed is turned off."""
    cfg = cb.load_config(_config_path(argv))
    return cfg.get("vhfctest_share", "yes").strip().lower() not in (
        "no", "false", "0", "off",
    )


class VHFcallbookApp(cb.CallbookApp):
    VERSION = __version__
    APP_TITLE = "VHF Callbook"
    # Takes VHFCtest4WIN's pre-log callsign feed (UDP 6767) in addition to
    # the N1MM broadcast; run() wires the second listener.
    VHFCTEST_CAPABLE = True
    # Locator per source, shown side by side ("JN76GB - JN76HD - JN76HD")
    # so a wrong one stands out, with the operator name (from the callbook)
    # in front of it. When every source that answered agrees, the row
    # collapses to one locator in a larger font and turns light green -
    # "Hans - JN76HD" - a quick "grid confirmed" signal.
    SLOT_FIELDS = ("grid",)
    SLOT_SEP = " - "
    SHOW_NAME = True
    DX_COUNTRY = False        # locator-focused: no " (Country)" after the name
    COLLAPSE_ON_AGREE = True
    # Slot order: QRZCQ, HamQTH's "Grid:" row, then the locator computed
    # from the coordinates on the public QRZ.com page. The paid QRZ XML
    # service is prepended automatically when credentials are configured.
    LOOKUP_CHAIN = (cb.qrzcq_lookup, cb.hamqth_lookup, cb.qrzdb_lookup)

    def _build(self):
        super()._build()
        # Title bar names every feed the app is actually listening on.
        extra = "  +  UDP {}".format(self.vhfctest_port) if self.vhfctest_port else ""
        self.root.title(
            "{}  -  UDP {}{}  v{}".format(
                self.APP_TITLE, self.port, extra, self.VERSION
            )
        )


def main():
    want_v4w = _wants_v4w_feed(sys.argv)
    # If the 6767 feed is wanted and VHFCtest4WIN already holds the port,
    # a raw capture socket (which needs elevation) is the only way to read
    # it - relaunch with a UAC prompt. No prompt when the feed is off, the
    # port is free (VHFCtest4WIN not up yet), or we are already elevated.
    if (
        want_v4w
        and "--elevated" not in sys.argv
        and not _is_admin()
        and not _port_bindable(V4W_PORT)
        and _relaunch_elevated()
    ):
        return
    cb.run(
        VHFcallbookApp,
        CONFIG_NAME,
        "VHFcallbook_cache.json",
        "VHF locator lookup (N1MM Logger+ / VHFCtest4WIN)",
        always_vhfctest=want_v4w,
    )


if __name__ == "__main__":
    main()
