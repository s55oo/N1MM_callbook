# N1MM Callbook – N1MM Logger+ Contest Callbook

> **Version:** 2.14 (HF) / 1.18 (VHF) / 1.0 (VHFCtest4WIN) · Made by **S55OO** with AI assistance.
> · **Public domain** – see [LICENSE](LICENSE).

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

A **VHF variant** (`n1mm_VHFcallbook.py` / `n1mm_VHFcallbook.exe`) is also
included. It uses the same engine but shows the worked station's
**QRA/maidenhead locator** (e.g. `JN76HD`) in the main area, from the
sources shown side by side – handy for VHF/UHF contests where the grid
square is the exchange. The **locator sources**:

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

### VHFCtest4WIN – `VHFctest4WinCallbook`

**VHFCtest4WIN** (S52AA's VHF contest logger) does not send N1MM
`LookupInfo` packets, so with the plain VHF callbook it only reacts once a
QSO is *logged*. **`VHFctest4WinCallbook`** is a dedicated variant that
instead listens to VHFCtest4WIN's **multi-op sharing broadcast** (UDP
**6767**), which carries the callsign **as it is typed** – so the locator
lookup runs *before* the QSO is logged and a wrong QRA locator can be
caught while it is still editable. Same three locator sources shown side
by side, same green "all agree" signal.

- Nothing to switch on in VHFCtest4WIN – it already broadcasts its entry
  field on 6767 as part of normal network sharing.
- **Port 6767 / UAC.** VHFCtest4WIN keeps 6767 open with an exclusive
  lock, so the only way to read the broadcast while it runs is a raw
  capture socket, which needs elevation. When VHFCtest4WIN is already up,
  `VHFctest4WinCallbook` **relaunches itself elevated** – you just get one
  **UAC prompt, click Yes**. Decline it and the window still opens and
  tells you what to do. No prompt when VHFCtest4WIN is not running yet.
- Do **not** start `VHFctest4WinCallbook` before VHFCtest4WIN on the same
  PC: it would take 6767 and VHFCtest4WIN's own network sharing then
  breaks. Start VHFCtest4WIN first, then `VHFctest4WinCallbook`.
- **Multi-op:** VHFCtest4WIN broadcasts to the whole network, so every
  PC sees every operator's typing. `VHFctest4WinCallbook` ignores
  everything except **its own PC's** VHFCtest4WIN, so each position's
  window follows only that operator (same local-computer-only rule as the
  N1MM feed).
- On another PC on the multi-op network, an ordinary listener works with
  no prompt.
- The same feed is also available as **`vhfctest_share=yes`** in
  `n1mm_VHFcallbook.cfg` if you would rather not run a second window
  (subject to the same elevation rule).

---

## 2. Running

HF callbook:

```
        double-click:  Callbook.bat       (from source, no console)
   or:  run:  pythonw n1mm_callbook.py    (from source, no window)
   or:  run:  n1mm_callbook.exe           (standalone executable)
```

VHF locator variant:

```
   or:  run:  pythonw n1mm_VHFcallbook.py (from source, no window)
   or:  run:  n1mm_VHFcallbook.exe        (standalone executable)
```

VHFCtest4WIN pre-log locator check (see section 1):

```
   or:  run:  pythonw VHFctest4WinCallbook.py  (from source, no window)
   or:  run:  VHFctest4WinCallbook.exe         (standalone; prompts for
                                                UAC when VHFCtest4WIN is
                                                already running)
```

Arguments:

```
python n1mm_callbook.py [--port 12060] [--config callbook.cfg]
python n1mm_VHFcallbook.py [--port 12060] [--config n1mm_VHFcallbook.cfg]
python VHFctest4WinCallbook.py [--config VHFctest4WinCallbook.cfg]
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
  side-by-side way, separated by ` - ` (`JN76HD - JN76HD - JN76HD`), and
  has no name/DX handling – it only needs the grid.
- **Local computer only:** the app only reacts to packets sent from *this*
  PC (identified by its local interface IPs). Broadcasts from other
  stations on the network are ignored, so only the local operator's
  callsign triggers a lookup.
- Lookups are cached (`callbook_cache.json` / `n1mm_VHFcallbook_cache.json`)
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

`callbook.cfg` (HF) / `n1mm_VHFcallbook.cfg` (VHF). Both are optional; the
apps run with defaults when no `.cfg` exists. Templates are in the repo:
`callbook.cfg.template` and `n1mm_VHFcallbook.cfg.template`.

```
[settings]
udp_port=12060
cache_days=30
cache_file=callbook_cache.json           (VHF: n1mm_VHFcallbook_cache.json)
cache_persist=yes                        (no = in-memory only, never writes)

# Optional - paid QRZ.com XML service (extra state / locator slot):
# qrz_username=S55OO
# qrz_password=YOUR_QRZ_PASSWORD

# VHF only - VHFCtest4WIN pre-log callsign feed (see section 1):
# vhfctest_share=no                      (yes = also listen on UDP 6767)
# vhfctest_port=6767
```

- Each `.cfg` and its matching `cache_file` are read/written from the same
  folder as the executable/script. The app also writes a small
  `*_window.json` (last window position) and `qrz_session.json` (QRZ XML
  session key) there – both are safe to delete and are gitignored.
- Both `.cfg` files are **gitignored** – they hold your QRZ login in
  **plain text**, so they are never committed and never land in a shared
  build. Only the `*.cfg.template` files (with placeholder credentials) are
  in the repo. Copy the matching template, fill in your QRZ credentials,
  and rename to `callbook.cfg` / `n1mm_VHFcallbook.cfg`.
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

REM VHF locator variant:
python -m PyInstaller --onefile --windowed --name n1mm_VHFcallbook --manifest manifest.xml n1mm_VHFcallbook.py
copy /Y dist\n1mm_VHFcallbook.exe n1mm_VHFcallbook.exe

REM VHFCtest4WIN pre-log locator check:
python -m PyInstaller --onefile --windowed --name VHFctest4WinCallbook --manifest manifest.xml VHFctest4WinCallbook.py
copy /Y dist\VHFctest4WinCallbook.exe VHFctest4WinCallbook.exe
```

`manifest.xml` makes the windows use modern common controls. The results are
single standalone EXEs (no Python required) – copy them to the other
computers together with the (optional) matching `.cfg`.

---

## 6. Files

```
n1mm_callbook.py     – main application, HF callbook (source code)
n1mm_callbook.exe    – HF standalone executable (built, no Python needed)
n1mm_VHFcallbook.py  – VHF locator variant (source code)
n1mm_VHFcallbook.exe – VHF standalone executable (built, no Python needed)
VHFctest4WinCallbook.py  – VHFCtest4WIN pre-log locator check (source code)
VHFctest4WinCallbook.exe – VHFCtest4WIN variant, standalone executable
callbook.cfg.template     – HF config template (copy to callbook.cfg)
callbook.cfg              – HF config (gitignored; may hold QRZ login in plain text)
callbook_cache.json       – HF local lookup cache (auto-created, gitignored)
n1mm_VHFcallbook.cfg.template – VHF config template
n1mm_VHFcallbook.cfg      – VHF config (gitignored; may hold QRZ login in plain text)
n1mm_VHFcallbook_cache.json – VHF local lookup cache (auto-created, gitignored)
VHFctest4WinCallbook.cfg.template – VHFCtest4WIN variant config template
VHFctest4WinCallbook.cfg  – VHFCtest4WIN variant config (gitignored)
VHFctest4WinCallbook_cache.json – VHFCtest4WIN variant lookup cache (auto, gitignored)
*_window.json        – last window position per app (auto, gitignored)
qrz_session.json     – cached QRZ XML session key (auto-created, gitignored)
Callbook.bat         – source launcher (no console)
manifest.xml         – PyInstaller manifest (common controls)
n1mm_callbook.spec, n1mm_VHFcallbook.spec, VHFctest4WinCallbook.spec – PyInstaller build settings
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
