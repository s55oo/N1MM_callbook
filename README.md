# Callbooker – contest callbook for HF and VHF

> **Version:** 1.1 · Made by **S55OO** with AI assistance.
> · **Public domain** – see [LICENSE](LICENSE).

A compact always-on-top window that listens to your logger's UDP broadcast
and looks up the callsign you are working. **Every source is queried in
parallel** and **all** of its values are shown side by side, so when the
sources disagree the wrong one stands out and you pick the right value for
the exchange. When they all agree the row collapses to a single value in a
larger green font – a quick "you can trust this".

It listens on **two feeds at once** and picks the right view per callsign:

- a callsign from **VHFCtest4WIN** (its sharing broadcast, UDP **6767**,
  sent as you type) → the **VHF** view: first name + each source's
  **QRA/maidenhead locator** (`Hans - JN76HD`);
- a callsign from **N1MM Logger+** (UDP **12060**) → the **operating
  frequency** decides: **≥ 30 MHz → VHF**, **< 30 MHz → HF** (first name +
  **CQ zone**, plus the **US state** for North-American calls –
  `Fred - MA/5`).

So one window covers an HF station, a VHF station, and VHFCtest4WIN's
pre-log check – no switching apps or modes.

### Sources

| Source | Free? | What it gives |
|---|---|---|
| **QRZ.com** | login optional | the paid [XML API](https://www.qrz.com/page/xml_data.html) (full record incl. grid, state, CQ zone) when a QRZ login is configured and the subscription is live; otherwise the public `/db/` page for the **locator only**. **One column either way** – qrz.com is never queried twice. |
| **[QRZCQ.com](https://www.qrzcq.com)** | yes, no account | name, locator, US state, CQ zone from `qrzcq.com/call/<CALL>` |
| **[HamQTH.com](https://www.hamqth.com)** | yes, no account | name, locator, country from `hamqth.com/<CALL>` |

The QRZ column is always shown in the VHF view (the public page still
yields the locator with no login); in the HF view it appears only when
QRZ credentials are configured.

The UI follows the same design language as the **PingPong** lamp: a small
topmost Tkinter window with a colored canvas and a help icon.

---

## 1. Logger setup

### N1MM Logger+

1. **File → Settings → Configurer → Broadcast Data** (a.k.a. External
   Broadcast), enable:
   - **External Callsign Lookup** – sends a `LookupInfo` packet after you
     type a callsign and press **Space** (moving to the exchange field).
     This is the primary trigger.
   - **Contacts** – sends a `ContactInfo` packet when a QSO is logged.
2. Set the **IP:Port** to your PC's address (or the subnet broadcast) and
   port **12060**.
3. Make sure **Broadcast Data is enabled** on the transmitting computer.

Callbooker listens on all interfaces and picks the worked callsign out of
the `LookupInfo` / `ContactInfo` packet. It ignores the local operator's
own call in `RadioInfo`, but **does** read the **frequency** from it as a
fallback for the HF/VHF decision.

### Which view — HF or VHF?

- A callsign from **VHFCtest4WIN** (6767) → **VHF** always.
- A callsign from **N1MM** → by the **frequency**: N1MM puts it in the
  `LookupInfo` / `ContactInfo` packet (`rxfreq`), and Callbooker also
  tracks the last `RadioInfo` frequency as a fallback. **≥ 30 MHz → VHF**
  (locators), **< 30 MHz → HF** (name / zone / state).
- With **no frequency** seen yet, Callbooker opens in the **view it was
  last using** (remembered between runs; HF on a first run).

The country is never appended after the name in either view – the CQ zone
is the multiplier that matters and the name stays short.

### The VHFCtest4WIN feed (6767)

**VHFCtest4WIN** (S52AA's VHF contest logger) does not send N1MM
`LookupInfo` packets. Instead it broadcasts the callsign in its entry
field on its **multi-op sharing broadcast** (UDP **6767**) **as it is
typed**. Callbooker listens on 6767 **in addition to** the N1MM port, so
with VHFCtest4WIN the lookup runs *before* the QSO is logged and a wrong
QRA locator can be caught while it is still editable. The feed is **on by
default**; set `vhfctest_share=no` in `Callbooker.cfg` to turn it (and the
UAC prompt below) off.

- Nothing to switch on in VHFCtest4WIN – it already broadcasts its entry
  field on 6767 as part of normal network sharing.
- **Port 6767 / UAC.** VHFCtest4WIN keeps 6767 open with an exclusive
  lock, so the only way to read the broadcast while it runs is a raw
  capture socket, which needs elevation. When VHFCtest4WIN is already up,
  Callbooker **relaunches itself elevated** – one **UAC prompt, click
  Yes**. Decline it and the window still opens (N1MM feed only) and tells
  you what to do. No prompt when VHFCtest4WIN is not running yet, or when
  the 6767 feed is disabled.
- Start VHFCtest4WIN **first**, then Callbooker – the other way round on
  the same PC would take 6767 and break VHFCtest4WIN's own network
  sharing.
- **Multi-op:** VHFCtest4WIN broadcasts to the whole network, so every PC
  sees every operator's typing. Callbooker ignores everything except
  **its own PC's** VHFCtest4WIN, so each position's window follows only
  that operator (same local-computer-only rule as the N1MM feed).
- On another PC on the multi-op network, an ordinary listener works with
  no prompt.

---

## 2. Running

```
        double-click:  Callbooker.exe      (standalone, no Python needed)
   or:  run:  pythonw Callbooker.py        (from source, no console window)
```

`Callbooker.exe` prompts for **UAC** once when VHFCtest4WIN is already
running (see section 1).

Arguments:

```
python Callbooker.py [--port 12060] [--config Callbooker.cfg]
```

- `--port` – N1MM UDP port (default 12060).
- `--config` – path to the config file (defaults to `Callbooker.cfg` next
  to the exe/script).

---

## 3. Configuration

`Callbooker.cfg` next to the exe – **optional**, the app runs with
defaults when it is absent. Copy `Callbooker.cfg.template` and edit:

```
[settings]
udp_port=12060
cache_days=30
cache_file=Callbooker_cache.json
cache_persist=yes                 # no = in-memory only, never writes to disk

# Start-up self-test (query every source once on launch, show OK / time):
# selftest=yes
# selftest_call=S55OO             # call to probe; blank / selftest=no disables

# QRZ.com login - the QRZ column uses the paid XML API when this is set
# and the subscription is live, otherwise the public page (locator only):
# qrz_username=S55OO
# qrz_password=YOUR_QRZ_PASSWORD

# VHFCtest4WIN pre-log feed, UDP 6767 (see section 1). On by default;
# set no to turn it - and the UAC prompt - off:
# vhfctest_share=no
# vhfctest_port=6767
```

There is **no HF/VHF-mode key** – Callbooker picks the view from the
frequency and remembers the last one between runs.

- `Callbooker.cfg` and its `cache_file` are read/written from the folder
  the exe/script lives in. Callbooker also writes `Callbooker_window.json`
  (last window position **and** last view) and `qrz_session.json` (the
  QRZ XML session key, so a restart skips the ~0.6 s re-login) – both are
  safe to delete and are gitignored.
- **`Callbooker.cfg` is gitignored** – it holds your QRZ login in plain
  text, so it is never committed. Only `Callbooker.cfg.template` (with a
  placeholder password) is in the repo.
- The `.exe` does **not** embed the `.cfg`; it reads it from disk at run
  time, so shipping the EXE never leaks your password.

---

## 4. Behavior

- When a `LookupInfo` (call + Space) or `ContactInfo` (QSO logged) packet
  arrives, the window shows the worked callsign in the footer
  **immediately** and starts the lookup. **All sources are queried in
  parallel** and **each slot fills the moment that source answers** – `…`
  marks a slot still running. You might see `FRED - MA/5 … …` first, then
  the rest fill in.
- **When every source that answered agrees**, the text turns light green
  **and the repeated token collapses to one** – `FRED - MA/5 MA/5 MA/5`
  shows as **`FRED - MA/5`**. A disagreement (`FRED - MA/5 MA/4 MA/5`), or
  a source that returned only part (`MA` vs `MA/5`), keeps every slot
  visible so the odd one out is obvious.
- **The font is as large as the line allows** – measured, not guessed:
  the collapsed token, a `name - zone` DX line and a short two-source
  disagreement all get the big font; a long side-by-side row steps down
  until it fits the window.
- The **name** is the operator's **first word only** (`Goran Andric` →
  `Goran`, `ARRL HQ OPERATORS CLUB` → `ARRL`), printed once in front.
- **HF view:** `first name - state/zone` per source. A slot shows just
  the state when that source has no CQ zone, just the zone for a non-US
  station, or `·` when it returned neither.
- **VHF view:** `first name - locator` per source, separated by ` - `.
- **Local computer only:** the app only reacts to packets from *this* PC
  (identified by its local interface IPs), so only the local operator's
  callsign triggers a lookup.
- **Cache** (`Callbooker_cache.json`): a re-worked call resolves instantly
  and the servers aren't hit twice. Written **at most once a minute** (and
  once on close), stores only the displayed fields, prunes expired entries
  on load. `cache_days` (default 30) is the freshness window;
  `cache_persist=no` keeps it in memory only. The cache carries a schema
  version, so after an upgrade that changes the stored shape older entries
  re-fetch automatically.
- If the lookup fails the main area shows `lookup failed`; a callsign with
  no record shows `no data`.
- **Start-up self-test.** On launch, before the first callsign, each
  source is queried once and the window lists them one per line with the
  result and round-trip time:

  ```
  QRZ·xml OK       521 ms
  QRZCQ   OK       152 ms
  HamQTH  OK       236 ms
  ```

  `OK` = answered and parsed · `no data` = reachable, no record for the
  test call · `FAIL` = network/HTTP error. The **QRZ** line shows which
  path it took – `QRZ·xml` (paid API) or `QRZ·web` (public-page
  fall-back) – and the footer summary adds the subscription expiry, e.g.
  `self-test: 3/3 sources OK · QRZ XML sub to 2027`. All-green when every
  source is `OK`. Holds a few seconds, then the window goes idle (the
  footer summary stays until the first lookup). Test callsign defaults to
  **S55OO**; set `selftest_call=` to another, or `selftest=no` to skip.
- **Fast lookups:** one kept-alive HTTPS connection per host, gzip'd
  responses – the ~90 ms TLS handshake isn't paid every QSO. Time to fill
  all slots is ~155 ms (median) in testing.
- The small **help icon** (top-right) opens the project page in your
  browser.

---

## 5. Building the standalone EXE (for PCs without Python)

Requires Python + PyInstaller:

```bat
python -m pip install pyinstaller
python -m PyInstaller --onefile --windowed --name Callbooker --manifest manifest.xml Callbooker.py
copy /Y dist\Callbooker.exe Callbooker.exe
```

`manifest.xml` makes the window use modern common controls. The result is
a single standalone EXE (no Python required) – copy it to the other
computers together with the (optional) `Callbooker.cfg`.

---

## 6. Files

```
Callbooker.py           – the app (feeds, HF/VHF view switch, UAC self-relaunch)
Callbooker.exe          – standalone executable (built, no Python needed)
Callbooker.cfg.template – config template (copy to Callbooker.cfg, drop .template)
Callbooker.cfg          – live config (gitignored; holds the QRZ login in plain text)
n1mm_callbook.py        – the engine: CallbookApp window, run(), the source functions
Callbooker.spec         – PyInstaller build settings
manifest.xml            – PyInstaller manifest (common controls)
Callbooker_cache.json   – local lookup cache          (auto-created, gitignored)
Callbooker_window.json  – last window position + view (auto-created, gitignored)
qrz_session.json        – cached QRZ XML session key   (auto-created, gitignored)
LICENSE                 – The Unlicense (public domain)
CLAUDE.md               – developer notes (architecture, gotchas, release steps)
dev/test_render.py      – headless display-logic tests (no network)
dev/bench_latency.py    – lookup-latency benchmark
dev/*.py, dev/*.md      – VHFCtest4WIN reverse-engineering notes and sniff tools
```

---

## 7. Changelog

Callbooker replaces the earlier separate apps (`n1mm_callbook` for HF,
`VHFcallbook` for VHF, and before that `n1mm_VHFcallbook` /
`VHFctest4WinCallbook`). All of their features are in `Callbooker` 1.1.

- **1.1** – single-app release. One window, two feeds (N1MM 12060 +
  VHFCtest4WIN 6767), HF/VHF view chosen per callsign from the operating
  frequency (`rxfreq` in the packet, or the last `RadioInfo`), remembered
  between runs. QRZ is one column (paid XML API when the login/subscription
  works, else the public page for the locator – never queried twice), and
  the self-test shows which path it took. Agreed values collapse to one
  larger green token; the result line is drawn at the biggest font that
  fits. Names are trimmed to the first word; no country after the name.
  Public domain.

---

## 8. License

Released into the **public domain** under [The Unlicense](LICENSE) – do
whatever you want with it, no attribution required.

The standalone EXE bundles the Python runtime and Tcl/Tk, which keep their
own permissive licenses (PSF and BSD-style); PyInstaller's bootloader
carries an explicit exception that allows shipping the frozen app under
any license.
