# SPDX-License-Identifier: Unlicense
"""Headless checks for LAN cache sharing (dev/lan-cache-sharing.md).

No sockets and no window: the cache helpers are exercised directly, the
LANShare packet dispatch is driven by handing bytes to ``_handle``, and
the app-side lookup order is checked with a fake Tk root / canvas. Run:
    python dev/test_lan_share.py
"""
import json
import os
import sys
import tempfile
import time
import tkinter as tk
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import n1mm_callbook as cb  # noqa: E402

# _render_slots -> _font_for measures text with real font metrics, which
# needs a Tk root to exist (withdrawn - nothing is shown).
_ROOT = tk.Tk()
_ROOT.withdraw()


def check(label, got, want):
    ok = "ok  " if got == want else "FAIL"
    print(f"  [{ok}] {label:52} -> {got!r}")
    if got != want:
        print(f"         expected {want!r}")
    return got == want


class FakeCanvas:
    text = None

    def configure(self, **kw):
        pass

    def itemconfigure(self, *a, **kw):
        if "text" in kw:
            self.text = kw["text"]

    def coords(self, *a):
        pass

    def winfo_width(self):
        return 362

    def winfo_reqwidth(self):
        return 362


class FakeRoot:
    def __init__(self):
        self.afters = []  # (ms, fn, args)

    def after(self, ms, fn, *args):
        self.afters.append((ms, fn, args))
        return len(self.afters)

    def after_cancel(self, _tok):
        pass

    def fire(self, fn_name):
        """Run every queued callback whose function has this name."""
        for _ms, fn, args in list(self.afters):
            if getattr(fn, "__name__", "") == fn_name:
                fn(*args)


class FakeLan:
    def __init__(self, cache):
        self.cache = cache
        self.requested = []
        self.broadcast = []

    def request_call(self, call):
        self.requested.append(call)

    def broadcast_entry(self, call, sources, ts):
        self.broadcast.append((call, sources, ts))


SRC = [{"name": "Fred", "state": "MA", "cqzone": "5", "grid": "FN42",
        "country": "United States", "qth": "secret", "class": "E"}]
TRIMMED = [{"name": "Fred", "state": "MA", "cqzone": "5", "grid": "FN42",
            "country": "United States"}]


def cache_tests():
    ok = True
    p = tempfile.mktemp(suffix="_cache.json")
    try:
        c = cb.Cache(p, 30, False)

        # _lan_trim / put shape
        ok &= check("_lan_trim keeps only display fields",
                    cb._lan_trim(SRC), TRIMMED)
        ok &= check("_lan_trim drops non-dict slots",
                    cb._lan_trim([None, "x", SRC[0]]), TRIMMED)

        t_put = c.put("W1AW", SRC)
        ok &= check("put() returns a timestamp", isinstance(t_put, float), True)
        ok &= check("put() stores trimmed sources",
                    c.get("W1AW"), TRIMMED)
        ok &= check("get_with_ts() returns (sources, ts)",
                    c.get_with_ts("W1AW"), (TRIMMED, t_put))

        # merge: newer wins, older / equal is a no-op, missing is stored
        ok &= check("merge older ts -> rejected",
                    c.merge("W1AW", [{"grid": "AA00"}], t_put - 10), False)
        ok &= check("merge older ts -> entry unchanged",
                    c.get("W1AW"), TRIMMED)
        ok &= check("merge newer ts -> accepted",
                    c.merge("W1AW", [{"grid": "BB11"}], t_put + 10), True)
        ok &= check("merge newer ts -> entry replaced",
                    c.get("W1AW"), [{"name": "", "state": "", "cqzone": "",
                                     "grid": "BB11", "country": ""}])
        ok &= check("merge unknown call -> stored",
                    c.merge("K1TTT", SRC, time.time()), True)
        ok &= check("merge empty sources -> rejected",
                    c.merge("N0P", [], time.time()), False)

        # items_since: newest first, honours the since cut-off
        c.merge("AA1A", [{"grid": "C"}], 1000.0)
        c.merge("BB2B", [{"grid": "D"}], 3000.0)
        c.merge("CC3C", [{"grid": "E"}], 2000.0)
        # (all three are decades old, so also older than the 30-day cutoff)
        got = [call for call, _s, _ts in c.items_since(0)]
        ok &= check("items_since(0) excludes entries past the freshness window",
                    [x for x in got if x in ("AA1A", "BB2B", "CC3C")], [])
        fresh = time.time()
        c.merge("F1", [{"grid": "a"}], fresh - 5)
        c.merge("F2", [{"grid": "b"}], fresh - 1)
        order = [call for call, _s, _ts in c.items_since(0)
                 if call in ("F1", "F2")]
        ok &= check("items_since newest-first", order, ["F2", "F1"])
        since_mid = [call for call, _s, _ts in c.items_since(fresh - 3)
                     if call in ("F1", "F2")]
        ok &= check("items_since honours the since argument", since_mid, ["F2"])
    finally:
        for f in (p, p + ".tmp"):
            try:
                os.remove(f)
            except OSError:
                pass
    return ok


def lanshare_dispatch_tests():
    ok = True
    p = tempfile.mktemp(suffix="_cache.json")
    try:
        c = cb.Cache(p, 30, False)
        got_entries = []
        lan = cb.LANShare(6768, c, lambda *a: got_entries.append(a),
                          {"127.0.0.1"})
        sent = []
        lan._send = lambda obj: sent.append(obj)

        def pkt(d):
            return json.dumps(d).encode("utf-8")

        good = {"cbshare": cb.LAN_PROTO, "call": "S55OO", "sources": TRIMMED,
                "ts": time.time(), "schema": cb.CACHE_SCHEMA}
        lan._handle(pkt(good), "10.0.0.9")
        ok &= check("entry packet -> on_entry(call, sources, ts)",
                    (got_entries[-1][0], got_entries[-1][1]), ("S55OO", TRIMMED))

        got_entries.clear()
        lan._handle(pkt({**good, "cbshare": 999}), "10.0.0.9")
        ok &= check("wrong cbshare marker -> ignored", got_entries, [])
        lan._handle(pkt({**good, "schema": cb.CACHE_SCHEMA + 1}), "10.0.0.9")
        ok &= check("wrong cache schema -> ignored", got_entries, [])
        lan._handle(b"not json at all", "10.0.0.9")
        ok &= check("junk bytes -> ignored", got_entries, [])
        lan._handle(pkt({**good, "ts": time.time() + 99999}), "10.0.0.9")
        ok &= check("far-future timestamp -> ignored", got_entries, [])

        # call-request: answered only when the call is cached
        c.put("W1AW", SRC)
        sent.clear()
        lan._handle(pkt({"cbshare": cb.LAN_PROTO, "req": "call",
                         "call": "W1AW"}), "10.0.0.9")
        ok &= check("call-request for a cached call -> entry broadcast",
                    (sent[0]["call"], sent[0]["sources"]), ("W1AW", TRIMMED))
        sent.clear()
        lan._handle(pkt({"cbshare": cb.LAN_PROTO, "req": "call",
                         "call": "DL0XYZ"}), "10.0.0.9")
        ok &= check("call-request for an unknown call -> silence", sent, [])

        # sync-request: our own echo is ignored, a peer's is served
        lan._own_sync_ts = 0.0
        lan._last_sync_served = 0.0
        sent.clear()
        lan._handle(pkt({"cbshare": cb.LAN_PROTO, "req": "sync",
                         "since": 0}), "127.0.0.1")
        ok &= check("sync-request from ourselves -> ignored",
                    lan._last_sync_served, 0.0)
        lan._handle(pkt({"cbshare": cb.LAN_PROTO, "req": "sync",
                         "since": 0}), "10.0.0.9")
        ok &= check("sync-request from a peer -> accepted for service",
                    lan._last_sync_served > 0, True)
        lan.close()
    finally:
        for f in (p, p + ".tmp"):
            try:
                os.remove(f)
            except OSError:
                pass
    return ok


def lookup_order_tests():
    ok = True
    p = tempfile.mktemp(suffix="_cache.json")
    try:
        app = cb.CallbookApp.__new__(cb.CallbookApp)
        app.root = FakeRoot()
        app.canvas = FakeCanvas()
        app.main_id = 0
        app._font_cache = {}
        app.cache = cb.Cache(p, 30, False)
        app.lan = FakeLan(app.cache)
        app.current = "S55OO"
        app._debounce = None
        app._await_lan = None
        app._await_lan_ctx = None
        app._lan_inbox = []
        app._slots = None
        app._pending_inds = set()
        app._lookup_generation = 5
        app._active_lookup_generation = 0
        app._active_lookup_context = None
        app.mqtt = types.SimpleNamespace(enabled=False)
        app.SLOT_FIELDS = ("state", "cqzone")
        app.SLOT_SEP = " "
        app.source_labels = ("QRZCQ", "HamQTH")
        app.lookup_chain = (cb.qrzcq_lookup, cb.hamqth_lookup)

        started = []
        app._start_lookup = lambda call, gen, ctx: started.append(call)
        GEN, CTX = 5, {"mode": "hf", "feed": "n1mm", "frequency_mhz": 14.2,
                       "source_labels": ("QRZCQ", "HamQTH")}

        # cache miss -> ask the LAN, schedule the grace, do NOT fetch yet
        app._on_stable("S55OO", GEN, CTX)
        ok &= check("cache miss -> call-request sent", app.lan.requested, ["S55OO"])
        ok &= check("cache miss -> no HTTP lookup during the grace", started, [])
        ok &= check("cache miss -> grace timer scheduled at LAN_GRACE_MS",
                    [ms for ms, fn, _a in app.root.afters
                     if fn.__name__ == "_lan_grace_expired"], [cb.LAN_GRACE_MS])
        ok &= check("cache miss -> _await_lan armed", app._await_lan, "S55OO")

        # a peer answers within the grace -> merged and rendered, no fetch
        # (two sources, matching the 2-entry lookup_chain)
        app._queue_lan_entry("S55OO", TRIMMED + TRIMMED, time.time())
        app.root.fire("_lan_grace_expired")
        ok &= check("peer answered -> _await_lan cleared", app._await_lan, None)
        ok &= check("peer answered -> HTTP lookup skipped", started, [])
        ok &= check("peer answered -> result on screen", app.canvas.text,
                    "Fred - MA/5")

        # no peer answers -> grace falls through to the HTTP lookup
        app.root.afters.clear()
        app.current = "K1TTT"
        app._await_lan = None
        app._lookup_generation = 6
        app._on_stable("K1TTT", 6, CTX)
        app.root.fire("_lan_grace_expired")
        ok &= check("no peer -> falls through to _start_lookup", started, ["K1TTT"])
    finally:
        for f in (p, p + ".tmp"):
            try:
                os.remove(f)
            except OSError:
                pass
    return ok


def main():
    ok = True
    print("cache helpers")
    ok &= cache_tests()
    print("LANShare packet dispatch")
    ok &= lanshare_dispatch_tests()
    print("app lookup order (LAN before the callbook sites)")
    ok &= lookup_order_tests()
    print("\n" + ("ALL PASS" if ok else "SOME FAILED"))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
