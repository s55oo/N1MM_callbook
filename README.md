# N1MM Callbook – N1MM Logger+ Contest Callbook

> **Version:** 2.16 (HF – `n1mm_callbook`) / 1.1 (VHF – `VHFcallbook`)
> · Made by **S55OO** with AI assistance. · **Public domain** – see [LICENSE](LICENSE).

A compact always-on-top window that listens to the N1MM Logger+ external
UDP broadcast (XML, port **12060**) and automatically looks up the callsign
you are working. Every source is queried **in parallel** and **all** of its
values are shown side by side – each slot filling in the moment that
source answers, so nothing waits for the slowest one – and when the
sources disagree the wrong one stands out and you can pick the right one.
The window shows the worked station's **name**, then each source's
**US state and CQ zone** as one `state/zone` token, and the **callsign**
in the footer – e.g. `Fred - MA/5 MA/5 MA/5` (name printed once as the
shortest of the sources). For a **non-US (DX) station**, where there is no
US state, the HF window shows the **operator name and country** followed
by each source's **CQ zone**, e.g. `Hans (Germany) - 14 14 14`.

The HF callbook pulls its **state, CQ zone** and name from up to **three
sources**: **[QRZ.com XML](https://www.qrz.com/page/xml_data.html),
[QRZCQ.com](https://www.qrzcq.com) and
[HamQTH.com](https://www.hamqth.com)**. They are queried at the same time;
the slots are shown left-to-right in that order (QRZ XML left-most when
your QRZ login is configured). Without QRZ credentials it runs the two
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
lookup *as the callsign is typed*, pre-log – see [section 1](#vhfcallbook--the-vhfctest4win-feed).
The **locator sources**:

| Source | How the locator is read |
|---|---|
| QRZCQ.com | `Grid:` / `Locator:` row on `https://www.qrzcq.com/call/<CALL>` |
| HamQTH.com | `Grid:` row on `https://www.hamqth.com/<CALL>` |
| QRZ.com | computed from the station coordinates embedded in the public `https://www.qrz.com/db/<CALL>` page ("Grid square" in the Detail tab) |

All locator sources are queried **in parallel** and each slot fills as
soon as that source replies. With QRZ credentials configured the QRZ XML
service is added as the left-most slot; without credentials the VHF app
uses the three free locator sources.

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
> the `LookupInfo`/`ContactInfo` packet automatically. `RadioInfo` only
> carries the local operator's own call and is deliberately ignored.

### `VHFcallbook` & the VHFCtest4WIN feed

**VHFCtest4WIN** (S52AA's VHF contest logger) does not send N1MM
`LookupInfo` packets. Instead it broadcasts the callsign in its entry
field on its **multi-op sharing broadcast** (UDP **6767**) **as it is
typed**. `VHFcallbook` listens on 6767 **in addition to** the N1MM port
(12060), so with VHFCtest4WIN the locator lookup runs *before* the QSO is
logged and a wrong QRA locator can be caught while it is still editable.
The feed is **on by default**; set `vhfctest_share=no` in
`VHFcallbook.cfg` to turn it (and the UAC prompt below) off.

- Nothing to switch on in VHFCtest4WIN – it already broadcasts its entry
  field on 6767 as part of normal network sharing.
- **Port 6767 / UAC.** VHFCtest4WIN keeps 6767 open with an exclusive
  lock, so the only way to read the broadcast while it runs is a raw
  capture socket, which needs elevation. When VHFCtest4WIN is already up,
  `VHFcallbook` **relaunches itself elevated** – you just get one **UAC
  prompt, click Yes**. Decline it and the window still opens (N1MM feed
  only) and tells you what to do. No prompt when VHFCtest4WIN is not
  running yet, or when the 6767 feed is disabled.
- Start VHFCtest4WIN **first**, then `VHFcallbook` – starting it the other
  way round on the same PC would take 6767 and break VHFCtest4WIN's own
  network sharing.
- **Multi-op:** VHFCtest4WIN broadcasts to the whole network, so every
  PC sees every operator's typing. `VHFcallbook` ignores everything
  except **its own PC's** VHFCtest4WIN, so each position's window follows
  only that operator (same local-computer-only rule as the N1MM feed).
- On another PC on the multi-op network, an ordinary listener works with
  no prompt.

---

## 2. Running

HF callbook:

```
        double-click:  Callbook.bat       (from source, no console)
   or:  run:  pythonw n1mm_callbook.py    (from source, no window)
   or:  run:  n1mm_callbook.exe           (standalone executable)
```

VHF locator lookup – **listens on 12060 *and* 6767** (N1MM Logger+ and
VHFCtest4WIN, whichever you use):

```
   or:  run:  pythonw VHFcallbook.py       (from source, no window)
   or:  run:  VHFcallbook.exe              (standalone; prompts for UAC
                                            when VHFCtest4WIN is already
                                            running – see section 1)
```

Arguments:

```
python n1mm_callbook.py [--port 12060] [--config callbook.cfg]
python VHFcallbook.py   [--port 12060] [--config VHFcallbook.cfg]
```

- `--port` – UDP port (default 12060).
- `--config` – path to the matching `.cfg` file.

> Both apps can run at the same time (e.g. one on each radio or monitor).
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
  **QRZ.com XML, QRZCQ.com, HamQTH.com** (QRZ XML only when credentials are
  configured; the **VHF variant** adds **QRZ.com public page** as a fourth
  slot). The order is just the column layout, not a priority – every source
  is fetched at the same time. When the values differ (e.g.
  `MA/5 MA/4 MA/5`) you see it immediately and can decide which one is
  right for the exchange. **When every source that answered agrees, the
  text turns light green** – a quick "you can trust this" signal.
- For a **US station** the main area shows the **shortest operator name**
  (printed once) followed by one **`state/zone`** token per source, e.g.
  `FRED - MA/5 MA/5 MA/5`. A slot shows just the state when that source has
  no CQ zone (`MA`), just the zone for a DX-style entry, or `·` when it
  returned neither. The font shrinks automatically for long text.
- For a **non-US (DX) station** there is no US state, so the HF window
  shows the **operator name and country** followed by each source's **CQ
  zone**, e.g. `Hans (Germany) - 14 14 14` (or just `Hans (Germany)` when
  no source reports a zone). A foreign subdivision that QRZ XML sometimes
  returns in the state field (e.g. `HE` for a German call) is ignored; the
  CQ zone, which is meaningful worldwide, is kept.
- The **VHF variant** shows the **QRA/maidenhead locator** the same
  side-by-side way, separated by ` - `, with the **operator name** printed
  once in front (`Hans - JN76GB - JN76HD - JN76HD`). **When every source
  that answered agrees on the locator the row collapses to one value in a
  larger green font** (`Hans - JN76HD`); a disagreement keeps every slot
  visible so the wrong one stands out. It has no country/DX handling – for
  a VHF exchange only the grid and the name matter.
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
  QRZ XML OK       521 ms
  QRZCQ   OK       152 ms
  HamQTH  OK       236 ms
  ```

  `OK` = answered and parsed, `no data` = reachable but no record for the
  test call, `FAIL` = network/HTTP error (that source is down). The text
  turns light green when every source is `OK`. The result stays up for a
  few seconds, then the window goes to its normal idle state (the footer
  keeps a short `self-test: 3/3 sources OK` summary until the first
  lookup). The test callsign defaults to **S55OO** (listed on every
  source); set `selftest_call=` to another call if some of your sources
  don't list it, or `selftest=no` to skip the test entirely.
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

`callbook.cfg` (HF) / `VHFcallbook.cfg` (VHF). Both are optional; the apps
run with defaults when no `.cfg` exists. Each has a `*.cfg.template` in
the repo to copy.

```
[settings]
udp_port=12060
cache_days=30
cache_file=callbook_cache.json           (VHF: VHFcallbook_cache.json)
cache_persist=yes                        (no = in-memory only, never writes)

# Start-up self-test (query every source once on launch, show OK / time):
# selftest=yes
# selftest_call=S55OO                    (call to probe; blank/selftest=no disables)

# Optional - paid QRZ.com XML service (extra state / locator slot):
# qrz_username=S55OO
# qrz_password=YOUR_QRZ_PASSWORD

# VHF only - VHFCtest4WIN pre-log callsign feed, UDP 6767 (see section 1).
# On by default; set no to also stop the UAC prompt.
# vhfctest_share=no
# vhfctest_port=6767
```

- Each `.cfg` and its matching `cache_file` are read/written from the same
  folder as the executable/script. The app also writes a small
  `*_window.json` (last window position) and `qrz_session.json` (QRZ XML
  session key) there – both are safe to delete and are gitignored.
- The `.cfg` files are **gitignored** – they hold your QRZ login in
  **plain text**, so they are never committed and never land in a shared
  build. Only the `*.cfg.template` files (with placeholder credentials) are
  in the repo. Copy the matching template, fill in your QRZ credentials,
  and rename to `callbook.cfg` / `VHFcallbook.cfg`.
- The built `.exe` files do **not** embed the `.cfg`; they read it from
  disk at run time, so shipping an EXE never leaks your password.

---

## 5. Building the standalone EXEs (for PCs without Python)

Requires Python + PyInstaller:

```bat
python -m pip install pyinstaller

REM HF callbook:
python -m PyInstaller --onefile --windowed --name n1mm_callbook --manifest manifest.xml n1mm_callbook.py
copy /Y dist\n1mm_callbook.exe n1mm_callbook.exe

REM VHF locator lookup (N1MM 12060 + VHFCtest4WIN 6767):
python -m PyInstaller --onefile --windowed --name VHFcallbook --manifest manifest.xml VHFcallbook.py
copy /Y dist\VHFcallbook.exe VHFcallbook.exe
```

`manifest.xml` makes the windows use modern common controls. The results are
single standalone EXEs (no Python required) – copy them to the other
computers together with the (optional) matching `.cfg`.

---

## 6. Files

```
n1mm_callbook.py     – HF callbook application (source code)
n1mm_callbook.exe    – HF standalone executable (built, no Python needed)
VHFcallbook.py       – VHF locator app: N1MM (12060) + VHFCtest4WIN (6767); source
VHFcallbook.exe      – VHF standalone executable (built, no Python needed)
callbook.cfg.template     – HF config template (copy to callbook.cfg)
VHFcallbook.cfg.template  – VHF config template (copy to VHFcallbook.cfg)
callbook.cfg / VHFcallbook.cfg – live configs (gitignored; may hold QRZ login)
*_cache.json         – per-app local lookup cache (auto-created, gitignored)
*_window.json        – last window position per app (auto, gitignored)
qrz_session.json     – cached QRZ XML session key (auto-created, gitignored)
Callbook.bat         – source launcher (no console)
manifest.xml         – PyInstaller manifest (common controls)
*.spec               – PyInstaller build settings (one per app)
dist\                – PyInstaller output
CLAUDE.md            – developer notes (architecture, gotchas, release steps)
dev\test_render.py   – headless display-logic tests (no network)
dev\bench_latency.py – lookup-latency benchmark
```

> QRZ.com XML needs a **paid subscription** for full records. Even without
> it, QRZ returns the US state (and a plain name/address) for a login, so
> the HF app still gets its three state sources (QRZ XML, QRZCQ, HamQTH);
> the VHF app's locators are all free (QRZCQ, HamQTH, QRZ public page).

---

## 7. Changelog

> **VHF app history.** Through **v2.16** the VHF side was two apps –
> `n1mm_VHFcallbook` (N1MM feed) and `VHFctest4WinCallbook` (VHFCtest4WIN
> 6767 feed). **v2.17** added `VHFcallbook`, which does both at once.
> **v2.18** (`VHFcallbook` 1.1) **removed `n1mm_VHFcallbook` and
> `VHFctest4WinCallbook` entirely** – `VHFcallbook` is the only VHF app
> now. Older entries below that name the retired apps are historical; the
> feature they describe lives in `VHFcallbook` today.

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
