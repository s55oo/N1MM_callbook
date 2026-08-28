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
        self.fill = None

    def configure(self, **kw):
        if "bg" in kw:
            self.bg = kw["bg"]

    def itemconfigure(self, _id, **kw):
        if "text" in kw:
            self.text = kw["text"]
        if "fill" in kw:
            self.fill = kw["fill"]

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
    USbadz = {"name": "Fred", "state": "MA", "cqzone": "4", "country": "United States"}
    CTY_US = {"state": "", "cqzone": "5", "country": "United States"}  # cty.dat slot
    CTY_USbad = {"state": "", "cqzone": "4", "country": "United States"}
    CTY_VE = {"state": "BC", "cqzone": "3", "country": "Canada"}
    VE = {"name": "Jim", "state": "BC", "cqzone": "3", "country": "Canada"}
    DL = {"name": "Hans", "state": "HE", "cqzone": "14", "country": "Germany"}
    DX = {"name": "Hans", "state": "", "cqzone": "14", "country": "Germany"}
    DXnz = {"name": "Hans", "state": "", "cqzone": "", "country": "Germany"}
    EMPTY = {"name": "", "state": "", "cqzone": "", "country": ""}

    def r(app, slots, pending=frozenset()):
        app._render_slots("T", slots, set(pending))
        return app.canvas.text

    def rf(app, slots, pending=frozenset()):
        app._render_slots("T", slots, set(pending))
        return app.canvas.fill

    ok &= check("HF US, all agree", r(hf, [US, US2, US]), "Fred - MA/5 MA/5 MA/5")
    ok &= check("HF US + cty.dat slot", r(hf, [CTY_US, US, US2]), "Fred - 5 MA/5 MA/5")
    ok &= check("HF VE, province + zone from cty.dat", r(hf, [CTY_VE, VE, VE]),
                "Jim - BC/3 BC/3 BC/3")
    ok &= check("HF US, one source has no zone", r(hf, [US, USnz, US]), "Fred - MA/5 MA MA/5")
    ok &= check("HF US, 2 slots pending", r(hf, [US, None, None], {1, 2}), "Fred - MA/5 … …")
    ok &= check("HF DX, foreign state dropped, zone kept", r(hf, [DL, DX, DX]), "Hans (Germany) - 14 14 14")
    ok &= check("HF DX, no zone anywhere", r(hf, [DXnz, DXnz, DXnz]), "Hans (Germany)")
    ok &= check("HF empty slot shows '·'", r(hf, [US, EMPTY, US]), "Fred - MA/5 · MA/5")
    ok &= check("HF nothing", r(hf, [EMPTY, EMPTY, EMPTY]), "no data")
    ok &= check("HF all failed", r(hf, [None, None, None]), "lookup failed")

    ok &= check("VHF locators joined with ' - '",
                r(vh, [{"grid": "JN76HD"}, {"grid": "JN76HD"}, {"grid": ""}]),
                "JN76HD - JN76HD - ·")
    ok &= check("VHF stale lowercase grid upper-cased",
                r(vh, [{"grid": "jn46la"}, {"grid": "JN46LA"}, {"grid": "JN46LA"}]),
                "JN46LA - JN46LA - JN46LA")
    ok &= check("VHF DX with no grid stays 'no data'",
                r(vh, [{"grid": "", "name": "Hans", "country": "Germany"}] * 3), "no data")

    # agreement colour
    ok &= check("VHF all agree -> green text",
                rf(vh, [{"grid": "KN04AX"}] * 3), cb.TEXT_AGREE)
    ok &= check("VHF disagree -> default text",
                rf(vh, [{"grid": "KN04AX"}, {"grid": "KN04BX"}, {"grid": "KN04AX"}]), cb.TEXT_DEFAULT)
    ok &= check("VHF one still pending -> not green yet",
                rf(vh, [{"grid": "KN04AX"}, {"grid": "KN04AX"}, None], {2}), cb.TEXT_DEFAULT)
    ok &= check("HF all agree -> green", rf(hf, [US, US2, US]), cb.TEXT_AGREE)
    ok &= check("HF cty.dat + web all agree -> green",
                rf(hf, [CTY_US, US, US2]), cb.TEXT_AGREE)
    ok &= check("HF web agree but cty.dat zone differs -> white",
                rf(hf, [CTY_USbad, US, US2]), cb.TEXT_DEFAULT)
    ok &= check("HF two sources disagree on zone -> white",
                rf(hf, [US, USbadz, US2]), cb.TEXT_DEFAULT)
    ok &= check("HF one source just missing the zone -> still green",
                rf(hf, [US, USnz, US2]), cb.TEXT_AGREE)

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

    # debounced writes: put() must not touch disk; flush(force) does
    p = tempfile.mktemp(suffix="_cache.json")
    try:
        c = cb.Cache(p, 30, True)
        c.put("W1AW", [{"name": "F", "state": "CT", "cqzone": "5",
                        "grid": "FN31", "country": "United States",
                        "qth": "drop me", "class": "E"}])
        ok &= check("cache: put() does not write (debounced)",
                    os.path.exists(p), False)
        c.flush(force=True)
        ok &= check("cache: flush(force) writes", os.path.exists(p), True)
        stored = sorted(__import__("json").load(open(p))["W1AW"]["sources"][0])
        ok &= check("cache: only display fields stored", stored,
                    ["country", "cqzone", "grid", "name", "state"])
    finally:
        for f in (p, p + ".tmp"):
            try:
                os.remove(f)
            except OSError:
                pass

    # persist=off: never writes, still de-dupes in memory
    p = tempfile.mktemp(suffix="_cache.json")
    c = cb.Cache(p, 30, False)
    c.put("K1TTT", [{"state": "MA", "cqzone": "5"}])
    c.flush(force=True)
    ok &= check("cache: persist=off never writes", os.path.exists(p), False)
    ok &= check("cache: persist=off still de-dupes",
                c.get("K1TTT") is not None, True)

    # geometry round-trip
    m = cb.CallbookApp._GEOM_RE.match("344x117+321+123")
    ok &= check("geometry regex keeps position only",
                "{}{}".format(*m.groups()) if m else None, "+321+123")

    # cty.dat: parser + call-area zone refinement (needs the bundled file)
    cty = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "cty.dat")
    if cb.cty_load([cty]):
        def z(call):
            r = cb.cty_lookup(call)
            return int(r["cqzone"]) if r and r["cqzone"] else None
        for call, want in [("W1AW", 5), ("K3LR", 5), ("W6YX", 3), ("K7RAT", 3),
                           ("W1AW/7", 3), ("K1TTT/4", 5), ("VE7CC", 3),
                           ("VA3XYZ", 4), ("VE2IM", 2), ("VY2LI", 5),
                           ("DL1AA", 14), ("9A1A", 15), ("JA1XYZ", 25)]:
            ok &= check("cty zone %s" % call, z(call), want)
        ok &= check("cty VE province", cb.cty_lookup("VE7CC")["state"], "BC")
        ok &= check("cty portable DL/K1TTT", cb.cty_lookup("DL/K1TTT")["country"],
                    "Fed. Rep. of Germany")
    else:
        print("  (skip cty.dat tests - bundled cty.dat not found)")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
