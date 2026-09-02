# SPDX-License-Identifier: Unlicense
"""Headless checks for CallbookApp._render_slots and the cache schema.

No network and no visible window - a fake canvas captures what would be
drawn. A withdrawn Tk root is created only so _font_for can measure text
with real font metrics (it picks the biggest size that fits the canvas
width). Run:  python dev/test_render.py
"""
import functools
import os
import sys
import tempfile
import time
import tkinter as tk

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import n1mm_callbook as cb  # noqa: E402

_ROOT = tk.Tk()
_ROOT.withdraw()
# Matches CallbookApp._build: Canvas(width=360) + highlightthickness 1 each side.
FAKE_CANVAS_W = 362


class FakeCanvas:
    def __init__(self):
        self.text = None
        self.bg = None
        self.fill = None
        self.font = None

    def configure(self, **kw):
        if "bg" in kw:
            self.bg = kw["bg"]

    def itemconfigure(self, _id, **kw):
        if "text" in kw:
            self.text = kw["text"]
        if "fill" in kw:
            self.fill = kw["fill"]
        if "font" in kw:
            self.font = kw["font"]

    def coords(self, *a):
        pass

    def winfo_width(self):
        return FAKE_CANVAS_W

    def winfo_reqwidth(self):
        return FAKE_CANVAS_W


def make(cls):
    app = cls.__new__(cls)
    app.canvas = FakeCanvas()
    app.main_id = 0
    app._font_cache = {}
    app._qrz_tier = ""
    return app


def check(label, got, want):
    ok = "ok  " if got == want else "FAIL"
    print(f"  [{ok}] {label:38} -> {got!r}")
    if got != want:
        print(f"         expected {want!r}")
    return got == want


def main():
    import VHFcallbook as vhf

    hf = make(cb.CallbookApp)
    vh = make(vhf.VHFcallbookApp)
    ok = True

    US = {"name": "Fred", "state": "MA", "cqzone": "5", "country": "United States"}
    US2 = {"name": "Frederick", "state": "MA", "cqzone": "5", "country": "United States"}
    USct = {"name": "Fred", "state": "CT", "cqzone": "5", "country": "United States"}
    USnz = {"name": "Fred", "state": "MA", "cqzone": "", "country": "United States"}
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

    def rsize(app, slots, pending=frozenset()):
        app._render_slots("T", slots, set(pending))
        return app.canvas.font[1]

    ok &= check("HF all agree -> state/zone collapses to one token",
                r(hf, [US, US2, US]), "Fred - MA/5")
    ok &= check("name -> first word only (no surname / club title)",
                r(hf, [{"name": "Goran Andric", "state": "", "cqzone": "15",
                        "country": "Slovenia"}] * 2), "Goran (Slovenia) - 15")
    ok &= check("VHF name -> first word only",
                r(vh, [{"grid": "JN76HD", "name": "David A Minster"}] * 3),
                "David - JN76HD")
    ok &= check("HF all agree -> collapsed line uses the big font",
                rsize(hf, [US, US2, US]), cb.FONT_SIZE_BIG)
    ok &= check("HF short disagreement (fits) -> big font, every slot shown",
                r(hf, [US, USct]), "Fred - MA/5 CT/5")
    ok &= check("HF short disagreement -> big font",
                rsize(hf, [US, USct]), cb.FONT_SIZE_BIG)
    ok &= check("HF short partial (fits) -> big font",
                (r(hf, [US, USnz]), rsize(hf, [US, USnz])), ("Fred - MA/5 MA", cb.FONT_SIZE_BIG))
    ok &= check("HF long disagreement -> falls back to the ladder",
                rsize(hf, [US, USct, US]) != cb.FONT_SIZE_BIG, True)
    ok &= check("HF US, one source has no zone -> no collapse",
                r(hf, [US, USnz, US]), "Fred - MA/5 MA MA/5")
    ok &= check("HF US, 2 slots pending", r(hf, [US, None, None], {1, 2}), "Fred - MA/5 … …")
    ok &= check("HF DX, foreign state dropped, zones agree -> collapse",
                r(hf, [DL, DX, DX]), "Hans (Germany) - 14")
    ok &= check("HF DX collapsed 'name (Country) - zone' -> big font too",
                rsize(hf, [DL, DX, DX]), cb.FONT_SIZE_BIG)
    ok &= check("HF DX, no zone anywhere", r(hf, [DXnz, DXnz, DXnz]), "Hans (Germany)")
    ok &= check("HF empty slot shows '·' (partial, no collapse)",
                r(hf, [US, EMPTY, USnz]), "Fred - MA/5 · MA")
    ok &= check("HF nothing", r(hf, [EMPTY, EMPTY, EMPTY]), "no data")
    ok &= check("HF all failed", r(hf, [None, None, None]), "lookup failed")

    ok &= check("VHF sources disagree -> joined with ' - ', name in front",
                r(vh, [{"grid": "JN76HD", "name": "Hans"},
                       {"grid": "JN76GB", "name": "Hans"},
                       {"grid": "", "name": "Hans"}]),
                "Hans - JN76HD - JN76GB - ·")
    ok &= check("VHF all agree -> collapsed to one locator + name",
                r(vh, [{"grid": "JN76HD", "name": "Hans"}] * 3), "Hans - JN76HD")
    ok &= check("VHF all agree -> collapsed line uses the big font",
                rsize(vh, [{"grid": "JN76HD", "name": "Hans"}] * 3), cb.FONT_SIZE_BIG)
    ok &= check("VHF long disagreement -> normal length-based font",
                rsize(vh, [{"grid": "JN76HD", "name": "Hans"},
                           {"grid": "JN76GB", "name": "Hans"},
                           {"grid": "JN76HD", "name": "Hans"}]) != cb.FONT_SIZE_BIG,
                True)
    ok &= check("VHF short disagreement (fits) -> big font, both slots shown",
                (r(vh, [{"grid": "JN76HD"}, {"grid": "JN76GB"}]),
                 rsize(vh, [{"grid": "JN76HD"}, {"grid": "JN76GB"}])),
                ("JN76HD - JN76GB", cb.FONT_SIZE_BIG))
    ok &= check("VHF collapsed but long name -> still one locator",
                r(vh, [{"grid": "JN76HD", "name": "Wolfgang-Dietrich"}] * 3),
                "Wolfgang-Dietrich - JN76HD")
    ok &= check("VHF collapsed but long name -> falls back to normal font",
                rsize(vh, [{"grid": "JN76HD", "name": "Wolfgang-Dietrich"}] * 3)
                != cb.FONT_SIZE_BIG, True)
    ok &= check("VHF no name, all agree -> bare collapsed locator",
                r(vh, [{"grid": "JN76HD"}] * 3), "JN76HD")
    ok &= check("VHF stale lowercase grid upper-cased then collapsed",
                r(vh, [{"grid": "jn46la"}, {"grid": "JN46LA"}, {"grid": "JN46LA"}]),
                "JN46LA")
    ok &= check("VHF name but no grid anywhere -> name alone",
                r(vh, [{"grid": "", "name": "Hans", "country": "Germany"}] * 3), "Hans")

    # agreement colour
    ok &= check("VHF all agree -> green text",
                rf(vh, [{"grid": "KN04AX"}] * 3), cb.TEXT_AGREE)
    ok &= check("VHF disagree -> default text",
                rf(vh, [{"grid": "KN04AX"}, {"grid": "KN04BX"}, {"grid": "KN04AX"}]), cb.TEXT_DEFAULT)
    ok &= check("VHF one still pending -> not green yet",
                rf(vh, [{"grid": "KN04AX"}, {"grid": "KN04AX"}, None], {2}), cb.TEXT_DEFAULT)
    ok &= check("HF all agree -> green text", rf(hf, [US, US2, US]), cb.TEXT_AGREE)
    ok &= check("HF one source lacks zone -> default text", rf(hf, [US, USnz, US]), cb.TEXT_DEFAULT)

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

    # VHFCtest4WIN <V4W> packet parsing
    v4w_full = (
        b"<V4W><QSOINLOG><CALLSIGN>S56M</CALLSIGN>"
        b"<CALLSIGN_COMPLETE>TRUE</CALLSIGN_COMPLETE><BAND>144 MHz</BAND>"
        b"<QSONUMBER></QSONUMBER><WWL>JN76GB</WWL>"
        b"<WWL_COMPLETE>TRUE</WWL_COMPLETE></QSOINLOG></V4W>"
    )
    ok &= check("v4w: callsign extracted", cb.packet_v4w(v4w_full), "S56M")
    ok &= check("v4w: partial call as typed",
                cb.packet_v4w(b"<V4W><QSOINLOG><CALLSIGN>s51a</CALLSIGN>"
                              b"<WWL>JN</WWL></QSOINLOG></V4W>"), "S51A")
    ok &= check("v4w: cleared field -> None",
                cb.packet_v4w(b"<V4W><QSOINLOG><CALLSIGN></CALLSIGN>"
                              b"<WWL></WWL></QSOINLOG></V4W>"), None)
    ok &= check("v4w: N1MM contactinfo is not a v4w packet",
                cb.packet_v4w(b"<contactinfo><call>S51A</call></contactinfo>"), None)
    ok &= check("v4w: junk -> None", cb.packet_v4w(b"not xml at all"), None)

    # packet_freq_mhz: N1MM frequency fields are in tens of Hz (Callbooker)
    ok &= check("freq: contactinfo rxfreq (144.3 MHz)",
                cb.packet_freq_mhz(b"<contactinfo><band>144</band>"
                                   b"<rxfreq>14430000</rxfreq><call>S50C</call>"
                                   b"</contactinfo>"), 144.3)
    ok &= check("freq: contactinfo 10m (28.074 MHz)",
                cb.packet_freq_mhz(b"<contactinfo><rxfreq>2807400</rxfreq>"
                                   b"<call>W1AW</call></contactinfo>"), 28.074)
    ok &= check("freq: RadioInfo <Freq> (7.025 MHz)",
                cb.packet_freq_mhz(b"<RadioInfo><Freq>702500</Freq>"
                                   b"<OpCall>S55OO</OpCall></RadioInfo>"), 7.025)
    ok &= check("freq: lookupinfo without a frequency -> None",
                cb.packet_freq_mhz(b"<lookupinfo><call>DL1ABC</call>"
                                   b"<mycall>S55OO</mycall></lookupinfo>"), None)
    ok &= check("freq: junk -> None", cb.packet_freq_mhz(b"not xml"), None)

    # qrz_lookup: one source, XML first when credentialled else the web page
    seen = []
    _xml, _web = cb._qrz_xml_lookup, cb._qrz_web_lookup
    cb._qrz_xml_lookup = lambda c, u, p, t=15: seen.append("xml") or {"grid": "AA00"}
    cb._qrz_web_lookup = lambda c, t=15: seen.append("web") or {"grid": "BB11"}
    try:
        r_nocreds = cb.qrz_lookup("W1AW")
        tier_nocreds = cb._QRZ_TIER
        seen.clear()
        r_creds = cb.qrz_lookup("W1AW", "u", "p")
        tier_creds = cb._QRZ_TIER
    finally:
        cb._qrz_xml_lookup, cb._qrz_web_lookup = _xml, _web
    ok &= check("qrz_lookup: no credentials -> web page only",
                (r_nocreds["grid"], tier_nocreds), ("BB11", "web"))
    ok &= check("qrz_lookup: credentials -> XML, web not called",
                (r_creds["grid"], tier_creds, seen), ("AA00", "xml", ["xml"]))

    # Callbooker: the freq picks the HF vs VHF view, VHFCtest4WIN forces VHF
    import Callbooker as ckr
    cbk = ckr.CallbookerApp.__new__(ckr.CallbookerApp)
    cbk._vhf_mode = False
    cbk._qrz_fn = None  # no XML credentials
    cbk._apply_mode(False, force=True)
    ok &= check("Callbooker HF view, no creds -> no QRZ slot, no DX country",
                (cbk.SLOT_FIELDS, cbk.DX_COUNTRY,
                 tuple(cb.source_label(f) for f in cbk.lookup_chain)),
                (("state", "cqzone"), False, ("QRZCQ", "HamQTH")))
    cbk._apply_mode(True)
    ok &= check("Callbooker VHF view, no creds -> web-only QRZ slot prepended",
                (cbk.SLOT_FIELDS, cbk.SLOT_SEP, cbk.DX_COUNTRY,
                 tuple(cb.source_label(f) for f in cbk.lookup_chain)),
                (("grid",), " - ", False, ("QRZ", "QRZCQ", "HamQTH")))
    cbk._qrz_fn = functools.partial(cb.qrz_lookup, username="x", password="y")
    cbk._apply_mode(False, force=True)
    ok &= check("Callbooker HF view, with creds -> QRZ slot present",
                tuple(cb.source_label(f) for f in cbk.lookup_chain),
                ("QRZ", "QRZCQ", "HamQTH"))
    ok &= check("Callbooker: >=30 MHz -> VHF", 144.3 >= ckr.VHF_ABOVE_MHZ, True)
    ok &= check("Callbooker: <30 MHz -> HF", 28.074 >= ckr.VHF_ABOVE_MHZ, False)

    # raw IPv4 packet -> UDP payload (SIO_RCVALL fallback path)
    def ip_udp(dport, payload, sport=6767):
        import socket as _s
        udp = (sport.to_bytes(2, "big") + dport.to_bytes(2, "big")
               + (8 + len(payload)).to_bytes(2, "big") + b"\x00\x00" + payload)
        ip = (b"\x45\x00" + (20 + len(udp)).to_bytes(2, "big")
              + b"\x00\x00\x00\x00\x40\x11\x00\x00"
              + _s.inet_aton("10.147.17.61") + _s.inet_aton("10.147.17.255"))
        return ip + udp
    ok &= check("raw: payload pulled out for matching port",
                cb._udp_payload(ip_udp(6767, v4w_full), 6767), v4w_full)
    ok &= check("raw: wrong port -> None",
                cb._udp_payload(ip_udp(12060, v4w_full), 6767), None)

    # _on_v4w_call: multi-op source filter - only this PC's VHFCtest4WIN
    fake = cb.CallbookApp.__new__(cb.CallbookApp)
    fake._v4w_inbox = []
    fake.local = {"192.168.1.5", "127.0.0.1"}
    fake._on_v4w_call("S51A", "192.168.1.5")   # this PC
    fake._on_v4w_call("OM3KII", "192.168.1.9")  # another op on the subnet
    fake._on_v4w_call("S59ABC", "127.0.0.1")   # this PC, loopback broadcast
    ok &= check("v4w: only local-source callsigns queued",
                fake._v4w_inbox, ["S51A", "S59ABC"])

    # geometry round-trip
    m = cb.CallbookApp._GEOM_RE.match("344x117+321+123")
    ok &= check("geometry regex keeps position only",
                "{}{}".format(*m.groups()) if m else None, "+321+123")

    # start-up self-test: source labels + the per-line render
    ok &= check("source_label: plain function",
                cb.source_label(cb.qrzcq_lookup), "QRZCQ")
    ok &= check("source_label: functools.partial unwrapped",
                cb.source_label(functools.partial(cb.qrz_lookup, username="x")),
                "QRZ")

    pc = make(cb.CallbookApp)
    pc.current = None
    pc._precheck_active = True
    pc.source_labels = ("QRZ", "QRZCQ", "HamQTH")
    pc._precheck = [("OK", 312.0), ("no data", 181.4), None]
    pc._render_precheck()
    ok &= check("precheck: mixed line render",
                pc.canvas.text,
                "QRZ     OK       312 ms\nQRZCQ   no data  181 ms\nHamQTH  …")
    pc._qrz_tier = "xml"
    pc._render_precheck()
    ok &= check("precheck: QRZ line shows the tier",
                pc.canvas.text.split("\n")[0], "QRZ·xml OK       312 ms")
    pc._qrz_tier = ""
    pc._precheck = [("OK", 312.0), ("OK", 181.0), ("OK", 233.0)]
    ok &= check("precheck: all OK -> green",
                (pc._render_precheck() or pc.canvas.fill), cb.TEXT_AGREE)
    pc._precheck = [("OK", 312.0), ("FAIL", 15000.0), ("OK", 233.0)]
    ok &= check("precheck: a FAIL -> default text",
                (pc._render_precheck() or pc.canvas.fill), cb.TEXT_DEFAULT)
    pc.current = "W1AW"
    pc.canvas.text = "unchanged"
    pc._render_precheck()
    ok &= check("precheck: suppressed once a real call is on screen",
                pc.canvas.text, "unchanged")

    print("\nALL PASS" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
