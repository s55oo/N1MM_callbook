# SPDX-License-Identifier: Unlicense
"""Headless checks for CallbookApp._render_slots and the cache schema.

No network, no real Tk window - a fake canvas captures the text that would
be drawn. Run:  python dev/test_render.py
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import n1mm_callbook as cb  # noqa: E402


class FakeCanvas:
    def __init__(self):
        self.text = None
        self.bg = None

    def configure(self, **kw):
        if "bg" in kw:
            self.bg = kw["bg"]

    def itemconfigure(self, _id, **kw):
        if "text" in kw:
            self.text = kw["text"]

    def coords(self, *a):
        pass


def make(cls):
    app = cls.__new__(cls)
    app.canvas = FakeCanvas()
    app.main_id = 0
    return app


def check(label, got, want):
    ok = "ok  " if got == want else "FAIL"
    print(f"  [{ok}] {label:38} -> {got!r}")
    if got != want:
        print(f"         expected {want!r}")
    return got == want


def main():
    import n1mm_VHFcallbook as vhf

    hf = make(cb.CallbookApp)
    vh = make(vhf.VHFApp)
    ok = True

    US = {"name": "Fred", "state": "MA", "cqzone": "5", "country": "United States"}
    US2 = {"name": "Frederick", "state": "MA", "cqzone": "5", "country": "United States"}
    USnz = {"name": "Fred", "state": "MA", "cqzone": "", "country": "United States"}
    DL = {"name": "Hans", "state": "HE", "cqzone": "14", "country": "Germany"}
    DX = {"name": "Hans", "state": "", "cqzone": "14", "country": "Germany"}
    DXnz = {"name": "Hans", "state": "", "cqzone": "", "country": "Germany"}
    EMPTY = {"name": "", "state": "", "cqzone": "", "country": ""}

    def r(app, slots, pending=frozenset()):
        app._render_slots("T", slots, set(pending))
        return app.canvas.text

    ok &= check("HF US, all agree", r(hf, [US, US2, US]), "Fred - MA/5 MA/5 MA/5")
    ok &= check("HF US, one source has no zone", r(hf, [US, USnz, US]), "Fred - MA/5 MA MA/5")
    ok &= check("HF US, 2 slots pending", r(hf, [US, None, None], {1, 2}), "Fred - MA/5 … …")
    ok &= check("HF DX, foreign state dropped, zone kept", r(hf, [DL, DX, DX]), "Hans (Germany) - 14 14 14")
    ok &= check("HF DX, no zone anywhere", r(hf, [DXnz, DXnz, DXnz]), "Hans (Germany)")
    ok &= check("HF nothing", r(hf, [EMPTY, EMPTY, EMPTY]), "no data")
    ok &= check("HF all failed", r(hf, [None, None, None]), "lookup failed")

    ok &= check("VHF locators, one missing", r(vh, [{"grid": "JN76HD"}, {"grid": "JN76HD"}, {"grid": ""}]),
                "JN76HD JN76HD -")
    ok &= check("VHF stale lowercase grid upper-cased",
                r(vh, [{"grid": "jn46la"}, {"grid": "JN46LA"}, {"grid": "JN46LA"}]),
                "JN46LA JN46LA JN46LA")
    ok &= check("VHF DX with no grid stays 'no data'",
                r(vh, [{"grid": "", "name": "Hans", "country": "Germany"}] * 3), "no data")

    # cache schema: an entry without the current version is refetched
    p = tempfile.mktemp(suffix=".json")
    try:
        import json
        json.dump({
            "OLD": {"ts": time.time(), "sources": [{"state": "CT"}]},
            "NEW": {"ts": time.time(), "v": cb.CACHE_SCHEMA,
                    "sources": [{"state": "CT", "cqzone": "5"}]},
        }, open(p, "w"))
        c = cb.Cache(p, 30)
        ok &= check("cache: pre-schema entry -> None (refetch)", c.get("OLD"), None)
        ok &= check("cache: current entry -> served", c.get("NEW"),
                    [{"state": "CT", "cqzone": "5"}])
    finally:
        try:
            os.remove(p)
        except OSError:
            pass

    # geometry round-trip
    m = cb.CallbookApp._GEOM_RE.match("344x117+321+123")
    ok &= check("geometry regex keeps position only",
                "{}{}".format(*m.groups()) if m else None, "+321+123")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
