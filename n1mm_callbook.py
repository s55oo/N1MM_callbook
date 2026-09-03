# SPDX-License-Identifier: Unlicense
"""Callbooker engine - callsign lookup, the sources, the cache, the window.

Not run directly. ``Callbooker.py`` imports this module for ``CallbookApp``
(the always-on-top Tkinter window and all lookup orchestration), ``run()``
(the entry point), and the source functions. Every source is queried in
parallel and ALL of its values are shown side by side, so disagreements
stand out and the operator can pick the right one.

QRZCQ.com is a public, free callbook that needs no account or API key -
each callsign has a page at https://www.qrzcq.com/call/<CALL> whose
lookup info is parsed from the HTML. HamQTH.com backs it up; QRZ.com is
the paid XML service when credentials are configured, else its public
/db/ page for the locator. Lookups are cached locally in a JSON file.

Made by S55OO with AI assistance.
"""

__version__ = "1.7"

import argparse
import base64
import functools
import gzip
import http.client
import json
import os
import random
import re
import select
import socket
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
import urllib.parse
import xml.etree.ElementTree as ET

from mqtt_client import MqttPublisher, lookup_payload

USER_AGENT = "Mozilla/5.0 Callbooker/1.7"
HAMQTH_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

DEFAULT_PORT = 12060
DEFAULT_CACHE_DAYS = 30

# LAN cache sharing (see dev/lan-cache-sharing.md). A dedicated UDP port -
# NOT 12060, which is the loggers' own multi-op network port - carries one
# small JSON packet type between Callbooker instances on a LAN. On a local
# cache miss an instance asks the LAN and only queries the callbook
# websites if no peer answers within the grace period.
LAN_SHARE_PORT = 6768
LAN_PROTO = 1          # the "cbshare" marker / on-wire protocol version
LAN_GRACE_MS = 50      # wait this long for a peer before the HTTP lookup
LAN_SYNC_MIN_INTERVAL = 30   # seconds; ignore repeat sync requests inside this
LAN_SYNC_SELF_HOLD = 10      # don't answer others' sync while catching up ourselves
LAN_SYNC_RATE = 200         # entry packets per second when replaying the cache
LAN_SYNC_CAP = 1000         # most entries a peer will replay for one sync
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
FONT_SIZE_BIG = 26
# The main result line is drawn at the largest of these sizes whose
# rendered width actually fits the canvas (measured, not guessed from the
# character count) - so a collapsed single token, a short disagreement,
# and a short "name (Country) - zone" DX line all get FONT_SIZE_BIG, while
# a long side-by-side row steps down until it fits.
FONT_LADDER = (FONT_SIZE_BIG, 23, 20, 18, 16, 14, 12)

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
    "qrz_lookup": "QRZ",
    "qrzcq_lookup": "QRZCQ",
    "hamqth_lookup": "HamQTH",
}


def source_label(fn):
    """Short human name for a lookup-chain entry.

    Unwraps the ``functools.partial`` that ``__init__`` builds for the
    QRZ source so the self-test can label every slot.
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


def packet_freq_mhz(data):
    """Operating frequency in MHz from an N1MM broadcast packet, or None.

    N1MM carries the frequency in ``<rxfreq>`` / ``<txfreq>`` (on
    LookupInfo / ContactInfo) and ``<Freq>`` / ``<TXFreq>`` (on RadioInfo),
    all in *tens of hertz* - e.g. ``14430000`` is 144.300 MHz. Callbooker
    uses this to choose the HF vs VHF view per callsign.
    """
    raw = data.decode("utf-8", errors="replace")
    start = raw.find("<")
    if start < 0:
        return None
    try:
        root = ET.fromstring(raw[start:])
    except ET.ParseError:
        return None
    wanted = ("rxfreq", "txfreq", "freq")
    for el in root.iter():
        if el.tag.lower() in wanted and el.text and el.text.strip():
            try:
                tens_hz = float(el.text.strip())
            except ValueError:
                continue
            if tens_hz > 0:
                return tens_hz / 100000.0  # tens of Hz -> MHz
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


def _lan_trim(sources):
    """Reduce a list of per-source result dicts to just ``_CACHE_FIELDS``.

    The same shape the cache stores on disk - so a LAN gossip packet
    carries only the displayed fields, never a QRZ login or session key.
    Non-dict / None slots are dropped.
    """
    return [
        {k: (s.get(k) or "") for k in _CACHE_FIELDS}
        for s in sources
        if isinstance(s, dict)
    ]


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
        """Store a freshly resolved result. Returns the timestamp stored
        (used as the ``ts`` of the LAN gossip packet for this entry)."""
        now = time.time()
        self._data[call] = {
            "ts": now, "v": CACHE_SCHEMA, "sources": _lan_trim(sources),
        }
        self._dirty = True
        return now

    def merge(self, call, sources, ts):
        """Store an entry received from a LAN peer, but only if it is newer
        than what we already have (or we have nothing). Returns True if it
        was stored. The freshness check means a real re-work always wins
        over a stale gossip entry for the same call."""
        if not call or not isinstance(sources, list) or not sources:
            return False
        existing = self._data.get(call)
        if existing and existing.get("ts", 0) >= ts:
            return False
        self._data[call] = {
            "ts": ts, "v": CACHE_SCHEMA, "sources": _lan_trim(sources),
        }
        self._dirty = True
        return True

    def get_with_ts(self, call):
        """``(sources, ts)`` for a fresh cache entry, or None - for
        answering a LAN peer's call-request with the timestamp intact."""
        sources = self.get(call)
        if sources is None:
            return None
        return sources, self._data[call].get("ts", 0)

    def items_since(self, since):
        """``(call, sources, ts)`` for every fresh entry newer than
        *since*, newest first - the payload of a startup sync replay."""
        cutoff = time.time() - self.days * 86400
        out = [
            (call, e["sources"], e["ts"])
            for call, e in self._data.items()
            if e.get("v") == CACHE_SCHEMA
            and e.get("ts", 0) > max(since, cutoff)
            and isinstance(e.get("sources"), list) and e["sources"]
        ]
        out.sort(key=lambda t: t[2], reverse=True)
        return out

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


class LANShare:
    """UDP-broadcast callbook-cache sharing between Callbooker instances.

    Design and rationale: ``dev/lan-cache-sharing.md``. One dedicated port
    (default 6768 - *not* the loggers' 12060), one small JSON packet type
    with a ``cbshare`` marker so stray traffic is ignored. Three packet
    shapes:

    * **entry** ``{"cbshare",  "call", "sources", "ts", "schema"}`` - a
      resolved callsign. Broadcast after an HTTP lookup and in reply to a
      call-request; received ones are merged into the local cache
      (newer-wins) and never re-broadcast.
    * **call-request** ``{"cbshare", "req": "call", "call"}`` - "does
      anyone have this call?", sent on a local cache miss.
    * **sync-request** ``{"cbshare", "req": "sync", "since"}`` - sent once
      on start-up; every peer replays its cache as entry packets
      (newest-first, rate-limited, staggered, capped).

    Only ``_CACHE_FIELDS`` go on the wire - never a QRZ login or session
    key. A peer on a different ``CACHE_SCHEMA`` is ignored.

    The listener thread only ever calls ``on_entry(call, sources, ts)``,
    which must be a cheap thread-safe hand-off (a list append) - the GUI
    thread does the cache merge and any redraw, same rule as the other
    feeds.
    """

    def __init__(self, port, cache, on_entry, local_ips, bcast=""):
        self.port = port
        self.cache = cache
        self.on_entry = on_entry
        self.local = set(local_ips)
        self.stop = threading.Event()
        self._sock = None
        self._targets = self._broadcast_targets(bcast)
        self._last_sync_served = 0.0
        self._own_sync_ts = 0.0
        self._thread = threading.Thread(target=self._listen, daemon=True)

    @staticmethod
    def _broadcast_targets(extra=None):
        """255.255.255.255 plus each local interface's /24 directed
        broadcast. The limited broadcast alone can egress the wrong
        adapter on a multi-homed PC (VirtualBox / Hyper-V / a VPN), so we
        also aim at the real LAN's <net>.255 explicitly. `extra` overrides
        from `lan_share_bcast` in the .cfg for an unusual netmask."""
        targets = ["255.255.255.255"]
        for ip in local_interfaces():
            parts = ip.split(".")
            if len(parts) == 4 and all(p.isdigit() for p in parts):
                directed = ".".join(parts[:3]) + ".255"
                if directed not in targets:
                    targets.append(directed)
        for addr in (extra or "").replace(",", " ").split():
            if addr and addr not in targets:
                targets.append(addr)
        return targets

    def start(self):
        """Bind the port and start listening. Returns False if the port
        cannot be bound (feature then simply stays off)."""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.bind(("", self.port))
            sock.settimeout(0.3)
        except OSError:
            return False
        self._sock = sock
        self._thread.start()
        return True

    def close(self):
        self.stop.set()

    # -- outgoing ------------------------------------------------------------

    def _send(self, obj):
        if self._sock is None:
            return
        try:
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            return
        for addr in self._targets:
            try:
                self._sock.sendto(data, (addr, self.port))
            except OSError:
                pass

    def broadcast_entry(self, call, sources, ts):
        self._send({
            "cbshare": LAN_PROTO, "call": call,
            "sources": _lan_trim(sources), "ts": ts, "schema": CACHE_SCHEMA,
        })

    def request_call(self, call):
        self._send({"cbshare": LAN_PROTO, "req": "call", "call": call})

    def request_sync(self):
        self._own_sync_ts = time.time()
        self._send({"cbshare": LAN_PROTO, "req": "sync", "since": 0})

    # -- incoming ----------------------------------------------------------

    def _listen(self):
        while not self.stop.is_set():
            try:
                data, addr = self._sock.recvfrom(65535)
            except socket.timeout:
                continue
            except OSError:
                break
            try:
                self._handle(data, addr[0])
            except Exception:
                pass
        try:
            self._sock.close()
        except OSError:
            pass

    def _handle(self, data, src):
        if len(data) > 60000:
            return
        try:
            msg = json.loads(data.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return
        if not isinstance(msg, dict) or msg.get("cbshare") != LAN_PROTO:
            return
        req = msg.get("req")
        if req == "call":
            self._serve_call(msg)
        elif req == "sync":
            self._serve_sync(msg, src)
        elif "sources" in msg:
            self._recv_entry(msg)

    def _recv_entry(self, msg):
        if msg.get("schema") != CACHE_SCHEMA:
            return
        call = normalize_call(str(msg.get("call") or ""))
        sources = msg.get("sources")
        try:
            ts = float(msg.get("ts") or 0)
        except (TypeError, ValueError):
            return
        if not call or not isinstance(sources, list) or not sources:
            return
        if ts <= 0 or ts > time.time() + 3600:   # 0 / far-future -> junk
            return
        self.on_entry(call, sources, ts)

    def _serve_call(self, msg):
        call = normalize_call(str(msg.get("call") or ""))
        if not call:
            return
        hit = self.cache.get_with_ts(call)
        if hit is not None:
            self.broadcast_entry(call, hit[0], hit[1])

    def _serve_sync(self, msg, src):
        now = time.time()
        if src in self.local:
            return   # our own request, echoed back to us
        if now - self._own_sync_ts < LAN_SYNC_SELF_HOLD:
            return   # we asked for a sync ourselves just now - still catching up
        if now - self._last_sync_served < LAN_SYNC_MIN_INTERVAL:
            return   # answered a sync very recently; let that one land
        self._last_sync_served = now
        try:
            since = float(msg.get("since") or 0)
        except (TypeError, ValueError):
            since = 0.0
        entries = self.cache.items_since(since)[:LAN_SYNC_CAP]
        if entries:
            threading.Thread(
                target=self._replay, args=(entries,), daemon=True
            ).start()

    def _replay(self, entries):
        time.sleep(random.uniform(0.0, 0.5))   # stagger vs. other responders
        gap = 1.0 / LAN_SYNC_RATE
        for call, sources, ts in entries:
            if self.stop.is_set():
                return
            self.broadcast_entry(call, sources, ts)
            time.sleep(gap)


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
    country, ...) and is used as an additional source - its "Grid" row
    carries the QRA/maidenhead locator for the VHF view.

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


# Which path qrz_lookup last took: "xml" (paid XML API) or "web" (public
# /db/ page). Read by the start-up self-test so it can show the QRZ status.
_QRZ_TIER = ""
_QRZ_SUBEXP = ""  # QRZ XML subscription expiry string, when known


def qrz_lookup(call, username="", password="", timeout=15):
    """QRZ.com lookup - **one** source, never two.

    Uses the paid QRZ.com XML API when credentials are configured and the
    subscription/session is usable; otherwise falls back to the public
    ``/db/<CALL>`` page (the maidenhead locator computed from the
    coordinates it embeds - no login, no account). Returns a dict like
    ``qrzcq_lookup`` or ``None``. Sets the module ``_QRZ_TIER`` to the path
    actually used.
    """
    global _QRZ_TIER
    if username and password:
        info = _qrz_xml_lookup(call, username, password, timeout)
        if info is not None:
            _QRZ_TIER = "xml"
            return info
    info = _qrz_web_lookup(call, timeout)
    if info is not None:
        _QRZ_TIER = "web"
    return info


def _qrz_xml_lookup(call, username, password, timeout=15):
    """Look up a callsign on the paid QRZ.com XML service.

    Needs a QRZ XML subscription; credentials come from the config file.
    Reuses the session key, re-logging in when it expired or the server
    rejected it. Returns a dict like qrzcq_lookup, or None on any failure
    (no subscription, bad login, network error, no record).
    """
    global _QRZ_SUBEXP
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
    _QRZ_SUBEXP = (root.findtext("Session/SubExp") or "").strip()
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


def _qrz_web_lookup(call, timeout=15):
    """Grab the locator from the public QRZ.com /db/<CALL> page.

    The QRZ fallback for when the paid XML API is not available. QRZ only
    shows its full Detail tab ("Grid square") to logged-in users, but
    every callsign page embeds the station's coordinates as cs_lat /
    cs_lon - so the 6-char maidenhead locator can be computed for free,
    without any account or subscription.

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
    """Entry point: parse the CLI args and config file, build ``app_class``
    (``CallbookerApp``) and run the Tk loop. ``always_vhfctest`` turns the
    VHFCtest4WIN 6767 feed on regardless of ``vhfctest_share``; Callbooker
    passes a value it computed from its own config (feed on unless
    ``vhfctest_share=no``).
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--config",
        default=os.path.join(app_dir(), config_name),
        help="config file (same folder as the exe by default)",
    )
    # Set by Callbooker's elevated self-relaunch; only used to stop that
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
    # (6767). Callbooker passes always_vhfctest computed from vhfctest_share
    # (default yes); the flag is what forces the second listener on.
    vhfctest_port = 0
    share = settings.get("vhfctest_share", "no").strip().lower() in (
        "yes", "true", "1", "on",
    )
    if always_vhfctest or (getattr(app_class, "VHFCTEST_CAPABLE", False) and share):
        vhfctest_port = as_int("vhfctest_port", 6767)

    # LAN cache sharing (dev/lan-cache-sharing.md). On by default; every
    # Callbooker on the LAN shares resolved callsigns so only one PC ever
    # queries the callbook sites for a given call. lan_share=no turns it off.
    lan_share_port = 0
    if settings.get("lan_share", "yes").strip().lower() not in (
        "no", "false", "0", "off",
    ):
        lan_share_port = as_int("lan_share_port", LAN_SHARE_PORT)
    # Extra broadcast address(es) for LAN sharing, if the auto-detected
    # 255.255.255.255 + <iface>/24 targets miss (an unusual netmask, or a
    # segment the sender's interface list doesn't cover).
    lan_share_bcast = settings.get("lan_share_bcast", "")

    # Side files live next to the cache: the remembered window position /
    # view and the QRZ XML session key.
    data_dir = os.path.dirname(cache_file)
    win_file = os.path.splitext(cache_file)[0] + "_window.json"
    qrz_session_load(os.path.join(data_dir, "qrz_session.json"))

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
        lan_share_port,
        settings,
        os.path.dirname(os.path.abspath(args.config)),
        lan_share_bcast,
    )
    root.mainloop()


class CallbookApp:
    # The window + all lookup orchestration. ``CallbookerApp`` in
    # Callbooker.py subclasses this and flips the display attributes below
    # (SLOT_FIELDS / SLOT_SEP / DX_COUNTRY / lookup_chain) at runtime to
    # switch between the HF (state / CQ zone) and VHF (locator) views. The
    # defaults here are the HF view.
    VERSION = __version__
    APP_TITLE = "Callbooker"
    # Fields the main area shows per source, joined with "/" into one token
    # per slot. Every source contributes its own token and ALL of them are
    # shown side by side (e.g. "MA/5 MA/5 MA/5"), so the operator sees when
    # sources disagree and can pick the right value. HF view: US state +
    # CQ zone; VHF view: the locator only.
    SLOT_FIELDS = ("state", "cqzone")
    # String between the per-source slots. HF keeps a plain space (the name
    # already has " - " after it); VHF uses " - " so the locators read as
    # "JN76HD - JN76HD - JN76HD", not a run-on.
    SLOT_SEP = " "
    # Show the operator's first name too (printed once, in front).
    SHOW_NAME = True
    # Append " (Country)" to that name for a non-US (DX) call. Callbooker
    # turns this off in both views - the CQ zone is the multiplier.
    DX_COUNTRY = True
    # When every source that answered returns the same slot value, show it
    # once in a larger font instead of repeating it: "Fred - MA/5" not
    # "Fred - MA/5 MA/5 MA/5", "Hans - JN76HD" not "Hans - JN76HD - ...".
    COLLAPSE_ON_AGREE = True
    # The free sources, queried in order; every source's value is kept
    # separately. A QRZ slot is prepended by __init__ / _apply_mode.
    LOOKUP_CHAIN = (qrzcq_lookup, hamqth_lookup)
    # Give QRZ a slot even with no XML credentials (the public /db/ page
    # still yields the locator). Off in the HF view - anonymous QRZ has
    # nothing it shows; on in the VHF view, where the locator is the point.
    QRZ_WEB_FALLBACK = False
    # Whether the app takes the VHFCtest4WIN pre-log 6767 feed
    # (see v4w_listener_loop). True on CallbookerApp.
    VHFCTEST_CAPABLE = False

    def __init__(self, root, cache_path, port, cache_days, qrz_username="",
                 qrz_password="", win_file=None, cache_persist=True,
                 vhfctest_port=0, selftest_call="", lan_share_port=0,
                 mqtt_settings=None, config_dir="", lan_share_bcast=""):
        self.root = root
        self.port = port
        self.vhfctest_port = vhfctest_port
        self.lan_share_port = lan_share_port
        self.lan_share_bcast = lan_share_bcast
        self.cache = Cache(cache_path, cache_days, cache_persist)
        self.win_file = win_file
        self.current = None
        self._debounce = None
        # Per-lookup generation counter + captured context (mode / feed /
        # frequency / source layout). Overlapping async lookups are told
        # apart by generation so a slow stale result cannot repaint or be
        # published against a newer callsign. Read by the MQTT publish path.
        self._lookup_generation = 0
        self._active_lookup_generation = 0
        self._active_lookup_context = None
        # QRZ takes slot 0 (shown left-most): the paid XML API when
        # credentials are set, else the public /db/ page (locator only) if
        # QRZ_WEB_FALLBACK is on for this app. All sources are queried in
        # parallel, so each slot fills as soon as that source answers
        # regardless of its position in the chain.
        chain = []
        if (qrz_username and qrz_password) or self.QRZ_WEB_FALLBACK:
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
        # LAN cache sharing. The listener thread appends received entries
        # (call, sources, ts) here; _poll_inbox / the grace timer merge
        # them on the GUI thread. _await_lan holds the callsign we have an
        # outstanding call-request for (waiting out LAN_GRACE_MS before the
        # HTTP lookup); a matching entry clears it and skips the lookup.
        self._lan_inbox = []
        self._await_lan = None
        self._await_lan_ctx = None
        # The footer info line shows the worked callsign and, once the
        # lookup resolves, where its data came from: "local" (this PC's
        # cache), "LAN" (a peer over 6768), or "online" (a fresh
        # QRZ/QRZCQ/HamQTH fetch). Reset per callsign in _show_call.
        self._resolved_from = None
        # Start-up self-test (see _start_precheck). Empty call = disabled.
        self._selftest_call = normalize_call(selftest_call)
        self._precheck = None       # per source: None = pending, (status, ms)
        self._precheck_inbox = []   # worker threads -> GUI, like _inbox
        self._precheck_active = False
        self._qrz_tier = ""         # "xml" / "web" - which QRZ path the self-test hit
        self._slots = None
        self._pending_inds = set()
        self._font_cache = {}  # size -> tkfont.Font, for width measurement
        # Optional MQTT output: one JSON document per completed lookup (see
        # mqtt_client.py). Off unless mqtt_enabled=yes; needs paho-mqtt.
        self.mqtt = MqttPublisher(mqtt_settings or {}, config_dir)
        self._mqtt_error_seen = ""
        self.local = set(local_interfaces())
        self.local.add("127.0.0.1")
        # Optional LAN cache-sharing feed on its own UDP port (started
        # before _build so the title bar can show it). Off if the port
        # cannot be bound.
        self.lan = None
        if self.lan_share_port:
            lan = LANShare(
                self.lan_share_port, self.cache, self._queue_lan_entry,
                self.local, self.lan_share_bcast,
            )
            if lan.start():
                self.lan = lan
                lan.request_sync()  # ask peers to replay their caches
        self._build()
        self._restore_window()
        self.mqtt.start()  # background network loop; a no-op when disabled
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
            width=360,
            height=64,
            bg=COLOR_IDLE,
            highlightthickness=1,
            highlightbackground="#888888",
        )
        self.canvas.pack(fill=tk.X)
        self.main_id = self.canvas.create_text(
            180, 32, text="—", font=("Segoe UI", FONT_SIZE_NAME, "bold"), fill="white"
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

    def _queue_lan_entry(self, call, sources, ts):
        # LANShare listener thread: hand a received entry to the GUI thread
        # (a plain list append is safe). _drain_lan_inbox does the merge.
        self._lan_inbox.append((call, sources, ts))

    def _drain_lan_inbox(self):
        # GUI thread: merge received LAN entries into the cache (newer-wins)
        # and, when one answers the callsign on screen, show it.
        if not self._lan_inbox:
            return
        items, self._lan_inbox = self._lan_inbox, []
        merged_any = False
        for call, sources, ts in items:
            if self.cache.merge(call, sources, ts):
                merged_any = True
        cur = self.current
        if not merged_any or cur is None:
            return
        cached = self._cached_sources(cur)
        if cached is None:
            return
        awaiting = self._await_lan == cur
        have_http_data = bool(self._slots) and any(
            s is not None for s in self._slots
        )
        # Show the LAN result when we were waiting for it, or when a lookup
        # is not already painting real data - never fight an in-flight HTTP
        # render.
        if awaiting or not have_http_data:
            self._await_lan = None
            self._slots = None
            self._render_slots(cur, list(cached), set())
            self._set_resolved_from("LAN")
            if awaiting:
                # A peer answered instead of the websites - to an MQTT
                # consumer this is a cache hit.
                self._publish_lookup_result(
                    cur, list(cached), cached=True,
                    context=self._await_lan_ctx or self._capture_lookup_context(),
                )

    def _cached_sources(self, call):
        # Cache lookup, keyed by the bare call so LAN peers share entries
        # regardless of view. An entry whose source count no longer matches
        # the active lookup chain (HF <-> VHF changes whether QRZ has a
        # slot) would be mislabelled, so treat it as a miss and re-fetch.
        sources = self.cache.get(call)
        if sources is not None and len(sources) != len(self.lookup_chain):
            return None
        return sources

    def _capture_lookup_context(self):
        return {
            "mode": "vhf" if self.SLOT_FIELDS == ("grid",) else "hf",
            "feed": getattr(self, "_result_feed", None),
            "frequency_mhz": getattr(self, "_result_frequency_mhz", None),
            "source_labels": tuple(self.source_labels),
        }

    def _footer_text(self):
        # The info-line text: the worked call, plus " · <source>" once the
        # lookup has resolved (see _resolved_from).
        if not self.current:
            return ""
        if self._resolved_from:
            return "{} · {}".format(self.current, self._resolved_from)
        return self.current

    def _set_resolved_from(self, source):
        # Record how the current lookup resolved and refresh the info line
        # (unless an MQTT error is currently occupying the footer).
        self._resolved_from = source
        if self.current and not self._mqtt_error_seen:
            self.call_label.configure(text=self._footer_text())

    def _handle_call(self, call):
        # Shared path for a worked callsign from any feed (the N1MM
        # LookupInfo/ContactInfo packet, or a VHFCtest4WIN <V4W> broadcast).
        call = normalize_call(call)
        if not call or call.lower().startswith("test"):
            return
        self._lookup_generation += 1
        generation = self._lookup_generation
        context = self._capture_lookup_context()
        self._precheck_active = False  # a real callsign supersedes the self-test
        # Show the callsign immediately (it may change as the user types),
        # but debounce the network lookup until it has been stable a moment.
        if self.current != call:
            self.current = call
            self._await_lan = None  # any pending call-request is now stale
            self._show_call(call)
        if self._debounce is not None:
            self.root.after_cancel(self._debounce)
        self._debounce = self.root.after(
            300, self._on_stable, call, generation, context
        )

    def _on_stable(self, call, generation, context):
        self._debounce = None
        self._await_lan = None
        if call != self.current or generation != self._lookup_generation:
            return
        sources = self._cached_sources(call)
        if sources is not None:
            self._slots = None
            self._render_slots(call, list(sources), set())
            self._set_resolved_from("local")
            self._publish_lookup_result(
                call, list(sources), cached=True, context=context
            )
        elif self.lan is not None:
            # Ask the LAN first: broadcast a call-request and give a peer a
            # short grace to answer before falling through to the callbook
            # websites. A matching entry (handled in _drain_lan_inbox)
            # clears _await_lan, so _lan_grace_expired then does nothing.
            self._await_lan = call
            self._await_lan_ctx = context
            self.lan.request_call(call)
            self.root.after(
                LAN_GRACE_MS, self._lan_grace_expired, call, generation, context
            )
        else:
            self._start_lookup(call, generation, context)

    def _lan_grace_expired(self, call, generation, context):
        if (self._await_lan != call or call != self.current
                or generation != self._lookup_generation):
            return  # superseded, or a peer already answered
        # Fold in anything that just arrived; if it answers `call` this
        # clears _await_lan and paints (and publishes) the result.
        self._drain_lan_inbox()
        if self._await_lan != call or call != self.current:
            return  # a peer answered inside the grace window
        self._await_lan = None
        self._start_lookup(call, generation, context)

    def _show_call(self, call):
        self._resolved_from = None  # new callsign - info line back to bare
        self.call_label.configure(text=call)
        sources = self._cached_sources(call)
        if sources is not None:
            self._slots = None
            self._render_slots(call, list(sources), set())
            self._set_resolved_from("local")
        else:
            # cleared visually while waiting for the debounce / lookup
            self.canvas.configure(bg=COLOR_ACTIVE)
            self.canvas.itemconfigure(self.main_id, text="…")

    def _start_lookup(self, call, generation, context):
        # No "already fetching" guard: if the operator retypes the call
        # while a lookup is in flight, we just start a fresh one. The old
        # threads still finish but their results are dropped by the
        # generation / `call != self.current` checks in _poll_inbox.
        self._slots = [None] * len(self.lookup_chain)
        self._pending_inds = set(range(len(self.lookup_chain)))
        self._active_lookup_generation = generation
        self._active_lookup_context = context
        self._render_slots(call, self._slots, self._pending_inds)
        self._do_lookup(call, generation, tuple(self.lookup_chain))

    def _do_lookup(self, call, generation, lookup_chain):
        # Fires every source at once (one thread each) so a slow source
        # never holds up a fast one; returns immediately. Each result is
        # posted to the GUI the moment that source answers; the slot index
        # is kept, so the display still reads in chain order (QRZ, QRZCQ,
        # HamQTH) - it just fills in as fast as each source can reply
        # instead of waiting for the whole chain.
        def run(i, fn):
            try:
                res = fn(call)
            except Exception:
                res = None
            self._inbox.append((call, generation, i, res))

        for i, fn in enumerate(lookup_chain):
            threading.Thread(target=run, args=(i, fn), daemon=True).start()

    def _publish_lookup_result(self, call, sources, cached, context):
        """Publish a stable, source-preserving record after lookup completes."""
        if not self.mqtt.enabled:
            return
        try:
            labels = list(context["source_labels"])
            normalized_sources = []
            values = []
            for source in sources:
                value = self._source_value(source) if source else ""
                values.append(value or None)
                result = None
                if source is not None:
                    result = {
                        key: self._source_field(source, key)
                        for key in ("name", "grid", "state", "cqzone", "country")
                    }
                normalized_sources.append(result)
            payload = lookup_payload(
                call=call,
                mode=context["mode"],
                feed=context["feed"],
                frequency_mhz=context["frequency_mhz"],
                cached=cached,
                name=self._best_name([s for s in sources if s]),
                source_labels=labels,
                sources=normalized_sources,
                values=values,
            )
            self.mqtt.publish(payload)
        except Exception:
            # MQTT must never interfere with the contest lookup UI.
            pass

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
            if source_label(fn) == "QRZ":
                self._qrz_tier = _QRZ_TIER  # "xml" / "web" - for the QRZ line
            self._precheck_inbox.append((i, status, ms))

        for i, fn in enumerate(self.lookup_chain):
            threading.Thread(target=run, args=(i, fn), daemon=True).start()

    def _render_precheck(self):
        # One monospaced line per source: "QRZCQ   OK      181 ms".
        if not self._precheck_active or self.current or self._precheck is None:
            return
        lines = []
        for lbl, v in zip(self.source_labels, self._precheck):
            if lbl == "QRZ" and self._qrz_tier:
                lbl = "QRZ·" + self._qrz_tier  # "QRZ·xml" / "QRZ·web"
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
        if self._qrz_tier == "web":
            summary += "  ·  QRZ: web page (no XML sub)"
        elif self._qrz_tier == "xml" and _QRZ_SUBEXP:
            summary += "  ·  QRZ XML sub to " + _QRZ_SUBEXP.split()[-1]
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
        try:
            self._drain_lan_inbox()  # merge cache entries shared by LAN peers
        except Exception:
            pass
        if self._v4w_status:
            msg, self._v4w_status = self._v4w_status, None
            if not self.current:  # don't clobber a lookup already on screen
                self.call_label.configure(text=msg)
        mqtt_error = self.mqtt.error
        if mqtt_error and mqtt_error != self._mqtt_error_seen:
            self._mqtt_error_seen = mqtt_error
            prefix = "{} · ".format(self.current) if self.current else ""
            self.call_label.configure(text=prefix + mqtt_error)
        elif not mqtt_error and self._mqtt_error_seen:
            self._mqtt_error_seen = ""
            self.call_label.configure(
                text=self._footer_text() or "MQTT connected"
            )
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
                call, generation, i, res = self._inbox.pop(0)
                if (call != self.current
                        or generation != self._lookup_generation
                        or generation != self._active_lookup_generation):
                    continue
                if self._slots is None or i >= len(self._slots):
                    continue
                self._slots[i] = res
                self._pending_inds.discard(i)
                if not self._pending_inds:
                    # Only cache a complete, error-free set of results.
                    if not any(s is None for s in self._slots):
                        ts = self.cache.put(call, list(self._slots))
                        if self.lan is not None:
                            self.lan.broadcast_entry(
                                call, list(self._slots), ts
                            )
                    # Publish even a partial result (a failed source is a
                    # null entry) - the MQTT consumer wants what was shown.
                    self._publish_lookup_result(
                        call, list(self._slots), cached=False,
                        context=self._active_lookup_context,
                    )
                    self._set_resolved_from("online")
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
        # The operator's first name, printed once. Out of the candidates
        # from the sources that have answered so far the shortest wins,
        # then only its first word is kept ("Goran Andric" -> "Goran",
        # "ARRL HQ OPERATORS CLUB" -> "ARRL") - a contest exchange never
        # wants the surname or a club's full title. Placeholder entries
        # (QRZCQ fills unallocated calls with "Unknown OM") count as empty.
        names = []
        for s in sources:
            n = self._source_field(s, "name")
            a = n.lower()
            if a and not a.startswith(("unknown", "not found", "n/a", "na")):
                names.append(n)
        if not names:
            return ""
        return min(names, key=len).split()[0]

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
        # text turns light green and (COLLAPSE_ON_AGREE) the repeated value
        # collapses to one token. _font_for then picks the biggest size
        # that fits the canvas, so anything short - a collapsed token, a
        # DX "name (Country) - zone", a two-source disagreement - is drawn
        # large and only a long side-by-side row steps down. Examples:
        #   HF, all agree:       "Dave - MA/5"            (collapsed, big, green)
        #   HF, DX all agree:    "Hans (Germany) - 14"    (big)
        #   HF, 2 sources differ:"Dave - MA/5 MA/4"       (big)
        #   HF, 3 sources differ:"Dave - MA/5 MA/4 MA/5"  (steps down to fit)
        #   VHF, all agree:      "Hans - JN76HD"          (collapsed, big, green)
        #   VHF, sources differ: "Hans - JN76GB - JN76HD - JN76HD"  (-> ladder)
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
        # When they all agree, show the value once (larger) instead of
        # "MA/5 MA/5 MA/5" / "JN76HD - JN76HD - JN76HD".
        collapsed = agree and self.COLLAPSE_ON_AGREE
        fill = TEXT_DEFAULT
        # Placeholder / error states keep a plain fixed size; only a real
        # result line is sized to fit (see _font_for).
        font = ("Segoe UI", FONT_SIZE_NAME, "bold")
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
            font = self._font_for(text)
        elif not all_done:
            text = SLOT_PENDING
            bg = COLOR_ACTIVE
        else:
            text = "lookup failed" if all(s is None for s in slots) else "no data"
            bg = COLOR_IDLE
        self.canvas.configure(bg=bg)
        self.canvas.itemconfigure(self.main_id, text=text, fill=fill)
        self.canvas.itemconfigure(self.main_id, font=font)

    def _font_for(self, text):
        # Largest FONT_LADDER size whose rendered width fits the canvas.
        # Uses the live width once the window is up, the requested width
        # before that; a short line (or the collapsed single token) lands
        # on FONT_SIZE_BIG, a long side-by-side row steps down to fit.
        avail = max(self.canvas.winfo_width(), self.canvas.winfo_reqwidth()) - 12
        for size in FONT_LADDER:
            font = self._font_cache.get(size)
            if font is None:
                font = tkfont.Font(family="Segoe UI", size=size, weight="bold")
                self._font_cache[size] = font
            if font.measure(text) <= avail:
                return ("Segoe UI", size, "bold")
        return ("Segoe UI", FONT_LADDER[-1], "bold")

    def on_close(self):
        self._save_window()
        self.cache.flush(force=True)
        if self.lan is not None:
            self.lan.close()
        self.mqtt.close()
        self.stop.set()
        self.root.destroy()
