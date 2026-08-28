"""N1MM Logger+ Contest Callbook lookup.

A compact always-on-top window that listens to the N1MM Logger+ external
UDP broadcast (XML, port 12060) and automatically looks up the callsign
currently in the radio/RX1. Each source is queried and ALL of its values
are shown side by side (e.g. "MA MA MA" for the US state on HF, three
locators on the VHF variant), so disagreements between sources stand out
and the operator can pick the right one.

QRZCQ.com is a public, free callbook that needs no account or API key -
each callsign has a page at https://www.qrzcq.com/call/<CALL> whose
lookup info is parsed from the HTML. HamQTH.com and (VHF) the QRZ.com
public page back it up; the paid QRZ.com XML service can also be added
when credentials are configured.

Lookups are cached locally in a JSON file to avoid repeated network
fetches for the same callsign and to stay polite to the server.

Made by S55OO with AI assistance.

Version: 2.2

Usage:
    python n1mm_callbook.py [--port 12060] [--config callbook.cfg]
"""

__version__ = "2.2"

import argparse
import base64
import functools
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

USER_AGENT = "Mozilla/5.0 N1MM_callbook/2.2"
HAMQTH_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

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
    """Very small persistent JSON cache for callbook lookups."""

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
        sources = entry.get("sources")
        # Old-format entries stored a single merged 'info' dict; treat them
        # as stale so the next lookup re-fetches per-source results.
        if not isinstance(sources, list) or not sources:
            return None
        return sources

    def put(self, call, sources):
        self._data[call] = {"ts": time.time(), "sources": sources}
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


def hamqth_lookup(call, timeout=15):
    """Query HamQTH.com public page for a callsign.

    HamQTH mirrors the same fields as QRZCQ (name, QTH, grid locator,
    country, ...) and is used as an additional/fallback source - most
    useful for the VHF variant, where the "Grid" row carries the
    QRA/maidenhead locator of the worked station.

    Returns a dict in the same shape as qrzcq_lookup, or None on
    network error. Fields that are absent or hidden come back empty.
    """
    url = "https://www.hamqth.com/" + urllib.parse.quote(call.upper())
    try:
        req = urllib.request.Request(url, headers={"User-Agent": HAMQTH_UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    def grab(label):
        m = re.search(
            r'<td[^>]*class="infoDesc"[^>]*>\s*' + re.escape(label) + r":\s*</td>"
            r"\s*<td[^>]*>(.*?)</td>",
            raw,
            re.S | re.I,
        )
        if not m:
            return ""
        val = re.sub(r"<[^>]+>", " ", m.group(1))
        return re.sub(r"\s+", " ", val).strip()

    return {
        "name": grab("Name"),
        "qth": grab("QTH"),
        "grid": grab("Grid"),
        "class": grab("Class"),
        "state": grab("US State") or grab("State"),
        "country": grab("Country"),
    }


_QRZ_SESSION = {}  # username -> {"key": str, "ts": float}


def _qrz_login(username, password, timeout=15):
    """Log in to the paid QRZ.com XML Callbook Data service.

    Returns (session_key, error_message). On success a session key that
    is valid for ~1 hour / 500 lookups; on failure the QRZ error text.
    """
    query = urllib.parse.urlencode({"username": username, "password": password})
    url = "https://xml.qrz.com/xml/current/?" + query
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return None, "network error"
    # The QRZ XML carries a default namespace; drop it so the plain tag
    # lookups below (Error, Session/Key, ...) work without namespace paths.
    raw = raw.replace(' xmlns="http://xml.qrz.com"', "", 1)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None, "parse error"
    err = root.findtext("Error") or ""
    if err:
        return None, err
    return (root.findtext("Session/Key") or "").strip() or None, ""


def qrz_lookup(call, username="", password="", timeout=15):
    """Look up a callsign on the paid QRZ.com XML service.

    Needs a QRZ XML subscription; credentials come from the config file.
    Reuses the session key, re-logging in when it expired or the server
    rejected it. Returns a dict like qrzcq_lookup (or None on failure),
    so it can be used as another entry of the lookup chain.
    """
    if not username or not password:
        return None
    key = None
    sess = _QRZ_SESSION.get(username)
    if sess and (time.time() - sess.get("ts", 0)) < 2700:
        key = sess.get("key")
    if not key:
        key, err = _qrz_login(username, password, timeout)
        if err or not key:
            return None
        _QRZ_SESSION[username] = {"key": key, "ts": time.time()}

    params = {"s": key, "callsign": call.upper()}
    url = "https://xml.qrz.com/xml/current/?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    raw = raw.replace(' xmlns="http://xml.qrz.com"', "", 1)
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    err = root.findtext("Error") or ""
    if err:
        if "session" in err.lower():
            _QRZ_SESSION.pop(username, None)  # drop stale key, retry next time
        return None
    cs = root.find("Callsign")
    if cs is None:
        return None

    def t(field):
        el = cs.find(field)
        return (el.text or "").strip() if el is not None else ""

    addr1, addr2 = t("addr1"), t("addr2")
    qth = " | ".join(x for x in (addr2, addr1) if x)
    return {
        "name": t("fname") or t("name"),
        "qth": qth,
        "grid": t("grid"),
        "class": t("class"),
        "state": t("state"),
        "country": t("country"),
    }


def maidenhead_from_latlon(lat, lon):
    """Convert WGS84 coordinates to a 6-char maidenhead locator.

    Used to derive the grid square from the coordinates that QRZ.com
    embeds on its public callsign pages.
    """
    try:
        lat = float(lat)
        lon = float(lon)
    except (TypeError, ValueError):
        return ""
    a = lon + 180.0
    b = lat + 90.0
    out = chr(ord("A") + int(a / 20)) + chr(ord("A") + int(b / 10))
    a -= int(a / 20) * 20
    b -= int(b / 10) * 10
    out += str(int(a / 2)) + str(int(b / 1))
    a -= int(a / 2) * 2
    b -= int(b / 1) * 1
    out += chr(ord("A") + int(a * 12)) + chr(ord("A") + int(b * 24))
    return out


def qrzdb_lookup(call, timeout=15):
    """Grab the locator from the public QRZ.com /db/<CALL> page.

    QRZ only shows its full Detail tab ("Grid square") to logged-in users,
    but every callsign page embeds the station's coordinates as
    cs_lat / cs_lon - so the 6-char maidenhead locator can be computed
    for free, without any account or subscription.

    Returns a dict in the same shape as qrzcq_lookup (grid filled in from
    the coordinates), or None on a network error.
    """
    url = "https://www.qrz.com/db/" + urllib.parse.quote(call.upper())
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": HAMQTH_UA,
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    lat = re.search(r'var cs_lat = "([0-9.\-]+)"', raw)
    lon = re.search(r'var cs_lon = "([0-9.\-]+)"', raw)
    grid = ""
    if lat and lon:
        grid = maidenhead_from_latlon(lat.group(1), lon.group(1))
    return {
        "name": "",
        "qth": "",
        "grid": grid,
        "class": "",
        "state": "",
        "country": "",
    }


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


class CallbookApp:
    APP_TITLE = "N1MM Callbook"
    # Field the main area highlights. Each source in the chain contributes
    # its own value and ALL of them are shown (e.g. "MA MA MA"), so the
    # operator can see when sources disagree and pick the right one.
    FIELD = "state"
    # Show the operator name too (printed once, shortest of the sources).
    # The VHF variant only needs the locator, hence False there.
    SHOW_NAME = True
    # Lookup sources run in order; every source's value is kept separately.
    # Variants can add more sources.
    LOOKUP_CHAIN = (qrzcq_lookup, hamqth_lookup)

    def __init__(self, root, cache_path, port, cache_days, qrz_username="", qrz_password=""):
        self.root = root
        self.port = port
        self.cache = Cache(cache_path, cache_days)
        self.current = None
        self._fetching = False
        self._debounce = None
        # QRZ XML first: it answers via a single XML request, so its slot
        # usually fills before the page scrapers. Added when credentials
        # are present, otherwise the free sources run without it.
        chain = []
        if qrz_username and qrz_password:
            chain.append(
                functools.partial(
                    qrz_lookup, username=qrz_username, password=qrz_password
                )
            )
        chain.extend(self.LOOKUP_CHAIN)
        self.lookup_chain = tuple(chain)
        # Background lookups push per-source results here; the GUI drains
        # the queue every 100ms and renders each slot as it arrives.
        self._inbox = []
        self._slots = None
        self._pending_inds = set()
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
        self.root.after(100, self._poll_inbox)

    def _build(self):
        self.root.title("{}  -  UDP {}  v{}".format(self.APP_TITLE, self.port, __version__))
        self.root.attributes("-topmost", True)
        frame = tk.Frame(self.root, padx=6, pady=4)
        frame.pack()
        top = tk.Frame(frame)
        top.pack(fill=tk.X)
        tk.Label(
            top, text=self.APP_TITLE, font=("Segoe UI", 8, "bold")
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
        self._debounce = self.root.after(300, self._on_stable, call)

    def _on_stable(self, call):
        self._debounce = None
        if call != self.current:
            return
        sources = self.cache.get(call)
        if sources is not None:
            self._slots = None
            self._render_slots(call, list(sources), set())
        else:
            self._start_lookup(call)

    def _show_call(self, call):
        self.call_label.configure(text=call)
        sources = self.cache.get(call)
        if sources is not None:
            self._slots = None
            self._render_slots(call, list(sources), set())
        else:
            # cleared visually while waiting for the debounce / lookup
            self.canvas.configure(bg=COLOR_ACTIVE)
            self.canvas.itemconfigure(self.main_id, text="…")

    def _start_lookup(self, call):
        if self._fetching:
            return
        self._fetching = True
        self._slots = [None] * len(self.lookup_chain)
        self._pending_inds = set(range(len(self.lookup_chain))) if self._slots else set()
        self._render_slots(call, self._slots, self._pending_inds)
        threading.Thread(target=self._do_lookup, args=(call,), daemon=True).start()

    def _do_lookup(self, call):
        # Runs in a worker thread; each source result is handed to the GUI
        # as soon as that source has answered, so the display fills in
        # source order (QRZ XML first when configured).
        for i, fn in enumerate(self.lookup_chain):
            res = fn(call)
            self._inbox.append((call, i, res))

    def _poll_inbox(self):
        # GUI thread: drains results posted by the worker and renders them.
        try:
            while self._inbox:
                call, i, res = self._inbox.pop(0)
                if call != self.current:
                    continue
                if self._slots is None or i >= len(self._slots):
                    continue
                self._slots[i] = res
                self._pending_inds.discard(i)
                if not self._pending_inds:
                    self._fetching = False
                    # Only cache a complete, error-free set of results.
                    if not any(s is None for s in self._slots):
                        self.cache.put(call, list(self._slots))
                self._render_slots(call, self._slots, self._pending_inds)
        except Exception:
            pass
        self.root.after(100, self._poll_inbox)

    def _source_field(self, info, key):
        if not info:
            return ""
        return (info.get(key) or "").strip()

    def _source_value(self, info):
        return self._source_field(info, self.FIELD)

    def _best_name(self, sources):
        # The operator name, printed only once; out of the candidates from
        # the sources that have answered so far the shortest one wins.
        # Placeholder entries (QRZCQ fills unallocated calls with
        # "Unknown OM") count as empty.
        names = []
        for s in sources:
            n = self._source_field(s, "name")
            a = n.lower()
            if a and not a.startswith(("unknown", "not found", "n/a", "na")):
                names.append(n)
        return min(names, key=len) if names else ""

    def _render_slots(self, call, slots, pending):
        # Renders the main area at any stage of the lookup. Each slot maps
        # to one source in chain order; still-fetching slots show "…" so
        # results appear as they arrive (e.g. "Fred - MA … …" then the
        # rest fill in). Example final lines:
        #   HF (state):  "Dave - MA MA MA"  (QRZ first when configured)
        #   VHF (grid):  "JN76HD JN76HD JN76HD JN76HD"
        finished = [slots[i] for i in range(len(slots)) if i not in pending]
        any_data = any(self._source_value(s) for s in finished if s)
        vals = []
        for i in range(len(slots)):
            if i in pending:
                vals.append("…")
            else:
                s = slots[i]
                v = self._source_value(s) if s else ""
                vals.append(v if v else "-")
        all_done = not pending
        if not finished:
            text = "…"
            bg = COLOR_ACTIVE
        elif any_data:
            line = " ".join(vals)
            if self.SHOW_NAME:
                name = self._best_name(finished)
                if name and any(v not in ("-", "…") for v in vals):
                    text = "{} - {}".format(name, line)
                else:
                    text = name if name else line
            else:
                text = line
            bg = COLOR_ACTIVE
        elif not all_done:
            text = "…"
            bg = COLOR_ACTIVE
        else:
            text = "lookup failed" if all(s is None for s in slots) else "no data"
            bg = COLOR_IDLE
        self.canvas.configure(bg=bg)
        self.canvas.itemconfigure(self.main_id, text=text)
        self.canvas.itemconfigure(self.main_id, font=self._font_for(len(text)))

    def _font_for(self, length):
        for limit, size in FONT_SIZES:
            if length <= limit:
                return ("Segoe UI", size, "bold")
        return ("Segoe UI", 11, "bold")

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

    # Optional QRZ.com XML service (paid subscription). Empty credentials
    # keep QRZ out of the lookup chain.
    qrz_username = settings.get("qrz_username", "")
    qrz_password = settings.get("qrz_password", "")

    root = tk.Tk()
    CallbookApp(root, cache_file, port, cache_days, qrz_username, qrz_password)
    root.mainloop()


if __name__ == "__main__":
    main()
