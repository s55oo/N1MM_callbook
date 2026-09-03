# SPDX-License-Identifier: Unlicense
"""Callbooker - one contest-callbook window for HF and VHF.

An always-on-top Tkinter window that looks up the callsign being worked
and shows every source side by side, picking the right view per callsign:

* Callsign from **VHFCtest4WIN** (its multi-op sharing broadcast, UDP
  **6767**, sent as you type) -> always the **VHF** view: first name +
  each source's QRA/maidenhead locator side by side, collapsing to one
  larger green locator when they agree.
* Callsign from **N1MM Logger+** (UDP **12060**) -> the frequency in the
  packet (or the last one seen on a ``RadioInfo`` broadcast) decides:
  **>= 30 MHz -> VHF** view, **< 30 MHz -> HF** view (first name, CQ zone,
  and US state for North-American stations). With no frequency yet the
  last-used view is remembered from the previous run (HF on a first run).

Both feeds run at once. The 6767 feed is on by default; if VHFCtest4WIN
already holds the port the app relaunches itself elevated (one UAC
prompt) to read it with a raw capture socket. ``vhfctest_share=no`` in
``Callbooker.cfg`` turns that feed - and the prompt - off.

Sources: QRZCQ.com and HamQTH.com (free, no account), plus a QRZ column -
the paid QRZ.com XML API when a login is configured and the subscription
is live, otherwise the public /db/ page for the locator. The lookup
engine, window and sources are in ``n1mm_callbook.py``. Lookups are
cached in ``Callbooker_cache.json``.

LAN cache sharing (UDP **6768**, on by default, ``lan_share=no`` to turn
off) has every Callbooker on the LAN share resolved callsigns, so in a
multi-op only one PC ever queries the callbook sites for a given call and
the rest get it instantly. See ``dev/lan-cache-sharing.md``.

Made by S55OO with AI assistance.

Version: 1.6

Usage:
    python Callbooker.py [--port 12060] [--config Callbooker.cfg]
"""

__version__ = "1.6"

import ctypes
import functools
import json
import os
import socket
import subprocess
import sys

import n1mm_callbook as cb

V4W_PORT = 6767
CONFIG_NAME = "Callbooker.cfg"
# HF below this operating frequency, VHF at or above it (the classic
# 30 MHz boundary). Not configurable - it is a property of the bands.
VHF_ABOVE_MHZ = 30.0


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


class CallbookerApp(cb.CallbookApp):
    VERSION = __version__
    APP_TITLE = "Callbooker"
    VHFCTEST_CAPABLE = True
    DX_COUNTRY = False  # name only, no " (Country)" - see _apply_mode

    # Free sources per view. A QRZ slot (XML API with credentials, else -
    # in the VHF view - the locator off the public /db/ page) is prepended
    # by _apply_mode.
    _HF_CHAIN = (cb.qrzcq_lookup, cb.hamqth_lookup)
    _VHF_CHAIN = (cb.qrzcq_lookup, cb.hamqth_lookup)
    LOOKUP_CHAIN = _HF_CHAIN  # base __init__ seeds from this; _apply_mode wins

    def __init__(self, root, *args, **kwargs):
        # Set before super().__init__ so _build / _apply_mode can read them.
        self._vhf_mode = False
        self._last_mhz = None
        # Which feed and frequency drove the current lookup - captured into
        # each lookup's context for the MQTT payload (see _capture_lookup_context).
        self._result_feed = None
        self._result_frequency_mhz = None
        super().__init__(root, *args, **kwargs)
        # Grab the QRZ XML partial that base __init__ may have prepended,
        # so _apply_mode can keep it at slot 0 in either view.
        first = self.lookup_chain[0] if self.lookup_chain else None
        self._qrz_fn = first if getattr(first, "func", None) is cb.qrz_lookup else None
        self._apply_mode(self._load_mode(), force=True)

    # -- HF <-> VHF view -------------------------------------------------

    def _apply_mode(self, vhf, force=False):
        """Switch the display + lookup chain between the HF and VHF views.

        Only plain attribute writes - the render path reads SLOT_FIELDS /
        SLOT_SEP / DX_COUNTRY / lookup_chain fresh on every repaint, so
        the next _render_slots is already in the new view. Safe to call
        from the packet-listener thread (same as the base _handle_call).
        """
        vhf = bool(vhf)
        if vhf == self._vhf_mode and not force:
            return
        self._vhf_mode = vhf
        # No " (Country)" after the name in either view - the CQ zone is
        # the multiplier that matters and the name stays short.
        self.DX_COUNTRY = False
        if vhf:
            self.SLOT_FIELDS = ("grid",)
            self.SLOT_SEP = " - "
            base = self._VHF_CHAIN
        else:
            self.SLOT_FIELDS = ("state", "cqzone")
            self.SLOT_SEP = " "
            base = self._HF_CHAIN
        # QRZ slot 0: the credentialled XML/web function when we have a
        # login, else - VHF only - a web-page-only QRZ for the locator.
        qrz = self._qrz_fn or (functools.partial(cb.qrz_lookup) if vhf else None)
        chain = ([qrz] if qrz else []) + list(base)
        self.lookup_chain = tuple(chain)
        self.source_labels = tuple(cb.source_label(fn) for fn in self.lookup_chain)

    # -- feeds --------------------------------------------------------------

    def on_packet(self, src, data):
        # N1MM feed. Track the frequency (from this packet or the last
        # RadioInfo), pick the view, then hand the callsign to the shared
        # path (the base on_packet, minus the view step).
        if src not in self.local:
            return
        mhz = cb.packet_freq_mhz(data)
        if mhz:
            self._last_mhz = mhz
        call = cb.packet_callsign(data)
        if call:
            ref = mhz or self._last_mhz
            if ref is not None:
                self._apply_mode(ref >= VHF_ABOVE_MHZ)
            self._result_feed = "n1mm"
            self._result_frequency_mhz = ref
            self._handle_call(call)

    def _poll_inbox(self):
        # A callsign from VHFCtest4WIN is always VHF; force the view before
        # the base loop drains _v4w_inbox into _handle_call.
        if self._v4w_inbox:
            self._apply_mode(True)
            self._result_feed = "vhfctest4win"
            self._result_frequency_mhz = None
        super()._poll_inbox()

    # -- window / remembered view ----------------------------------------

    def _load_mode(self):
        if not self.win_file:
            return False
        try:
            with open(self.win_file, encoding="utf-8") as fh:
                return json.load(fh).get("mode") == "vhf"
        except (OSError, ValueError):
            return False

    def _save_window(self):
        # Same file as the base, plus the current view so the next start
        # opens where it left off.
        if not self.win_file:
            return
        try:
            tmp = self.win_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(
                    {"geometry": self.root.geometry(),
                     "mode": "vhf" if self._vhf_mode else "hf"},
                    fh,
                )
            os.replace(tmp, self.win_file)
        except OSError:
            pass

    def _build(self):
        super()._build()
        extra = "  +  UDP {}".format(self.vhfctest_port) if self.vhfctest_port else ""
        if getattr(self, "lan", None) is not None:
            extra += "  +  LAN {}".format(self.lan_share_port)
        self.root.title(
            "{}  -  UDP {}{}  auto HF/VHF  v{}".format(
                self.APP_TITLE, self.port, extra, self.VERSION
            )
        )


def main():
    want_v4w = _wants_v4w_feed(sys.argv)
    if (
        want_v4w
        and "--elevated" not in sys.argv
        and not _is_admin()
        and not _port_bindable(V4W_PORT)
        and _relaunch_elevated()
    ):
        return
    cb.run(
        CallbookerApp,
        CONFIG_NAME,
        "Callbooker_cache.json",
        "Contest callbook - HF state/zone and VHF locator in one window",
        always_vhfctest=want_v4w,
    )


if __name__ == "__main__":
    main()
