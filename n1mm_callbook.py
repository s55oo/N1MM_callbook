"""N1MM Logger+ Contest Callbook lookup.

A compact always-on-top window that listens to the N1MM Logger+ external
UDP broadcast (XML, port 12060) and automatically looks up the callsign
currently in the radio/RX1 via QRZCQ.com. The operator name, QTH and
grid square are shown under the callsign.

QRZCQ.com is a public, free callbook that needs no account or API key -
each callsign has a page at https://www.qrzcq.com/call/<CALL> whose
lookup info is parsed from the HTML.

Lookups are cached locally in a JSON file to avoid repeated network
fetches for the same callsign and to stay polite to the server.

Made by S55OO with AI assistance.

Version: 1.5

Usage:
    python n1mm_callbook.py [--port 12060] [--config callbook.cfg]
"""

__version__ = "1.5"

import argparse
import base64
import json
import os
import re
import socket
import sys
import threading
import time
import tkinter as tk
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 N1MM_callbook/1.5"

DEFAULT_PORT = 12060
DEFAULT_CACHE_DAYS = 30
HELP_URL = ""
HELP_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABFElEQVR4nK2TMYqFMBCGJ49X2HoArQTBTqxsbCysBSutLbyBR4gH8AQBW0/gARQUC/EGVlZ2WmVByBJiIizswBTO+P35J0wQSKIsSyqrY4yRWEMyuGkaGQ9pmj5EkHiqCuZFeDcfvsngIAig6zpY1xUIIWAYxuOfh23TNO90XZcex0HzPKeO41BCCJ2m6bfPkjlG4sxxHEOSJJBl2f2t6zrM8wy2bcN5no9xvqKbtm3vZOF5HmzbBtd1Se/k+3Zhvu9DVVVQFAVQSv8moGka1HV9w8MwKA/5qBqWZcG+79D3/ZtJUAosywJRFL3CtwDGGLHl4CMMQxjHUQmyrUSs8LbCKvgxgsyJDObj/x6TKCKry57zD5uWhA5j8tjMAAAAAElFTkSuQmCC"
)
COLOR_IDLE = "#3a3a3a"
COLOR_ACTIVE = "#1f6feb"

FONT_SIZE_NAME = 18
FONT_SIZE_FOOTER = 10
FONT_SIZES = [(14, 18), (24, 15), (34, 13), (9999, 11)]


def packet_callsign(data):
    """Extract the worked station's callsign from an N1MM broadcast packet.

    N1MM's useful packets for a callbook (both use the lowercase "call"
    field and have structurally identical XML):

    * LookupInfo  - sent after entering a callsign in the entry window and
      pressing the Space bar, before the QSO is logged. Requires the
      "External Callsign Lookup" broadcast option to be enabled in N1MM.
      This is the "I've committed the callsign" trigger.
    * ContactInfo - sent when the contact is added to the log. Requires
      the "Contacts" broadcast option to be enabled.

    RadioInfo is deliberately ignored: its "OpCall"/"mycall" is the local
    operator's own callsign, not the station being worked. Returns the
    callsign string, or None if the packet carries no worked station.
    """
    raw = data.decode("utf-8", errors="replace")
    start = raw.find("<")
    if start < 0:
        return None
    try:
        root = ET.fromstring(raw[start:])
    except ET.ParseError:
        return None
    kind = root.tag.lower()
    if kind not in ("lookupinfo", "contactinfo", "contactreplace"):
        return None
    callsign = ""
    for el in root.iter():
        name = el.tag
        if name == "Call":
            return (el.text or "").strip().upper() or None
        if name.lower() == "call" and el.text and el.text.strip():
            callsign = el.text.strip()
            return callsign.upper() or None
    return callsign.upper() or None


def normalize_call(call):
    if not call:
        return ""
    return "".join(ch for ch in call.upper() if ch.isalnum() or ch in "/.:")


def local_interfaces():
    ips = []
    try:
        ips.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            if info[4][0] not in ips:
                ips.append(info[4][0])
    except OSError:
        pass
    return [ip for ip in ips if not ip.startswith("127.")]


def open_socket(bind_ip, port):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    sock.bind((bind_ip, port))
    sock.settimeout(0.3)
    return sock


def listener_loop(bind_ip, port, on_packet, stop):
    try:
        sock = open_socket(bind_ip, port)
    except OSError:
        for ip in local_interfaces():
            try:
                sock = open_socket(ip, port)
                break
            except OSError:
                continue
        else:
            return
    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        on_packet(addr[0], data)
    try:
        sock.close()
    except OSError:
        pass


class Cache:
    """Very small persistent JSON cache for HamQTH lookups."""

    def __init__(self, path, days):
        self.path = path
        self.days = days
        self._data = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                self._data = json.load(fh)
        except (OSError, ValueError):
            self._data = {}

    def get(self, call):
        entry = self._data.get(call)
        if not entry:
            return None
        if (time.time() - entry.get("ts", 0)) > self.days * 86400:
            return None
        info = entry.get("info")
        # Old-format cache entries predate the 'state' field and only have the
        # name; treat them as stale so the next lookup re-fetches and fills in
        # the state rather than showing a bare name from history.
        if not isinstance(info, dict) or "state" not in info:
            return None
        return info

    def put(self, call, info):
        self._data[call] = {"ts": time.time(), "info": info}
        self._save()

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass


def qrzcq_lookup(call, timeout=15):
    """Query QRZCQ.com for a callsign by parsing its public page.

    Returns a dict with 'name'/'qth'/'grid'/'class'/'country' (any may be
    empty), or None on network/parse error.
    """
    url = "https://www.qrzcq.com/call/" + urllib.parse.quote(call.upper())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    name, addr = "", ""
    m = re.search(r'<p class="haminfoaddress">(.*?)</p>', raw, re.S)
    if m:
        block = m.group(1)
        b = re.search(r"<b[^>]*>([^<]+)</b>(.*)", block, re.S)
        if b:
            name = b.group(1).strip()
            a = b.group(2)
            a = re.sub(r"<br\s*/?>", " | ", a)
            a = re.sub(r"<[^>]+>", " ", a)
            a = re.sub(r"\s+", " ", a).strip(" |")
            for cut in ("APRS Info", "Call data", "&bull;", "&nbsp;"):
                idx = a.find(cut)
                if idx != -1:
                    a = a[:idx]
                    break
            a = re.sub(r"(?:\s*\|\s*)+$", "", a).strip(" |")
            addr = a

    def grab(label):
        mm = re.search(
            r"<b>" + label + r":</b></td><td align=\"left\">([^<]+)</td>", raw
        )
        return mm.group(1).strip() if mm else ""

    return {
        "name": name,
        "qth": addr,
        "grid": grab("Locator"),
        "class": grab("Class"),
        "state": grab("Federal state"),
        "country": "",
    }


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class CallbookApp:
    def __init__(self, root, cache_path, port, cache_days):
        self.root = root
        self.port = port
        self.cache = Cache(cache_path, cache_days)
        self.current = None
        self._fetching = False
        self._debounce = None
        self.local = set(local_interfaces())
        self.local.add("127.0.0.1")
        self._build()
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=listener_loop,
            args=("0.0.0.0", port, self.on_packet, self.stop),
            daemon=True,
        )
        self.thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(500, self._flush_pending)

    def _build(self):
        self.root.title("N1MM Callbook  -  UDP {}  v{}".format(self.port, __version__))
        self.root.attributes("-topmost", True)
        frame = tk.Frame(self.root, padx=6, pady=4)
        frame.pack()
        top = tk.Frame(frame)
        top.pack(fill=tk.X)
        tk.Label(
            top, text="N1MM Callbook", font=("Segoe UI", 8, "bold")
        ).pack(side=tk.LEFT)
        self.help_icon = tk.PhotoImage(
            data=base64.b64decode(HELP_ICON_B64.encode("ascii"))
        )
        self.help_link = tk.Label(top, image=self.help_icon, cursor="hand2")
        self.help_link.pack(side=tk.RIGHT)
        self.help_link.bind("<Button-1>", lambda e: self._open_help())

        self.canvas = tk.Canvas(
            frame,
            width=330,
            height=64,
            bg=COLOR_IDLE,
            highlightthickness=1,
            highlightbackground="#888888",
        )
        self.canvas.pack(fill=tk.X)
        self.main_id = self.canvas.create_text(
            165, 32, text="—", font=("Segoe UI", FONT_SIZE_NAME, "bold"), fill="white"
        )
        self.canvas.bind("<Configure>", self._recenter_text)

        self.call_label = tk.Label(
            frame, text="", font=("Segoe UI", FONT_SIZE_FOOTER), justify=tk.CENTER
        )
        self.call_label.pack(fill=tk.X)

    def _recenter_text(self, event):
        self.canvas.coords(self.main_id, event.width / 2.0, event.height / 2.0)

    def _open_help(self):
        try:
            import webbrowser

            webbrowser.open("https://www.qrzcq.com")
        except Exception:
            pass

    def on_packet(self, src, data):
        # Only look up callsigns from the local computer (this PC), ignoring
        # broadcasts from other stations on the network.
        if src not in self.local:
            return
        call = packet_callsign(data)
        if not call:
            return
        call = normalize_call(call)
        if not call or call.lower().startswith("test"):
            return
        # Show the callsign immediately (it may change as the user types),
        # but debounce the network lookup until it has been stable a moment.
        if self.current != call:
            self.current = call
            self._show_call(call)
        if self._debounce is not None:
            self.root.after_cancel(self._debounce)
        self._debounce = self.root.after(1200, self._on_stable, call)

    def _on_stable(self, call):
        self._debounce = None
        if call != self.current:
            return
        info = self.cache.get(call)
        if info is not None:
            self._set_info(call, info, cached=True)
        else:
            self._set_info(call, None, searching=True)
            self._fetch_async(call)

    def _show_call(self, call):
        self.call_label.configure(text=call)
        info = self.cache.get(call)
        if info is not None:
            self._set_info(call, info, cached=True)
        else:
            # cleared visually while waiting for the debounce / lookup
            self.canvas.configure(bg=COLOR_ACTIVE)
            self.canvas.itemconfigure(self.main_id, text="…")

    def _fetch_async(self, call):
        if self._fetching:
            return
        self._fetching = True
        threading.Thread(target=self._do_fetch, args=(call,), daemon=True).start()

    def _do_fetch(self, call):
        info = qrzcq_lookup(call)
        status = "api error"
        if info is not None:
            self.cache.put(call, info)
            status = ""
        self._fetching = False
        self._pending = (call, info, status)

    def _flush_pending(self):
        pending = getattr(self, "_pending", None)
        if pending:
            call, info, status = pending
            self._pending = None
            if call == self.current:
                self._set_info(call, info, cached=False, status=status)
        self.root.after(500, self._flush_pending)

    def _line(self, info):
        name = (info.get("name") or "").strip()
        name = name.split()[0] if name else ""
        state = (info.get("state") or "").strip()
        if name and state:
            return "{} - {}".format(name, state)
        return name or state

    def _font_for(self, length):
        for limit, size in FONT_SIZES:
            if length <= limit:
                return ("Segoe UI", size, "bold")
        return ("Segoe UI", 11, "bold")

    def _set_info(self, call, info, cached=False, status="", searching=False):
        if searching:
            self.canvas.configure(bg=COLOR_ACTIVE)
            self.canvas.itemconfigure(self.main_id, text="…")
        elif info is not None and (info.get("name") or info.get("state")):
            self.canvas.configure(bg=COLOR_ACTIVE)
            text = self._line(info)
            self.canvas.itemconfigure(self.main_id, text=text)
            self.canvas.itemconfigure(self.main_id, font=self._font_for(len(text)))
        elif status == "api error":
            self.canvas.configure(bg=COLOR_IDLE)
            self.canvas.itemconfigure(self.main_id, text="lookup failed")
        else:
            self.canvas.configure(bg=COLOR_IDLE)
            self.canvas.itemconfigure(self.main_id, text="no data")

    def on_close(self):
        self.stop.set()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description="N1MM Logger+ contest callbook")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--config",
        default=os.path.join(app_dir(), "callbook.cfg"),
        help="config file (same folder as the exe by default)",
    )
    args = parser.parse_args()

    settings = {}
    if os.path.exists(args.config):
        try:
            with open(args.config, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith(("#", "[")):
                        continue
                    if "=" not in line:
                        continue
                    key, _, val = [p.strip() for p in line.partition("=")]
                    settings[key.lower()] = val
        except OSError:
            pass

    port = args.port
    if "udp_port" in settings:
        try:
            port = int(settings["udp_port"])
        except ValueError:
            pass
    cache_days = DEFAULT_CACHE_DAYS
    if "cache_days" in settings:
        try:
            cache_days = int(settings["cache_days"])
        except ValueError:
            pass
    cache_file = os.path.join(app_dir(), "callbook_cache.json")
    if "cache_file" in settings:
        cache_file = os.path.abspath(
            os.path.join(os.path.dirname(args.config), settings["cache_file"])
        )

    root = tk.Tk()
    CallbookApp(root, cache_file, port, cache_days)
    root.mainloop()


if __name__ == "__main__":
    main()
