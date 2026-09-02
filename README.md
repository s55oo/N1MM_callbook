# N1MM Callbook – N1MM Logger+ Contest Callbook

> **Version:** 1.0 (`Callbooker` – HF + VHF in one) · 2.17 (HF – `n1mm_callbook`)
> · 1.2 (VHF – `VHFcallbook`) · Made by **S55OO** with AI assistance.
> · **Public domain** – see [LICENSE](LICENSE).

> **`Callbooker` (recommended)** does the job of both apps below in one
> window. It listens on the N1MM Logger+ port (**12060**) **and**
> VHFCtest4WIN's port (**6767**) and picks the view per callsign:
> a VHFCtest4WIN callsign, or an N1MM one on **≥ 30 MHz**, gets the
> **VHF** locator view; an N1MM callsign **< 30 MHz** gets the **HF**
> name / CQ-zone / state view. See [section 1](#which-view-hf-or-vhf).
> `n1mm_callbook` and `VHFcallbook` stay available for now as the
> single-purpose apps.

A compact always-on-top window that listens to the N1MM Logger+ external
UDP broadcast (XML, port **12060**) and automatically looks up the callsign
you are working. Every source is queried **in parallel** and **all** of its
values are shown side by side – each slot filling in the moment that
source answers, so nothing waits for the slowest one – and when the
sources disagree the wrong one stands out and you can pick the right one.
The window shows the worked station's **name**, then each source's
**US state and CQ zone** as one `state/zone` token, and the **callsign**
in the footer (the operator's **first name** only, printed once). When
the sources **disagree** you see every token – `Fred - MA/5 MA/4 MA/5` –
and pick the right one; when they **all agree** it collapses to a single
`state/zone` in a **larger green font** – `Fred - MA/5` – a quick "you can
trust this" signal. For a **non-US (DX) station**, where there is no US
state, the HF window shows the **operator name and country** followed by
the **CQ zone**, e.g. `Hans (Germany) - 14`.

The HF callbook pulls its **state, CQ zone** and name from up to **three
sources**: **[QRZ.com](https://www.qrz.com),
[QRZCQ.com](https://www.qrzcq.com) and
[HamQTH.com](https://www.hamqth.com)**, queried at the same time and shown
left-to-right in that order. **QRZ is one column** – the paid
[XML API](https://www.qrz.com/page/xml_data.html) when your QRZ login is
configured and the subscription is live, otherwise the public page as a
fall-back (never both). Without QRZ credentials the HF app runs the two
free sources.

A **VHF variant** (`VHFcallbook.py` / `VHFcallbook.exe`) is also included.
It uses the same engine but shows the worked station's **QRA/maidenhead
locator** (e.g. `JN76HD`) in the main area, with the **operator name** in
front of it, from the sources shown side by side – handy for VHF/UHF
contests where the grid square is the exchange. When every source that
answered returns the **same** locator the row collapses to a single value
in a **larger green font** (`Goran - JN76HD`) – a quick "grid confirmed"
signal; when they differ you see each one and can pick the right value.
`VHFcallbook` also listens on **VHFCtest4WIN**'s sharing port (6767)
alongside the N1MM port, so it works with either logger and can run the
lookup *as the callsign is typed*, pre-log – see [section 1](#the-vhfctest4win-feed-6767).
The **locator sources**:

| Source | How the locator is read |
|---|---|
| QRZ.com | the XML API (`grid` field) with a QRZ login + subscription, otherwise computed from the coordinates embedded in the public `https://www.qrz.com/db/<CALL>` page – **one column either way** |
| QRZCQ.com | `Grid:` / `Locator:` row on `https://www.qrzcq.com/call/<CALL>` |
| HamQTH.com | `Grid:` row on `https://www.hamqth.com/<CALL>` |

All sources are queried **in parallel** and each slot fills as soon as
that source replies. On VHF the QRZ column is always present (the public
page still yields the locator with no login); on HF it appears only with
credentials.

QRZCQ.com is a free public callbook that needs **no account and no API key** –
each callsign has a page at `https://www.qrzcq.com/call/<CALL>` whose lookup
info this app reads.

The UI follows the same design language as the **PingPong** lamp: a small
topmost Tkinter window with a colored canvas and a help icon.

---

## Screenshot

![N1MM Callbook](n1mm_callbook.png)

---

## 1. N1MM Logger+ setup

1. In N1MM Logger+: **File → Settings → Configurer → Broadcast Data**
   (a.k.a. External Broadcast), enable:
   - **External Callsign Lookup** – sends a `LookupInfo` packet after you
     type a callsign and press **Space** (i.e. as you move to the exchange
     field). This is the primary trigger for the callbook.
   - **Contacts** – sends a `ContactInfo` packet when a QSO is logged.
2. Set the **IP:Port** next to them to your PC's address (or the subnet
   broadcast) and port **12060**.
3. Make sure **Broadcast Data is enabled** on the transmitting computer.

> The app listens on all interfaces and picks the worked callsign out of
> the `LookupInfo`/`ContactInfo` packet automatically. The local
> operator's own call in `RadioInfo` is ignored – but `Callbooker` does
> read the **frequency** from `RadioInfo` (see below).

### Which view, HF or VHF?

Only `Callbooker` has both views; `n1mm_callbook` is always HF and
`VHFcallbook` is always VHF. `Callbooker` decides per callsign:

- A callsign from **VHFCtest4WIN** (UDP 6767) → **VHF** view always.
- A callsign from **N1MM** → by the **operating frequency**. N1MM puts it
  in the `LookupInfo` / `ContactInfo` packet (`rxfreq`), and `Callbooker`
  also tracks the last `RadioInfo` frequency as a fallback:
  **≥ 30 MHz → VHF** (locators), **< 30 MHz → HF** (name / zone / state).
- When no frequency has been seen yet, `Callbooker` opens in the **view it
  was last using** (remembered between runs; HF on a first run).

The **VHF** view shows the operator name + each source's QRA locator; the
**HF** view shows the name + `state/zone` (state only for North-American
calls). Everything else – parallel sources, the agree/collapse behaviour,
the cache, the self-test – is identical in both.

### The VHFCtest4WIN feed (6767)

**VHFCtest4WIN** (S52AA's VHF contest logger) does not send N1MM
`LookupInfo` packets. Instead it broadcasts the callsign in its entry
field on its **multi-op sharing broadcast** (UDP **6767**) **as it is
typed**. `Callbooker` and `VHFcallbook` listen on 6767 **in addition to**
the N1MM port (12060), so with VHFCtest4WIN the lookup runs *before* the
QSO is logged and a wrong QRA locator can be caught while it is still
editable. The feed is **on by default**; set `vhfctest_share=no` in the
`.cfg` to turn it (and the UAC prompt below) off. (The plain
`n1mm_callbook` HF app has no 6767 feed.)

- Nothing to switch on in VHFCtest4WIN – it already broadcasts its entry
  field on 6767 as part of normal network sharing.
- **Port 6767 / UAC.** VHFCtest4WIN keeps 6767 open with an exclusive
  lock, so the only way to read the broadcast while it runs is a raw
  capture socket, which needs elevation. When VHFCtest4WIN is already up,
  the app **relaunches itself elevated** – you just get one **UAC prompt,
  click Yes**. Decline it and the window still opens (N1MM feed only) and
  tells you what to do. No prompt when VHFCtest4WIN is not running yet, or
  when the 6767 feed is disabled.
- Start VHFCtest4WIN **first**, then the callbook – starting it the other
  way round on the same PC would take 6767 and break VHFCtest4WIN's own
  network sharing.
- **Multi-op:** VHFCtest4WIN broadcasts to the whole network, so every
  PC sees every operator's typing. The app ignores everything except
  **its own PC's** VHFCtest4WIN, so each position's window follows only
  that operator (same local-computer-only rule as the N1MM feed).
- On another PC on the multi-op network, an ordinary listener works with
  no prompt.

---

## 2. Running

**Callbooker** – HF + VHF in one window, listens on 12060 *and* 6767,
picks the view per callsign (**recommended**):

```
   or:  run:  pythonw Callbooker.py        (from source, no window)
   or:  run:  Callbooker.exe               (standalone; prompts for UAC
                                            when VHFCtest4WIN is already
                                            running – see section 1)
```

Single-purpose apps – HF only (`n1mm_callbook`, no 6767 feed) / VHF only
(`VHFcallbook`, 12060 + 6767):

```
        double-click:  Callbook.bat        (n1mm_callbook from source)
   or:  run:  n1mm_callbook.exe    /    VHFcallbook.exe
```

Arguments:

```
python Callbooker.py    [--port 12060] [--config Callbooker.cfg]
python n1mm_callbook.py  [--port 12060] [--config callbook.cfg]
python VHFcallbook.py    [--port 12060] [--config VHFcallbook.cfg]
```

- `--port` – UDP port (default 12060).
- `--config` – path to the matching `.cfg` file.

> Several can run at the same time (e.g. one on each radio or monitor).
> They share the local-computer-only filtering and each keep their own
> cache file, so they never interfere with each other.

---

## 3. Behavior

- When a `LookupInfo` (type a call + press Space) or `ContactInfo` (QSO
  logged) packet arrives, the window shows the worked callsign in the
  footer **immediately** and starts the lookup. **All sources are queried
  in parallel** and **each slot's value is shown the moment that source
  answers** – `…` marks a slot still running. A slow source never holds up
  a fast one: you might see `FRED - MA/5 … …` first, then the rest fill in
  to `FRED - MA/5 MA/5 MA/5`.
- The slots are laid out left-to-right in a fixed order –
  **QRZ, QRZCQ.com, HamQTH.com**. QRZ is **one column**: the paid XML API
  when your login works, else the public page (never both, so qrz.com
  isn't queried twice). The QRZ column shows on HF only with credentials;
  on VHF it is always there (the public page still gives the locator). The
  order is just the column layout, not a priority – every source is
  fetched at the same time. When the values differ (e.g. `MA/5 MA/4 MA/5`)
  you see it immediately and can decide which one is right for the
  exchange.
- **When every source that answered agrees**, the text turns light green
  **and the repeated token collapses to one** – so `FRED - MA/5 MA/5 MA/5`
  shows as **`FRED - MA/5`** – a quick "you can trust this" signal. A
  disagreement (`FRED - MA/5 MA/4 MA/5`), or a source that returned only
  part (`MA` vs `MA/5`), keeps every slot visible.
- **The font is as large as the line allows.** The result is drawn at the
  biggest size that actually fits the window – the collapsed token, a
  `name (Country) - zone` DX line, and a short two-source disagreement all
  get the **big font**; a long side-by-side row steps down until it fits.
- For a **US station** the main area shows the operator's **first name**
  (printed once) followed by the **`state/zone`** token – one per source
  when they differ, a single one when they agree. A slot shows just the
  state when that source has no CQ zone (`MA`), just the zone for a
  DX-style entry, or `·` when it returned neither.
- For a **non-US (DX) station** there is no US state, so the HF window
  shows the **operator name and country** followed by the **CQ zone**,
  e.g. `Hans (Germany) - 14` (or `Hans (Germany) - 14 14` when the sources
  disagree, or just `Hans (Germany)` when none reports a zone). A foreign
  subdivision that QRZ XML sometimes returns in the state field (e.g. `HE`
  for a German call) is ignored; the CQ zone, which is meaningful
  worldwide, is kept.
- The **VHF variant** shows the **QRA/maidenhead locator** the same
  side-by-side way, separated by ` - `, with the **operator name** printed
  once in front – `Hans - JN76GB - JN76HD - JN76HD` when the sources
  disagree, collapsing the same way to `Hans - JN76HD` when they agree. It
  has no country/DX handling – for a VHF exchange only the grid and the
  name matter.
- **Local computer only:** the app only reacts to packets sent from *this*
  PC (identified by its local interface IPs). Broadcasts from other
  stations on the network are ignored, so only the local operator's
  callsign triggers a lookup.
- Lookups are cached (`callbook_cache.json` / `VHFcallbook_cache.json`)
  so a re-worked call resolves instantly and the servers aren't hit twice.
  The file is written **at most once a minute** (and once on close), not on
  every lookup, and it stores only the fields the window shows. Expired
  entries are pruned when it loads, so it doesn't grow forever.
- `cache_days` (default 30) sets how long an entry stays fresh.
  `cache_persist=no` keeps the cache **in memory only** – zero disk writes,
  still de-dupes within the session – for a big contest where you don't
  need the cache afterwards. The cache also carries a schema version, so
  after an upgrade that changes the stored shape older entries re-fetch
  automatically. Deleting the file forces a full refresh.
- If the lookup fails the main area shows `lookup failed`; if a callsign
  has no entry it shows `no data`.
- **Start-up self-test.** On launch, before the first callsign, each
  configured source is queried once and the window lists them one per
  line with the result and the round-trip time, e.g.

  ```
  QRZ·xml OK       521 ms
  QRZCQ   OK       152 ms
  HamQTH  OK       236 ms
  ```

  `OK` = answered and parsed, `no data` = reachable but no record for the
  test call, `FAIL` = network/HTTP error (that source is down). The **QRZ**
  line shows which path it took – `QRZ·xml` (paid API) or `QRZ·web`
  (public page fall-back) – and the footer summary adds the subscription
  expiry, e.g. `self-test: 3/3 sources OK · QRZ XML sub to 2027`. The text
  turns light green when every source is `OK`. The result stays up for a
  few seconds, then the window goes idle (the footer summary stays until
  the first lookup). The test callsign defaults to **S55OO**; set
  `selftest_call=` to another call, or `selftest=no` to skip it.
- **Fast lookups:** the connection to each source is kept alive and
  re-used between QSOs, and responses are gzip-compressed, so the ~90 ms
  TLS handshake isn't paid every time. In testing this cut the time to
  fill all three HF slots from ~385 ms to ~155 ms (median).
- The **window remembers where you put it** (`*_window.json`, next to the
  cache), and the QRZ XML session key is kept across restarts
  (`qrz_session.json`), skipping the ~0.6 s re-login on the first lookup.
- The small **help icon** (top-right) opens the project page
  (`https://github.com/s55oo/N1MM_callbook/`) in your browser.

---

## 4. Configuration

`Callbooker.cfg` / `callbook.cfg` / `VHFcallbook.cfg` – one per app, all
optional (the apps run with defaults when no `.cfg` exists). Each has a
`*.cfg.template` in the repo to copy. Same keys for all three:

```
[settings]
udp_port=12060
cache_days=30
cache_file=Callbooker_cache.json         (or callbook_ / VHFcallbook_)
cache_persist=yes                        (no = in-memory only, never writes)

# Start-up self-test (query every source once on launch, show OK / time):
# selftest=yes
# selftest_call=S55OO                    (call to probe; blank/selftest=no disables)

# QRZ.com login - the QRZ column uses the paid XML API when this is set
# and the subscription is live, otherwise the public page (locator only):
# qrz_username=S55OO
# qrz_password=YOUR_QRZ_PASSWORD

# VHFCtest4WIN pre-log callsign feed, UDP 6767 (see section 1). Callbooker
# and VHFcallbook only; on by default, set no to also stop the UAC prompt.
# vhfctest_share=no
# vhfctest_port=6767
```

`Callbooker` has no HF/VHF-mode key – it picks the view from the
frequency (≥ 30 MHz → VHF), and remembers the last view between runs.

- Each `.cfg` and its matching `cache_file` are read/written from the same
  folder as the executable/script. The app also writes a small
  `*_window.json` (last window position) and `qrz_session.json` (QRZ XML
  session key) there – both are safe to delete and are gitignored.
- The `.cfg` files are **gitignored** – they hold your QRZ login in
  **plain text**, so they are never committed and never land in a shared
  build. Only the `*.cfg.template` files (with placeholder credentials) are
  in the repo. Copy the matching template, fill in your QRZ credentials,
  and rename (drop the `.template`).
- The built `.exe` files do **not** embed the `.cfg`; they read it from
  disk at run time, so shipping an EXE never leaks your password.

---

## 5. Building the standalone EXEs (for PCs without Python)

Requires Python + PyInstaller:

```bat
python -m pip install pyinstaller

REM Callbooker (combined HF + VHF):
python -m PyInstaller --onefile --windowed --name Callbooker --manifest manifest.xml Callbooker.py
copy /Y dist\Callbooker.exe Callbooker.exe

REM HF-only callbook:
python -m PyInstaller --onefile --windowed --name n1mm_callbook --manifest manifest.xml n1mm_callbook.py
copy /Y dist\n1mm_callbook.exe n1mm_callbook.exe

REM VHF-only locator lookup (N1MM 12060 + VHFCtest4WIN 6767):
python -m PyInstaller --onefile --windowed --name VHFcallbook --manifest manifest.xml VHFcallbook.py
copy /Y dist\VHFcallbook.exe VHFcallbook.exe
```

`manifest.xml` makes the windows use modern common controls. The results are
single standalone EXEs (no Python required) – copy them to the other
computers together with the (optional) matching `.cfg`.

---

## 6. Files

```
Callbooker.py        – combined HF + VHF app (picks the view per callsign); source
Callbooker.exe       – combined app, standalone executable (no Python needed)
n1mm_callbook.py/.exe – HF-only callbook (source + executable)
VHFcallbook.py/.exe  – VHF-only locator lookup: N1MM (12060) + VHFCtest4WIN (6767)
*.cfg.template       – config template, one per app (copy, drop the .template)
*.cfg                – live configs (gitignored; may hold QRZ login in plain text)
*_cache.json         – per-app local lookup cache (auto-created, gitignored)
*_window.json        – last window position (and, for Callbooker, last view) per app
qrz_session.json     – cached QRZ XML session key (auto-created, gitignored)
Callbook.bat         – source launcher (no console)
manifest.xml         – PyInstaller manifest (common controls)
*.spec               – PyInstaller build settings (one per app)
dist\                – PyInstaller output
CLAUDE.md            – developer notes (architecture, gotchas, release steps)
dev\test_render.py   – headless display-logic tests (no network)
dev\bench_latency.py – lookup-latency benchmark
```

> The QRZ column uses the paid **XML API** (needs a subscription for the
> full record) when your login works, and falls back to the public
> `/db/` page (locator from the embedded coordinates – free, no login)
> otherwise. It is never queried both ways. QRZCQ and HamQTH are always
> free.

---

## 7. Changelog

> **VHF app history.** Through **v2.16** the VHF side was two apps –
> `n1mm_VHFcallbook` (N1MM feed) and `VHFctest4WinCallbook` (VHFCtest4WIN
> 6767 feed). **v2.17** added `VHFcallbook`, which does both at once.
> **v2.18** (`VHFcallbook` 1.1) **removed `n1mm_VHFcallbook` and
> `VHFctest4WinCallbook` entirely** – `VHFcallbook` is the only VHF app
> now. Older entries below that name the retired apps are historical; the
> feature they describe lives in `VHFcallbook` today.

- **v2.20 – name is the first name only.** The displayed name is trimmed
  to its first word (`Goran Andric` → `Goran`, `ARRL HQ OPERATORS CLUB` →
  `ARRL`) – a contest exchange never wants the surname or a club's full
  title.
- **v2.20 – QRZ is now one column.** The separate `QRZ XML` and `QRZ web`
  slots are merged: the paid XML API when your QRZ login works and the
  subscription is live, otherwise the public `/db/` page for the locator –
  **never both**, so qrz.com isn't hit twice and a station no longer shows
  two identical QRZ columns. The start-up self-test's QRZ line says which
  path it took (`QRZ·xml` / `QRZ·web`) and the footer adds the
  subscription expiry. On VHF the QRZ column is always present (public
  page needs no login); on HF only with credentials.
- **v2.20 – new: `Callbooker` 1.0** – the HF (`n1mm_callbook`) and VHF
  (`VHFcallbook`) apps in **one window** that picks the view per callsign:
  a **VHFCtest4WIN** callsign, or an N1MM one **≥ 30 MHz**, gets the VHF
  locator view; an N1MM callsign **< 30 MHz** gets the HF name / zone /
  state view. The frequency comes from the N1MM packet (`rxfreq`) or the
  last `RadioInfo`; with no frequency yet it opens in the view it was last
  using (remembered between runs, HF on a first run). New engine helper
  `packet_freq_mhz`. New `Callbooker.cfg`.
- **v2.19 – HF 2.17 / VHF 1.2** – **agreed `state/zone` collapses, and a
  bigger, width-aware font.** The HF window now does what the VHF one
  already did: when every source returns the **same state and CQ zone**,
  the repeated `state/zone` token merges into one (`Fred - MA/5 MA/5 MA/5`
  → `Fred - MA/5`), still green (shared `COLLAPSE_ON_AGREE` engine flag –
  now on for both apps). The result line is now drawn at the **largest
  font that actually fits** (measured, not guessed): the collapsed token,
  a `name (Country) - zone` DX line and a short disagreement all get the
  big font; long side-by-side rows step down to fit. The window is a touch
  wider to give the big font room.
- **v2.18 / `VHFcallbook` 1.1** – `n1mm_VHFcallbook` and
  `VHFctest4WinCallbook` **deleted** (source, EXEs, config templates, spec
  files). `VHFcallbook` already did everything both did – a single window
  on **both** UDP **12060** (N1MM Logger+) and **6767** (VHFCtest4WIN),
  6767 on by default. Its `VHFApp` base class was folded straight into
  `VHFcallbook.py` so nothing imports the removed module; no behaviour
  change. **Migrating:** copy the values from your old
  `n1mm_VHFcallbook.cfg` / `VHFctest4WinCallbook.cfg` into
  `VHFcallbook.cfg`, then the old `.cfg` and `*_cache.json` files can be
  deleted. HF app (`n1mm_callbook` 2.16) unchanged.
- **v2.17 / `VHFcallbook` 1.0** – new `VHFcallbook` app: the two VHF apps'
  jobs in **one window** that listens on **both** 12060 and 6767 at the
  same time, so whichever logger sends the callsign first drives the same
  side-by-side locator lookup. 6767 feed **on by default** (one UAC prompt
  if VHFCtest4WIN already holds the port; `vhfctest_share=no` turns it
  off). `n1mm_VHFcallbook` / `VHFctest4WinCallbook` were still shipped
  alongside it in this release (removed in v2.18). No engine change.
- **2.16 (HF) / 1.20 (VHF) / 1.2 (VHFctest4WIN)** – **VHF: operator name +
  agreed-locator collapse**. The VHF windows (`n1mm_VHFcallbook` and
  `VHFctest4WinCallbook`) now print the **operator name** in front of the
  locators, and **when every source that answered agrees they collapse to
  a single locator in a larger green font** (`Hans - JN76HD`) instead of
  repeating it per source. A disagreement still shows every slot so the
  wrong grid stands out. Shared-engine change (new `DX_COUNTRY` /
  `COLLAPSE_ON_AGREE` class flags) – all three apps bump; HF display
  unchanged.
- **2.15 (HF) / 1.19 (VHF) / 1.1 (VHFctest4WIN)** – **start-up self-test**:
  on launch each configured source is queried once (callsign **S55OO** by
  default) and the window lists them line by line with `OK` / `no data` /
  `FAIL` and the round-trip time in ms, turning light green when every
  source answers `OK`. The result holds for a few seconds, then the
  window goes idle (a short `self-test: n/n sources OK` stays in the
  footer until the first real lookup). New `.cfg` keys `selftest` (default
  yes) and `selftest_call` (default `S55OO`). Shared-engine change – all
  three apps bump.
- **2.14 (HF) / 1.18 (VHF) / new: VHFctest4WinCallbook 1.0** – new
  **`VHFctest4WinCallbook`** app: the side-by-side locator check driven by
  **VHFCtest4WIN**. It listens to VHFCtest4WIN's multi-op sharing
  broadcast (UDP 6767), which carries the callsign **as it is typed**, so
  the locator lookup runs *before* the QSO is logged and a wrong QRA
  locator can be caught while it is still editable. When VHFCtest4WIN is
  already running it holds UDP 6767 exclusively, so the app **relaunches
  itself elevated** (one UAC prompt) and reads the broadcast with a raw
  capture socket; in a multi-op it follows only its own PC's VHFCtest4WIN.
  The same feed is also available in the plain VHF callbook via
  `vhfctest_share=yes`. HF unchanged (shared-engine plumbing only).
- **2.11 (HF) / 1.15 (VHF)** – the main text turns **light green when every
  source that answered agrees**. VHF locators are now separated by ` - `
  (`JN76HD - JN76HD - JN76HD`) instead of plain spaces, and a source that
  returned nothing shows `·` (was `-`, which read like a separator).
- **2.10 (HF) / 1.14 (VHF)** – cache resource use: the file is now written
  at most once a minute instead of on every lookup (a multi-thousand-QSO
  contest went from thousands of full-file rewrites to a few dozen), stores
  only the displayed fields, and prunes expired entries on load. New
  `cache_persist=no` option keeps it in memory only.
- **2.9 (HF) / 1.13 (VHF)** – latency: HTTPS connections to each source
  are pooled and kept alive, and responses are gzip-compressed – time to
  fill all three HF slots dropped from ~385 ms to ~155 ms (median) in
  testing. The window position is remembered between runs, and the QRZ
  XML session key is persisted so a restart skips the re-login.
- **2.8 (HF) / 1.12 (VHF)** – fixed a hang where retyping a callsign while
  a lookup was still running could stop all further lookups until restart.
  Internal: the two apps now share one `run()`/`load_config()` entry point
  (`n1mm_VHFcallbook.py` is a ~30-line subclass); the VHF title bar now
  shows its own version instead of the HF one.
- **2.7 (HF) / 1.11 (VHF)** – the **?** icon now opens the project page on
  GitHub instead of QRZCQ.com; released into the **public domain** (The
  Unlicense).
- **2.6 (HF) / 1.10 (VHF)** – the cache now carries a schema version, so
  entries written by an older build are always re-fetched once after an
  upgrade (the 2.5 fix missed calls that a 2.4 build had already cached).
  Locators are also upper-cased on read, so even a stale entry displays
  consistently.
- **2.5 (HF) / 1.9 (VHF)** – VHF: locators are upper-cased on the way in
  (some sources return the sub-square lower case, e.g. `JN46la` vs
  `JN46LA`), so a pure case difference no longer looks like a source
  disagreement.
- **2.4 (HF) / 1.8 (VHF)** – HF now also looks up the **CQ zone** from
  every source and shows it next to the state as a `state/zone` token
  (e.g. `MA/5`); DX stations show the CQ zone after the country. Cache
  entries from an earlier version (no CQ zone stored) are refreshed
  automatically on next use. VHF display unchanged (shared engine update
  only).
- **2.3 (HF) / 1.7 (VHF)** – all sources are now queried **in parallel**;
  each slot fills as soon as that source answers instead of waiting for
  the whole chain. HF: **non-US (DX) stations** now show the operator
  **name and country** instead of `no data`; a foreign subdivision
  returned by QRZ XML in the state field is ignored.
- **2.2 (HF) / 1.6 (VHF)** – per-source side-by-side display; QRZ.com XML
  added as an optional source.

---

## 8. License

This project is released into the **public domain** under
[The Unlicense](LICENSE) – do whatever you want with it, no attribution
required.

The standalone EXEs bundle the Python runtime and Tcl/Tk, which keep
their own permissive licenses (PSF and BSD-style); PyInstaller's
bootloader carries an explicit exception that allows shipping the frozen
app under any license. Nothing in the toolchain restricts this
dedication.
