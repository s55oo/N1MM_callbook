# SPDX-License-Identifier: Unlicense
"""Two-socket smoke test for LAN cache sharing (real UDP, one machine).

Brings up two ``LANShare`` instances on the sharing port, has one resolve
a call and broadcast it, then has the other ask the LAN for it - and
prints what each received. A quick "does the wire actually work here?"
before trusting it in a multi-op. Run:  python dev/lan_wire.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import n1mm_callbook as cb  # noqa: E402

PORT = cb.LAN_SHARE_PORT
SAMPLE = [{"name": "Goran", "state": "", "cqzone": "15", "grid": "JN76",
           "country": "Slovenia"}]


def main():
    got = []
    a_cache = cb.Cache(tempfile.mktemp(suffix=".json"), 30, False)
    b_cache = cb.Cache(tempfile.mktemp(suffix=".json"), 30, False)

    def spy(who, cache):
        # Mimic the app: record it and merge it into that peer's cache.
        def on_entry(call, sources, ts):
            got.append((who, call, sources, ts))
            cache.merge(call, sources, ts)
        return on_entry

    a = cb.LANShare(PORT, a_cache, spy("A", a_cache), {"127.0.0.1"})
    b = cb.LANShare(PORT, b_cache, spy("B", b_cache), {"127.0.0.1"})
    print("A.start:", a.start(), " B.start:", b.start())
    if not (a._sock and b._sock):
        print("could not bind - is another Callbooker already running?")
        return
    time.sleep(0.2)

    ts = a_cache.put("S55OO", SAMPLE)
    a.broadcast_entry("S55OO", a_cache.get("S55OO"), ts)
    time.sleep(0.3)
    print("after A broadcasts an entry, B received:",
          [m[1:] for m in got if m[0] == "B"])

    got.clear()
    b.request_call("S55OO")
    time.sleep(0.3)
    print("after B asks the LAN for S55OO, B received:",
          [m[1:] for m in got if m[0] == "B"])
    print("B cache now has S55OO:", b_cache.get("S55OO") is not None)

    a.close()
    b.close()
    time.sleep(0.4)


if __name__ == "__main__":
    main()
