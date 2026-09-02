# SPDX-License-Identifier: Unlicense
"""N1MM Logger+ Contest Callbook lookup.

A compact always-on-top window that listens to the N1MM Logger+ external
UDP broadcast (XML, port 12060) and automatically looks up the callsign
currently in the radio/RX1. Every source is queried in parallel and ALL
of its values are shown side by side (e.g. "MA/5 MA/5 MA/5" for the US
state + CQ zone on HF, three locators on the VHF variant), each slot
filling in as soon as that source answers, so disagreements between
sources stand out and the operator can pick the right one. For non-US
(DX) stations the HF window shows the operator name and country followed
by the CQ zone from each source.

QRZCQ.com is a public, free callbook that needs no account or API key -
each callsign has a page at https://www.qrzcq.com/call/<CALL> whose
lookup info is parsed from the HTML. HamQTH.com and (VHF) the QRZ.com
public page back it up; the paid QRZ.com XML service can also be added
when credentials are configured.

Lookups are cached locally in a JSON file to avoid repeated network
fetches for the same callsign and to stay polite to the server.

Made by S55OO with AI assistance.

Version: 2.16

Usage:
    python n1mm_callbook.py [--port 12060] [--config callbook.cfg]
"""

__version__ = "2.16"

import argparse
import base64
import functools
import gzip
import http.client
import json
import os
import re
import select
import socket
import sys
import threading
import time
import tkinter as tk
import urllib.parse
import xml.etree.ElementTree as ET

USER_AGENT = "Mozilla/5.0 N1MM_callbook/2.16"
HAMQTH_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

DEFAULT_PORT = 12060
DEFAULT_CACHE_DAYS = 30
HELP_URL = "https://github.com/s55oo/N1MM_callbook/"
HELP_ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAABAAAAAQCAYAAAAf8/9hAAABFElEQVR4nK2TMYqFMBCGJ49X2HoArQTBTqxsbCysBSutLbyBR4gH8AQBW0/gARQUC/EGVlZ2WmVByBJiIizswBTO+P35J0wQSKIsSyqrY4yRWEMyuGkaGQ9pmj5EkHiqCuZFeDcfvsngIAig6zpY1xUIIWAYxuOfh23TNO90XZcex0HzPKeO41BCCJ2m6bfPkjlG4sxxHEOSJJBl2f2t6zrM8wy2bcN5no9xvqKbtm3vZOF5HmzbBtd1Se/k+3Zhvu9DVVVQFAVQSv8moGka1HV9w8MwKA/5qBqWZcG+79D3/ZtJUAosywJRFL3CtwDGGLHl4CMMQxjHUQmyrUSs8LbCKvgxgsyJDObj/x6TKCKry57zD5uWhA5j8tjMAAAAAElFTkSuQmCC"
)
COLOR_IDLE = "#3a3a3a"
COLOR_ACTIVE = "#1f6feb"
TEXT_DEFAULT = "white"
TEXT_AGREE = "#b9f5b0"  # very light green: every source returned the same value
SLOT_EMPTY = "·"   # a source answered but had no value ("·")
SLOT_PENDING = "…"  # a source is still being queried ("…")

FONT_SIZE_NAME = 18
FONT_SIZE_FOOTER = 10
FONT_SIZES = [(14, 18), (24, 15), (34, 13), (9999, 11)]
# When the VHF view collapses to a single agreed locator (COLLAPSE_ON_AGREE)
# it is drawn ~two steps larger than the normal 18 pt - unless the operator
# name in front of it pushes the line past FONT_BIG_MAXLEN characters, in
# which case the usual length-based sizing is used so it still fits.
FONT_SIZE_BIG = 26
FONT_BIG_MAXLEN = 16

# Start-up self-test. On launch every configured source is queried once
# for PRECHECK_CALL and the window lists, source by source, whether it
# answered and how long it took - a quick "are the sources reachable and
# still parsing?" check before a contest. The default is the author's own
# call, which is listed (with the same locator) on every source, so a
# healthy run is all-green; override it with selftest_call= (or turn the
# whole thing off with selftest=no) in the .cfg.
PRECHECK_CALL = "S55OO"
PRECHECK_HOLD_MS = 4000  # keep the finished result on screen this long
SOURCE_LABELS = {
    "qrz_lookup": "QRZ XML",
    "qrzcq_lookup": "QRZCQ",
    "hamqth_lookup": "HamQTH",
    "qrzdb_lookup": "QRZ web",
}


def source_label(fn):
    """Short human name for a lookup-chain entry.

    Unwraps the ``functools.partial`` that ``__init__`` builds for the
    paid QRZ XML source so the self-test can label every slot.
    """
    fn = getattr(fn, "func", fn)
    name = getattr(fn, "__name__", "")
    return SOURCE_LABELS.get(name, name or "source")


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


def packet_v4w(data):
    """Extract the callsign from a VHFCtest4WIN multi-op sharing packet.

    VHFCtest4WIN broadcasts the entry-field contents to UDP port 6767 as
    it is typed, wrapped as ``<V4W><QSOINLOG><CALLSIGN>..</CALLSIGN>..``.
    Unlike N1MM's LookupInfo/ContactInfo this arrives *before* the QSO is
    logged (one packet per keystroke), so the callbook can flag a bad
    locator while it can still be fixed. Returns the callsign in upper
    case, or None when the packet is not a ``<V4W>`` packet or carries an
    empty ``<CALLSIGN>`` (VHFCtest4WIN sends an empty one when the field
    is cleared).
    """
    raw = data.decode("utf-8", errors="replace")
    start = raw.find("<")
    if start < 0:
        return None
    try:
        root = ET.fromstring(raw[start:])
    except ET.ParseError:
        return None
    if root.tag.lower() != "v4w":
        return None
    for el in root.iter():
        if el.tag.lower() == "callsign":
            return (el.text or "").strip().upper() or None
    return None


def normalize_call(call):
    if not call:
        return ""
    return "".join(ch for ch in call.upper() if ch.isalnum() or ch in "/.:")


def normalize_grid(grid):
    """Upper-case a maidenhead locator so sources agree on case.

    Some sources return the sub-square in lower case (e.g. "JN46la") and
    others in upper case ("JN46LA"); without this they would look like a
    disagreement in the side-by-side display.
    """
    return (grid or "").strip().upper()


class _HttpPool:
    """One kept-alive HTTPS connection per host.

    Every callbook lookup is a single GET, and back-to-back QSOs hit the
    same three or four hosts over and over. Re-using the connection skips
    the ~90 ms TLS handshake each time (measured: QRZCQ 118->33 ms,
    HamQTH 213->120 ms per request). Responses are requested gzip-encoded
    (the pages shrink 3-5x) and transparently decompressed.

    http.client connections are not thread-safe, so each host has its own
    lock; a stale or server-closed connection is reopened and the request
    retried once. If the pooled connection is busy (a retyped callsign can
    fire a second lookup at the same host), the caller doesn't queue
    behind it - it falls back to a one-shot connection so a slow source
    never blocks a fresh lookup.
    """

    def __init__(self):
        self._hosts = {}  # host -> [connection_or_None, threading.Lock]
        self._guard = threading.Lock()

    def _slot(self, host):
        with self._guard:
            slot = self._hosts.get(host)
            if slot is None:
                slot = [None, threading.Lock()]
                self._hosts[host] = slot
            return slot

    @staticmethod
    def _do(conn, path, hdrs):
        conn.request("GET", path, headers=hdrs)
        resp = conn.getresponse()
        body = resp.read()  # must drain fully to reuse the connection
        if resp.status >= 400:
            return None
        if "gzip" in (resp.getheader("Content-Encoding") or ""):
            body = gzip.decompress(body)
        return body.decode("utf-8", errors="replace")

    def get(self, url, headers=None, timeout=15):
        parts = urllib.parse.urlsplit(url)
        host = parts.netloc
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        hdrs = dict(headers or {})
        hdrs.setdefault("Accept-Encoding", "gzip")
        hdrs["Connection"] = "keep-alive"

        slot = self._slot(host)
        if not slot[1].acquire(blocking=False):
            # Host busy - use a throwaway connection instead of waiting.
            conn = None
            try:
                conn = http.client.HTTPSConnection(host, timeout=timeout)
                return self._do(conn, path, hdrs)
            except (OSError, http.client.HTTPException):
                return None
            finally:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
        try:
            for attempt in (1, 2):
                conn = slot[0]
                if conn is None:
                    conn = http.client.HTTPSConnection(host, timeout=timeout)
                    slot[0] = conn
                try:
                    return self._do(conn, path, hdrs)
                except (OSError, http.client.HTTPException):
                    try:
                        conn.close()
                    except Exception:
                        pass
                    slot[0] = None
                    if attempt == 2:
                        return None
        finally:
            slot[1].release()
        return None


_POOL = _HttpPool()


def http_get(url, headers=None, timeout=15):
    """GET *url* through the shared keep-alive pool.

    Returns the decoded body, or None on any network / HTTP error (so
    callers keep their existing "None means this source failed" contract).
    """
    return _POOL.get(url, headers, timeout)


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


def _udp_payload(pkt, want_port):
    """Return the UDP payload of a raw IPv4 packet whose destination port
    is *want_port*, or None. ``pkt`` is a full IPv4 datagram as delivered
    by a ``SOCK_RAW`` / ``IPPROTO_IP`` socket on Windows (IP header
    included)."""
    if len(pkt) < 28:
        return None
    ihl = (pkt[0] & 0x0F) * 4
    if ihl < 20 or pkt[9] != 17 or len(pkt) < ihl + 8:  # 17 = UDP
        return None
    if ((pkt[ihl + 2] << 8) | pkt[ihl + 3]) != want_port:
        return None
    ulen = (pkt[ihl + 4] << 8) | pkt[ihl + 5]
    end = ihl + ulen if 8 <= ulen <= len(pkt) - ihl else len(pkt)
    return pkt[ihl + 8:end]


def _v4w_raw_listen(port, on_call, stop):
    """Fallback capture for when the UDP port cannot be bound.

    VHFCtest4WIN binds port 6767 with ``SO_EXCLUSIVEADDRUSE``, so when it
    is already running no second socket can bind that port - not even on a
    specific address or 127.0.0.1. A raw ``SIO_RCVALL`` socket reads the
    broadcasts below the socket layer instead; on Windows it needs the app
    to be running as Administrator. Returns True once it has at least one
    capture socket, False if raw sockets are unavailable (not Windows, or
    the app is not elevated) so the caller can surface a hint."""
    if not hasattr(socket, "SIO_RCVALL"):
        return False
    socks = []
    for ip in list(local_interfaces()) + ["127.0.0.1"]:
        try:
            r = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_IP)
            r.bind((ip, 0))
            r.setsockopt(socket.IPPROTO_IP, socket.IP_HDRINCL, 1)
            r.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            r.setblocking(False)
            socks.append(r)
        except OSError:
            pass
    if not socks:
        return False
    try:
        while not stop.is_set():
            try:
                ready, _, _ = select.select(socks, [], [], 0.3)
            except OSError:
                break
            for r in ready:
                try:
                    pkt, _ = r.recvfrom(65535)
                except OSError:
                    continue
                payload = _udp_payload(pkt, port)
                if payload is None:
                    continue
                call = packet_v4w(payload)
                if call:
                    on_call(call, socket.inet_ntoa(pkt[12:16]))
    finally:
        for r in socks:
            try:
                r.ioctl(socket.SIO_RCVALL, socket.RCVALL_OFF)
            except OSError:
                pass
            try:
                r.close()
            except OSError:
                pass
    return True


def v4w_listener_loop(port, on_call, stop, on_status=None):
    """Listen for VHFCtest4WIN ``<V4W>`` callsign broadcasts on *port*.

    Tries a normal UDP listener first (works when the callbook is started
    before VHFCtest4WIN, or VHFCtest4WIN is not using the port); if the
    bind fails because VHFCtest4WIN already holds the port exclusively,
    falls back to a raw capture socket. Every callsign found is passed to
    ``on_call(callsign, src_ip)`` - the caller filters on ``src_ip`` so a
    multi-op only reacts to its own PC. If neither path works (VHFCtest4WIN
    holds the port and the app is not elevated) *on_status* is called once
    with a short hint. Both callbacks must be safe to call from this
    thread."""
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", port))
        sock.settimeout(0.3)
    except OSError:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        sock = None

    if sock is None:
        if not _v4w_raw_listen(port, on_call, stop) and on_status:
            on_status(
                "VHFCtest4WIN holds UDP {} - run this app as Administrator, "
                "or start it before VHFCtest4WIN".format(port)
            )
        return

    while not stop.is_set():
        try:
            data, addr = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        call = packet_v4w(data)
        if call:
            on_call(call, addr[0])
    try:
        sock.close()
    except OSError:
        pass


# Bump whenever the per-source result shape changes (new field, different
# normalisation, ...) so stale entries from an older build are re-fetched
# once instead of being shown forever.
#   1  original per-source dicts
#   2  + 'cqzone' field, locators upper-cased
CACHE_SCHEMA = 2

# The only per-source fields the display ever reads. The cache stores just
# these, so a contest's worth of entries stays small on disk and in RAM.
_CACHE_FIELDS = ("name", "state", "cqzone", "grid", "country")


class Cache:
    """Small JSON cache for callbook lookups.

    Writes are debounced: ``put()`` only marks the store dirty and the
    file is rewritten at most once every ``FLUSH_INTERVAL`` seconds (plus
    once on close), not on every new callsign - over a big contest that
    turns thousands of full-file rewrites into a few dozen. Set
    ``cache_persist=no`` in the .cfg to keep the cache purely in memory
    (no disk writes at all); it still de-dupes within the session.

    Expired / wrong-schema entries are pruned when the file is loaded, so
    it does not grow without bound across contests.
    """

    FLUSH_INTERVAL = 60  # seconds between disk writes while running

    def __init__(self, path, days, persist=True):
        self.path = path
        self.days = days
        self.persist = bool(persist and path)
        self._data = {}
        self._dirty = False
        self._last_flush = time.time()
        self._load()

    def _load(self):
        if not self.persist:
            return
        try:
            with open(self.path, encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        if not isinstance(data, dict):
            return
        cutoff = time.time() - self.days * 86400
        self._data = {
            call: e
            for call, e in data.items()
            if isinstance(e, dict)
            and e.get("v") == CACHE_SCHEMA
            and e.get("ts", 0) > cutoff
            and isinstance(e.get("sources"), list)
            and e["sources"]
        }

    def get(self, call):
        entry = self._data.get(call)
        if not entry:
            return None
        if (time.time() - entry.get("ts", 0)) > self.days * 86400:
            return None
        # Entries from an older result shape (missing fields, different
        # normalisation) are dropped so the next lookup re-fetches them.
        if entry.get("v") != CACHE_SCHEMA:
            return None
        sources = entry.get("sources")
        if not isinstance(sources, list) or not sources:
            return None
        return sources

    def put(self, call, sources):
        trimmed = [
            {k: (s.get(k) or "") for k in _CACHE_FIELDS} if isinstance(s, dict) else s
            for s in sources
        ]
        self._data[call] = {"ts": time.time(), "v": CACHE_SCHEMA, "sources": trimmed}
        self._dirty = True

    def flush(self, force=False):
        """Write the store to disk if it is dirty and either ``force`` is
        set or the flush interval has elapsed. Driven from the GUI poll
        loop and called once on close; a no-op when persistence is off."""
        if not self._dirty or not self.persist:
            return
        if not force and (time.time() - self._last_flush) < self.FLUSH_INTERVAL:
            return
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self._data, fh, ensure_ascii=False)
            os.replace(tmp, self.path)
            self._dirty = False
            self._last_flush = time.time()
        except OSError:
            pass


def qrzcq_lookup(call, timeout=15):
    """Query QRZCQ.com for a callsign by parsing its public page.

    Returns a dict with 'name'/'qth'/'grid'/'class'/'state'/'cqzone'/
    'country' (any may be empty), or None on network/parse error.
    """
    url = "https://www.qrzcq.com/call/" + urllib.parse.quote(call.upper())
    raw = http_get(url, {"User-Agent": USER_AGENT}, timeout)
    if raw is None:
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
        "grid": normalize_grid(grab("Locator")),
        "class": grab("Class"),
        "state": grab("Federal state"),
        "cqzone": grab("CQ Zone"),
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
    raw = http_get(url, {"User-Agent": HAMQTH_UA}, timeout)
    if raw is None:
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
        "grid": normalize_grid(grab("Grid")),
        "class": grab("Class"),
        "state": grab("US State") or grab("State"),
        "cqzone": grab("CQ") or grab("CQ zone"),
        "country": grab("Country"),
    }


_QRZ_SESSION = {}  # username -> {"key": str, "ts": float}
_QRZ_SESSION_PATH = None  # set by run(); persists the key across restarts


def qrz_session_load(path):
    """Load a previously saved QRZ XML session key.

    The key is valid for ~1 hour, so carrying it across an app restart
    skips the ~0.6 s re-login on the first lookup. Called once at start-up.
    """
    global _QRZ_SESSION_PATH
    _QRZ_SESSION_PATH = path
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            _QRZ_SESSION.update(
                {k: v for k, v in data.items() if isinstance(v, dict)}
            )
    except (OSError, ValueError):
        pass


def _qrz_session_save():
    if not _QRZ_SESSION_PATH:
        return
    try:
        tmp = _QRZ_SESSION_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_QRZ_SESSION, fh)
        os.replace(tmp, _QRZ_SESSION_PATH)
    except OSError:
        pass


def _qrz_login(username, password, timeout=15):
    """Log in to the paid QRZ.com XML Callbook Data service.

    Returns (session_key, error_message). On success a session key that
    is valid for ~1 hour / 500 lookups; on failure the QRZ error text.
    """
    query = urllib.parse.urlencode({"username": username, "password": password})
    url = "https://xml.qrz.com/xml/current/?" + query
    raw = http_get(url, {"User-Agent": USER_AGENT}, timeout)
    if raw is None:
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
        _qrz_session_save()

    params = {"s": key, "callsign": call.upper()}
    url = "https://xml.qrz.com/xml/current/?" + urllib.parse.urlencode(params)
    raw = http_get(url, {"User-Agent": USER_AGENT}, timeout)
    if raw is None:
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
            _qrz_session_save()
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
        "grid": normalize_grid(t("grid")),
        "class": t("class"),
        "state": t("state"),
        "cqzone": t("cqzone"),
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
    raw = http_get(
        url,
        {"User-Agent": HAMQTH_UA, "Accept-Language": "en-US,en;q=0.9"},
        timeout,
    )
    if raw is None:
        return None
    lat = re.search(r'var cs_lat = "([0-9.\-]+)"', raw)
    lon = re.search(r'var cs_lon = "([0-9.\-]+)"', raw)
    grid = ""
    if lat and lon:
        grid = normalize_grid(maidenhead_from_latlon(lat.group(1), lon.group(1)))
    return {
        "name": "",
        "qth": "",
        "grid": grid,
        "class": "",
        "state": "",
        "cqzone": "",
        "country": "",
    }


def app_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def load_config(path):
    """Parse the small ``key = value`` .cfg file.

    Blank lines, ``#`` comments and ``[section]`` headers are ignored.
    Returns a lower-cased dict; a missing or unreadable file yields ``{}``.
    """
    settings = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith(("#", "[")) or "=" not in line:
                    continue
                key, _, val = [p.strip() for p in line.partition("=")]
                settings[key.lower()] = val
    except OSError:
        pass
    return settings


def run(app_class, config_name, cache_name, description, always_vhfctest=False):
    """Shared entry point for the apps: parse the CLI args and config file,
    build ``app_class`` (CallbookApp or a subclass) and run the Tk loop.
    Only the file names and the ArgumentParser description differ between
    the HF and VHF apps. ``always_vhfctest=True`` turns the VHFCtest4WIN
    6767 feed on regardless of ``vhfctest_share``; ``VHFcallbook`` passes a
    value computed from its own config there (feed on unless
    ``vhfctest_share=no``), which is why the feed defaults differ per app.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--config",
        default=os.path.join(app_dir(), config_name),
        help="config file (same folder as the exe by default)",
    )
    # Set by VHFcallbook's elevated self-relaunch; only used to stop that
    # relaunch from looping. Hidden from --help.
    parser.add_argument("--elevated", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    settings = load_config(args.config)

    def as_int(key, default):
        try:
            return int(settings[key])
        except (KeyError, ValueError):
            return default

    port = as_int("udp_port", args.port)
    cache_days = as_int("cache_days", DEFAULT_CACHE_DAYS)
    cache_persist = settings.get("cache_persist", "yes").strip().lower() not in (
        "no", "false", "0", "off",
    )
    cache_file = os.path.join(app_dir(), cache_name)
    if "cache_file" in settings:
        cache_file = os.path.abspath(
            os.path.join(os.path.dirname(args.config), settings["cache_file"])
        )

    # Start-up self-test callsign. Empty string = disabled (selftest=no).
    selftest_call = settings.get("selftest_call", PRECHECK_CALL).strip().upper()
    if settings.get("selftest", "yes").strip().lower() in (
        "no", "false", "0", "off",
    ):
        selftest_call = ""

    # VHFCtest4WIN pre-log callsign feed on its multi-op sharing port
    # (6767). always_vhfctest is set by VHFcallbook (to a value it computed
    # from vhfctest_share, default yes); otherwise the feed is opt-in via
    # vhfctest_share on any VHFCTEST_CAPABLE app.
    vhfctest_port = 0
    share = settings.get("vhfctest_share", "no").strip().lower() in (
        "yes", "true", "1", "on",
    )
    if always_vhfctest or (getattr(app_class, "VHFCTEST_CAPABLE", False) and share):
        vhfctest_port = as_int("vhfctest_port", 6767)

    # Side files live next to the cache: the remembered window position
    # and the QRZ XML session key (shared by both apps - same QRZ account).
    data_dir = os.path.dirname(cache_file)
    win_file = os.path.splitext(cache_file)[0] + "_window.json"
    qrz_session_load(os.path.join(data_dir, "qrz_session.json"))

    # Optional QRZ.com XML service (paid subscription). Empty credentials
    # keep QRZ out of the lookup chain.
    root = tk.Tk()
    app_class(
        root,
        cache_file,
        port,
        cache_days,
        settings.get("qrz_username", ""),
        settings.get("qrz_password", ""),
        win_file,
        cache_persist,
        vhfctest_port,
        selftest_call,
    )
    root.mainloop()


class CallbookApp:
    # Shown in the title bar. The VHF subclass overrides it with its own
    # module version (they are released on separate version numbers).
    VERSION = __version__
    APP_TITLE = "N1MM Callbook"
    # Fields the main area shows per source, joined with "/" into one token
    # per slot. Every source contributes its own token and ALL of them are
    # shown side by side (e.g. "MA/5 MA/5 MA/5"), so the operator sees when
    # sources disagree and can pick the right value for the exchange. The
    # HF app shows US state + CQ zone; the VHF variant only the locator.
    SLOT_FIELDS = ("state", "cqzone")
    # String placed between the per-source slots. HF keeps a plain space
    # (the name already has a " - " after it); VHF uses " - " so three
    # locators read as "JN76HD - JN76HD - JN76HD", not a run-on.
    SLOT_SEP = " "
    # Show the operator name too (printed once, shortest of the sources).
    SHOW_NAME = True
    # Append " (Country)" to that name for a non-US (DX) call. HF does this;
    # the VHF variants turn it off - they stay locator-focused.
    DX_COUNTRY = True
    # When every source that answered returns the same slot value, show it
    # just once in a larger font ("JN76HD") instead of repeating it per
    # source ("JN76HD - JN76HD - JN76HD"). Off on HF, on for the VHF apps.
    COLLAPSE_ON_AGREE = False
    # Lookup sources run in order; every source's value is kept separately.
    # Variants can add more sources.
    LOOKUP_CHAIN = (qrzcq_lookup, hamqth_lookup)
    # Whether this variant can take the optional VHFCtest4WIN pre-log
    # callsign feed (see v4w_listener_loop). VHF only.
    VHFCTEST_CAPABLE = False

    def __init__(self, root, cache_path, port, cache_days, qrz_username="",
                 qrz_password="", win_file=None, cache_persist=True,
                 vhfctest_port=0, selftest_call=""):
        self.root = root
        self.port = port
        self.vhfctest_port = vhfctest_port
        self.cache = Cache(cache_path, cache_days, cache_persist)
        self.win_file = win_file
        self.current = None
        self._debounce = None
        # QRZ XML takes slot 0 (shown left-most) when credentials are
        # present, otherwise the free sources run without it. All sources
        # are queried in parallel, so each slot fills as soon as that
        # source answers regardless of its position in the chain.
        chain = []
        if qrz_username and qrz_password:
            chain.append(
                functools.partial(
                    qrz_lookup, username=qrz_username, password=qrz_password
                )
            )
        chain.extend(self.LOOKUP_CHAIN)
        self.lookup_chain = tuple(chain)
        self.source_labels = tuple(source_label(fn) for fn in self.lookup_chain)
        # Background lookups push per-source results here; the GUI drains
        # the queue every 100ms and renders each slot as it arrives.
        self._inbox = []
        # VHFCtest4WIN listener thread appends the callsign being typed
        # here; drained on the GUI thread by _poll_inbox (same cross-thread
        # hand-off pattern as _inbox - never touch Tk from that thread).
        self._v4w_inbox = []
        self._v4w_status = None  # one-shot hint text from the v4w listener
        # Start-up self-test (see _start_precheck). Empty call = disabled.
        self._selftest_call = normalize_call(selftest_call)
        self._precheck = None       # per source: None = pending, (status, ms)
        self._precheck_inbox = []   # worker threads -> GUI, like _inbox
        self._precheck_active = False
        self._slots = None
        self._pending_inds = set()
        self.local = set(local_interfaces())
        self.local.add("127.0.0.1")
        self._build()
        self._restore_window()
        self.stop = threading.Event()
        self.thread = threading.Thread(
            target=listener_loop,
            args=("0.0.0.0", port, self.on_packet, self.stop),
            daemon=True,
        )
        self.thread.start()
        # Optional second feed: VHFCtest4WIN shares the callsign being
        # typed (before the QSO is logged) on its own UDP port.
        self.v4w_thread = None
        if self.vhfctest_port:
            self.v4w_thread = threading.Thread(
                target=v4w_listener_loop,
                args=(self.vhfctest_port, self._on_v4w_call, self.stop,
                      self._on_v4w_status),
                daemon=True,
            )
            self.v4w_thread.start()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(100, self._poll_inbox)
        if self._selftest_call:
            self.root.after(150, self._start_precheck)

    def _build(self):
        self.root.title("{}  -  UDP {}  v{}".format(self.APP_TITLE, self.port, self.VERSION))
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
        # The "?" icon opens the project page in the default browser.
        try:
            import webbrowser

            webbrowser.open(HELP_URL)
        except Exception:
            pass

    _GEOM_RE = re.compile(r"^\d+x\d+([+-]\d+)([+-]\d+)$")

    def _restore_window(self):
        # Re-apply the last on-screen position (not the size - the window
        # sizes itself to its content, which may change between versions).
        if not self.win_file:
            return
        try:
            with open(self.win_file, encoding="utf-8") as fh:
                geom = json.load(fh).get("geometry", "")
        except (OSError, ValueError):
            return
        m = self._GEOM_RE.match(geom or "")
        if m:
            self.root.geometry("{}{}".format(*m.groups()))

    def _save_window(self):
        if not self.win_file:
            return
        try:
            tmp = self.win_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"geometry": self.root.geometry()}, fh)
            os.replace(tmp, self.win_file)
        except OSError:
            pass

    def on_packet(self, src, data):
        # Only look up callsigns from the local computer (this PC), ignoring
        # broadcasts from other stations on the network.
        if src not in self.local:
            return
        call = packet_callsign(data)
        if call:
            self._handle_call(call)

    def _on_v4w_call(self, call, src):
        # Runs on the VHFCtest4WIN listener thread. VHFCtest4WIN broadcasts
        # to the whole multi-op subnet, so ignore datagrams from other
        # PCs - this callbook only follows its own operator's entry field
        # (same local-computer-only rule as on_packet). Then just queue the
        # callsign (a plain list append is safe); _poll_inbox picks it up
        # on the GUI thread.
        if src not in self.local:
            return
        self._v4w_inbox.append(call)

    def _on_v4w_status(self, msg):
        # Listener thread: stash a one-off hint (e.g. "run as Administrator")
        # for _poll_inbox to show in the footer on the GUI thread.
        self._v4w_status = msg

    def _handle_call(self, call):
        # Shared path for a worked callsign from any feed (the N1MM
        # LookupInfo/ContactInfo packet, or a VHFCtest4WIN <V4W> broadcast).
        call = normalize_call(call)
        if not call or call.lower().startswith("test"):
            return
        self._precheck_active = False  # a real callsign supersedes the self-test
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
        # No "already fetching" guard: if the operator retypes the call
        # while a lookup is in flight, we just start a fresh one. The old
        # threads still finish but their results are dropped by the
        # `call != self.current` check in _poll_inbox.
        self._slots = [None] * len(self.lookup_chain)
        self._pending_inds = set(range(len(self.lookup_chain)))
        self._render_slots(call, self._slots, self._pending_inds)
        self._do_lookup(call)

    def _do_lookup(self, call):
        # Fires every source at once (one thread each) so a slow source
        # never holds up a fast one; returns immediately. Each result is
        # posted to the GUI the moment that source answers; the slot index
        # is kept, so the display still reads in chain order (QRZ XML,
        # QRZCQ, HamQTH, ...) - it just fills in as fast as each source can
        # reply instead of waiting for the whole chain.
        def run(i, fn):
            try:
                res = fn(call)
            except Exception:
                res = None
            self._inbox.append((call, i, res))

        for i, fn in enumerate(self.lookup_chain):
            threading.Thread(target=run, args=(i, fn), daemon=True).start()

    def _start_precheck(self):
        # One-off start-up probe: query every source once for the self-test
        # callsign and show, line by line, whether it answered and how long
        # it took. Skipped if a real callsign already came in.
        if self.current or not self._selftest_call:
            return
        self._precheck = [None] * len(self.lookup_chain)
        self._precheck_active = True
        self.call_label.configure(text="self-test: " + self._selftest_call)
        self._render_precheck()

        def run(i, fn):
            t0 = time.perf_counter()
            try:
                res = fn(self._selftest_call)
            except Exception:
                res = None
            ms = (time.perf_counter() - t0) * 1000.0
            if res is None:
                status = "FAIL"          # network / HTTP error - source down
            elif any((res or {}).values()):
                status = "OK"            # answered and parsed to real fields
            else:
                status = "no data"      # reachable, but no record for this call
            self._precheck_inbox.append((i, status, ms))

        for i, fn in enumerate(self.lookup_chain):
            threading.Thread(target=run, args=(i, fn), daemon=True).start()

    def _render_precheck(self):
        # One monospaced line per source: "QRZCQ   OK      181 ms".
        if not self._precheck_active or self.current or self._precheck is None:
            return
        lines = []
        for lbl, v in zip(self.source_labels, self._precheck):
            if v is None:
                lines.append("{:<7} {}".format(lbl, SLOT_PENDING))
            else:
                status, ms = v
                lines.append("{:<7} {:<7} {:4.0f} ms".format(lbl, status, ms))
        done = all(v is not None for v in self._precheck)
        failed = done and any(v[0] == "FAIL" for v in self._precheck)
        all_ok = done and all(v[0] == "OK" for v in self._precheck)
        self.canvas.configure(bg=COLOR_ACTIVE if (not done or failed) else COLOR_IDLE)
        self.canvas.itemconfigure(
            self.main_id,
            text="\n".join(lines),
            fill=TEXT_AGREE if all_ok else TEXT_DEFAULT,
            font=("Consolas", 9, "bold"),  # small + monospaced: up to 4 lines
        )

    def _finish_precheck(self):
        # Drop the probe result and return to the idle placeholder, unless a
        # real callsign already took over the canvas while it was showing.
        if not self._precheck_active:
            return
        self._precheck_active = False
        results = self._precheck or []
        oks = sum(1 for v in results if v and v[0] == "OK")
        fails = sum(1 for v in results if v and v[0] == "FAIL")
        self._precheck = None
        if self.current:
            return
        if fails:
            summary = "self-test: {} source(s) FAILED".format(fails)
        else:
            summary = "self-test: {}/{} sources OK".format(oks, len(results))
        self.call_label.configure(text=summary)
        self.canvas.configure(bg=COLOR_IDLE)
        self.canvas.itemconfigure(
            self.main_id, text="—", fill=TEXT_DEFAULT,
            font=("Segoe UI", FONT_SIZE_NAME, "bold"),
        )

    def _poll_inbox(self):
        # GUI thread: drains results posted by the worker and renders them.
        # First fold in any callsign the VHFCtest4WIN listener queued - only
        # the most recent matters (it fires once per keystroke), and
        # _handle_call debounces the lookup from there.
        if self._v4w_inbox:
            latest = self._v4w_inbox[-1]
            self._v4w_inbox.clear()
            try:
                self._handle_call(latest)
            except Exception:
                pass
        if self._v4w_status:
            msg, self._v4w_status = self._v4w_status, None
            if not self.current:  # don't clobber a lookup already on screen
                self.call_label.configure(text=msg)
        if self._precheck_inbox:
            while self._precheck_inbox:
                i, status, ms = self._precheck_inbox.pop(0)
                if self._precheck is not None and i < len(self._precheck):
                    self._precheck[i] = (status, ms)
            self._render_precheck()
            if self._precheck_active and self._precheck is not None and all(
                v is not None for v in self._precheck
            ):
                self.root.after(PRECHECK_HOLD_MS, self._finish_precheck)
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
                    # Only cache a complete, error-free set of results.
                    if not any(s is None for s in self._slots):
                        self.cache.put(call, list(self._slots))
                self._render_slots(call, self._slots, self._pending_inds)
        except Exception:
            pass
        self.cache.flush()  # debounced - actually writes at most once a minute
        if not self.stop.is_set():
            self.root.after(100, self._poll_inbox)

    def _source_field(self, info, key):
        if not info:
            return ""
        v = (info.get(key) or "").strip()
        # Upper-case the locator on read too, so a stale cache entry from
        # an older build still displays consistently with the others.
        if key == "grid":
            v = v.upper()
        return v

    _US_NAMES = ("united states", "usa", "united states of america", "us")

    def _is_dx(self, sources):
        # True when at least one source reports a non-US country - used to
        # switch the HF window from "state" mode to "name + country".
        for s in sources:
            c = self._source_field(s, "country").lower()
            if c and c not in self._US_NAMES:
                return True
        return False

    def _source_value(self, info):
        # One slot token, e.g. "MA/5" (state + CQ zone) or just "5" for a
        # DX station that has no US state. Empty when the source gave none
        # of the SLOT_FIELDS.
        if not info:
            return ""
        parts = []
        for key in self.SLOT_FIELDS:
            v = self._source_field(info, key)
            # The state column is US-only. When the source reports a non-US
            # country its "state" is a foreign subdivision (e.g. QRZ XML
            # gives "HE" for a DL call) - drop it, but keep the CQ zone,
            # which is meaningful worldwide.
            if v and key == "state":
                country = self._source_field(info, "country").lower()
                if country and country not in self._US_NAMES:
                    v = ""
            if v:
                parts.append(v)
        return "/".join(parts)

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

    def _best_country(self, sources):
        # Country, printed once - the first source in chain order that
        # carries one. Used for DX stations, where there is no US state.
        for s in sources:
            c = self._source_field(s, "country")
            if c:
                return c
        return ""

    def _render_slots(self, call, slots, pending):
        # Renders the main area at any stage of the lookup. Each slot maps
        # to one source in chain order; a slot still being queried shows
        # "…" and one that answered with nothing shows "·", so results
        # appear as they arrive. When every source that answered agrees the
        # text turns light green. Example final lines:
        #   HF, US:   "Dave - MA/5 MA/5 MA/5"      (state / CQ zone per source)
        #   HF, DX:   "Hans (Germany) - 14 14 14"
        #   VHF:      "Hans - JN76GB - JN76HD - JN76HD"   (sources disagree)
        #   VHF agree: "Hans - JN76HD"  (collapsed, larger font, green)
        finished = [slots[i] for i in range(len(slots)) if i not in pending]
        any_data = any(self._source_value(s) for s in finished if s)
        vals = []
        for i in range(len(slots)):
            if i in pending:
                vals.append(SLOT_PENDING)
            else:
                s = slots[i]
                v = self._source_value(s) if s else ""
                vals.append(v if v else SLOT_EMPTY)
        all_done = not pending
        have_name = self.SHOW_NAME and bool(self._best_name(finished))
        # Every source that answered with a real value - if they all match
        # (and there are at least two), the operator can trust it: green.
        real_vals = [v for v in vals if v not in (SLOT_EMPTY, SLOT_PENDING)]
        agree = all_done and len(real_vals) >= 2 and len(set(real_vals)) == 1
        # VHF: when they all agree, show the value once (larger) instead of
        # "JN76HD - JN76HD - JN76HD".
        collapsed = agree and self.COLLAPSE_ON_AGREE
        fill = TEXT_DEFAULT
        big = False
        if not finished:
            text = SLOT_PENDING
            bg = COLOR_ACTIVE
        elif any_data or have_name:
            line = real_vals[0] if collapsed else self.SLOT_SEP.join(vals)
            if self.SHOW_NAME:
                name = self._best_name(finished)
                prefix = name
                # DX station: prepend the country, since there is no US
                # state (the slots then carry just the CQ zone).
                if self.DX_COUNTRY and self._is_dx(finished):
                    country = self._best_country(finished)
                    if country:
                        prefix = "{} ({})".format(name, country) if name else country
                if prefix and real_vals:
                    text = "{} - {}".format(prefix, line)
                else:
                    text = prefix or line
            else:
                text = line
            bg = COLOR_ACTIVE
            if agree:
                fill = TEXT_AGREE
            big = collapsed and len(text) <= FONT_BIG_MAXLEN
        elif not all_done:
            text = SLOT_PENDING
            bg = COLOR_ACTIVE
        else:
            text = "lookup failed" if all(s is None for s in slots) else "no data"
            bg = COLOR_IDLE
        self.canvas.configure(bg=bg)
        self.canvas.itemconfigure(self.main_id, text=text, fill=fill)
        font = ("Segoe UI", FONT_SIZE_BIG, "bold") if big else self._font_for(len(text))
        self.canvas.itemconfigure(self.main_id, font=font)

    def _font_for(self, length):
        for limit, size in FONT_SIZES:
            if length <= limit:
                return ("Segoe UI", size, "bold")
        return ("Segoe UI", 11, "bold")

    def on_close(self):
        self._save_window()
        self.cache.flush(force=True)
        self.stop.set()
        self.root.destroy()


def main():
    run(
        CallbookApp,
        "callbook.cfg",
        "callbook_cache.json",
        "N1MM Logger+ contest callbook",
    )


if __name__ == "__main__":
    main()
