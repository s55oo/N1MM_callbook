# CLAUDE.md — developer notes for Callbooker

Context for anyone (human or AI) picking this repo up. Pair it with
`README.md`, the user-facing documentation.

## What it is

One always-on-top Tkinter window that listens to a logger's UDP broadcast
and looks up the callsign being worked. Every source is queried **in
parallel** and *all* of its values are shown side by side, so a
disagreement is obvious and the operator picks the right one. When they
agree the row collapses to one larger green token.

**Two files:**

- **`Callbooker.py`** — the app. `CallbookerApp(cb.CallbookApp)` plus the
  feed wiring and the UAC self-relaunch. It flips the HF/VHF view **per
  callsign** in `_apply_mode(vhf)`: plain attribute writes to
  `SLOT_FIELDS` / `SLOT_SEP` / `DX_COUNTRY` / `lookup_chain` +
  `source_labels`. The render path reads those fresh every repaint, so the
  next `_render_slots` is already in the new view — and the writes are
  safe from the packet-listener thread (same as the base `_handle_call`,
  which also touches Tk from there).
  - VHFCtest4WIN callsign → **VHF** always (`_poll_inbox` override forces
    it before draining `_v4w_inbox`).
  - N1MM callsign → `_apply_mode(mhz >= VHF_ABOVE_MHZ)` where `mhz` comes
    from `cb.packet_freq_mhz` on this packet or the last one seen
    (`RadioInfo` included — `on_packet` tracks `self._last_mhz`).
  - No frequency yet → the view saved in `Callbooker_window.json`
    (`{"mode": "hf"|"vhf"}`, read by `_load_mode`), HF on a first run.
  - `DX_COUNTRY` is `False` in both views — the CQ zone is the multiplier.
- **`n1mm_callbook.py`** — the engine (not run directly, despite the
  N1MM-ish name — the repo is `N1MM_callbook`). `CallbookApp` (window +
  lookup orchestration), `run()` (entry point), the source functions,
  `_HttpPool`, `Cache`. Its class-attribute defaults are the **HF view**.

Pure Python standard library — no third-party runtime dependencies.
PyInstaller is only needed to build the EXE. Public domain (Unlicense).

## Architecture (all in `n1mm_callbook.py` unless noted)

| Piece | Role |
|---|---|
| `packet_callsign()` | pull the worked call out of a `LookupInfo`/`ContactInfo`/`ContactReplace` XML packet (`RadioInfo`'s call is the local op's — ignored for the callsign). DXLog.net's "N1MM format" broadcast sends a byte-compatible `<lookupinfo>` on 12060 (on Space/Tab, pre-log, `<txfreq>` in tens of Hz) — parses with no change |
| `packet_v4w()` | pull the callsign out of a VHFCtest4WIN `<V4W><QSOINLOG>` sharing packet (UDP 6767); empty `<CALLSIGN>` → `None` |
| `packet_freq_mhz()` | operating frequency in MHz from `<rxfreq>`/`<txfreq>`/`<Freq>` (N1MM's *tens of Hz*, so ÷100000), any packet type; `None` if absent. Callbooker's HF/VHF switch |
| `v4w_listener_loop()` | the 6767 listener (Callbooker, on unless `vhfctest_share=no`). Tries a normal UDP bind; VHFCtest4WIN holds 6767 with `SO_EXCLUSIVEADDRUSE`, so if it is already running the bind fails and it falls back to `_v4w_raw_listen` — a Windows `SIO_RCVALL` raw socket that needs the app run as admin. Feeds callsigns to `_on_v4w_call` → `_v4w_inbox` → `_poll_inbox` (drained on the GUI thread) → `_handle_call` |
| `normalize_call()` / `normalize_grid()` | sanitise the call; upper-case locators so a case-only difference isn't seen as a disagreement |
| `_HttpPool` / `http_get()` | one kept-alive HTTPS connection per host, gzip, per-host lock, stale-connection retry, busy-host fallback to a one-shot connection. **All source fetches go through `http_get`.** |
| `Cache` | JSON cache keyed by call. `put()` only marks dirty; `flush()` (driven from `_poll_inbox`, forced in `on_close`) writes at most once per `FLUSH_INTERVAL`. Stores only `_CACHE_FIELDS`. Prunes expired / wrong-`CACHE_SCHEMA` entries on load. `persist=False` (`cache_persist=no`) = in-memory only. |
| `qrzcq_lookup` / `hamqth_lookup` / `qrz_lookup` | the sources. Each returns a dict with the same keys (`name qth grid class state cqzone country`) or `None`. **`qrz_lookup` is one source**: `_qrz_xml_lookup` (paid XML API, needs creds + a live subscription) when it can, else `_qrz_web_lookup` (grid from `cs_lat`/`cs_lon` on the public `/db/` page, no login) — never both. It sets module `_QRZ_TIER` (`"xml"`/`"web"`) and `_QRZ_SUBEXP`, read by the self-test. |
| `qrz_session_load()` / `_qrz_session_save()` | persist the QRZ XML session key to `qrz_session.json` so a restart skips the ~0.6 s re-login |
| `load_config()` / `run()` | entry point — parse args + the `key=value` .cfg, build `CallbookerApp`, run the Tk loop. `run(..., always_vhfctest=<bool>)` — Callbooker computes it from `vhfctest_share` (default yes) and forces the 6767 listener on when true |
| `CallbookApp` | the window + all lookup orchestration. Subclassed only by `CallbookerApp`. |

### Lookup flow

`on_packet` → debounce 300 ms → `_on_stable` → cache hit renders
immediately, else `_start_lookup` → `_do_lookup` spawns **one thread per
source** → each posts `(call, slot_index, result_or_None)` to `self._inbox`
→ `_poll_inbox` (GUI thread, every 100 ms) drains it, drops results whose
call != `self.current`, renders each slot as it lands, caches once every
slot is in.

### Start-up self-test

`run()` resolves `selftest` / `selftest_call` (default `S55OO`, empty =
off) and passes the call to `__init__`, which schedules `_start_precheck`
~150 ms after the window is up. One thread per source posts
`(slot_index, status, ms)` to `self._precheck_inbox` (`status` =
`"OK"` / `"no data"` / `"FAIL"`); the QRZ thread also stashes the module
`_QRZ_TIER` in `self._qrz_tier`. `_poll_inbox` drains it, `_render_precheck`
draws one monospaced line per source (the QRZ line shows `QRZ·xml` /
`QRZ·web`), and once every slot is in it schedules `_finish_precheck`
(`PRECHECK_HOLD_MS` later), whose footer summary adds the QRZ subscription
expiry. A real callsign supersedes it (`_handle_call` clears
`_precheck_active`; `_render_precheck` early-outs when `self.current` set).

### Render

`_render_slots` builds the display string. `_source_value` joins the
`SLOT_FIELDS` into one `a/b` token per slot; the `state` field is dropped
when the source's country is non-US (`_US_NAMES`), `cqzone` kept.
`_best_name` picks the shortest non-placeholder name, then **its first
word only** (`_source_field(..., "name")` → `min(..., key=len).split()[0]`).
`_is_dx` + `DX_COUNTRY` would add `name (country)` — but Callbooker keeps
`DX_COUNTRY` False, so the name stays bare. Slots joined by `SLOT_SEP`;
empty slot `·` (`SLOT_EMPTY`), pending `…` (`SLOT_PENDING`). `all_done` +
every real value equal (≥2) → light-green fill (`agree`); + `COLLAPSE_ON_AGREE`
(True on the base) → the value shown once instead of joined. `_font_for`
walks `FONT_LADDER` (26 … 12) and returns the first size whose
`tkfont.Font.measure(text)` fits the canvas width (live width once mapped,
`winfo_reqwidth` before) — `Font`s cached in `self._font_cache`; canvas is
`width=360` to give `FONT_SIZE_BIG` room.

### Class attributes (`CallbookApp` default = HF view; `CallbookerApp` changes them)

```
VERSION       # title bar — CallbookerApp sets it from its own __version__
APP_TITLE
SLOT_FIELDS   # HF ("state","cqzone");  VHF ("grid",)   — _apply_mode swaps at runtime
SLOT_SEP      # HF " " (name has " - " after it);  VHF " - "
SHOW_NAME     # True — first name only, printed once in front
DX_COUNTRY    # base True; CallbookerApp False (both views)
COLLAPSE_ON_AGREE  # True on the base — a unanimous result collapses to one big green token
LOOKUP_CHAIN  # the free sources (qrzcq, hamqth); a QRZ slot is prepended by __init__ / _apply_mode
QRZ_WEB_FALLBACK  # base False (QRZ slot only with creds); CallbookerApp _apply_mode adds a web-only QRZ in the VHF view
VHFCTEST_CAPABLE  # True on CallbookerApp — lets run() wire the 6767 listener
```

`CallbookerApp` writes `SLOT_FIELDS` / `SLOT_SEP` / `DX_COUNTRY` /
`lookup_chain` / `source_labels` as **instance** attributes in
`_apply_mode` — Python resolves instance-first, so the render code is
unchanged.

## Gotchas (don't reintroduce these bugs)

- **No `_fetching` guard.** An earlier version skipped a new lookup while
  one was "in flight"; retyping a call mid-lookup then wedged all future
  lookups. `_start_lookup` always starts fresh; stale results are dropped
  by the `call != self.current` check.
- **`self.VERSION`, not module `__version__`.** `_build` reads
  `self.VERSION`; `CallbookerApp` sets it from its own `__version__`.
- **Bump `CACHE_SCHEMA`** only when an old entry would now display *wrong*
  (a field's meaning or normalisation changed) — not merely differently.
- **`normalize_grid` is applied twice**: in each lookup (so the cache is
  clean) and in `_source_field` on read (so a stale entry still displays
  consistently).
- Source pages are scraped with regex — markup drift fails silently
  (fields go empty → `·`). `dev/bench_latency.py` doubles as a quick
  "are the sources still parsing?" check before a contest.
- Callbooker touches Tk from the packet-listener thread (`on_packet` →
  `_handle_call` / `_apply_mode`). This is pre-existing and low-contention
  (packets arrive at typing speed); `_apply_mode` only does plain
  attribute writes there, no Tk calls.

## Files the app writes (all gitignored, all safe to delete)

`Callbooker_cache.json`, `Callbooker_window.json` (last position **and**
`{"mode": ...}`), `qrz_session.json`. Next to the `.cfg` / exe.

**Never commit `Callbooker.cfg`** (nor the older `callbook.cfg` /
`VHFcallbook.cfg` / …, still gitignored) — it holds the QRZ login in
plain text. Only `Callbooker.cfg.template` (placeholder) is tracked.

## Build

```bat
python -m PyInstaller --onefile --windowed --name Callbooker --manifest manifest.xml --noconfirm Callbooker.py
copy /Y dist\Callbooker.exe .
```

`--noconfirm` also rewrites `Callbooker.spec` (unchanged content — leave
it).

## Release ritual

A **user-facing change** gets a version bump + a release; a
docs / `dev/` / comment change is committed and pushed only.

1. Bump `__version__` in `Callbooker.py`, and `__version__` + `USER_AGENT`
   in `n1mm_callbook.py` (keep them the same number).
2. README: version banner + a new entry at the top of `## 7. Changelog`.
3. Rebuild `Callbooker.exe`, copy to repo root.
4. `git grep` for your QRZ username / password → confirm nothing real
   reached a tracked file.
5. Commit straight to `main` (no branch).
6. Push.
7. Release: `gh` authenticated via `GH_TOKEN` env only (never
   `gh auth login`), tag `main`, then
   `gh release create v<X.Y> --verify-tag --latest` attaching
   `Callbooker.exe`, `Callbooker.cfg.template` and `LICENSE`.

## dev/

- `dev/test_render.py` — headless render-logic tests (fake canvas + a
  withdrawn Tk root for font metrics, no network). `make(cls)` builds a
  bare instance; `vh` is a `CallbookerApp` switched to the VHF view.
- `dev/bench_latency.py` — per-source and end-to-end lookup latency
  (reads QRZ creds from `Callbooker.cfg` if present).
- `dev/logger-feeds.md` — every logger feed (N1MM, DXLog.net,
  VHFCtest4WIN) and the step-by-step method for adding another; the
  WriteLog to-do lives here.
- `dev/vhfctest4win-*.md`, `dev/sniff_multi.py`, `dev/test_rcvall2.py`,
  `dev/probe_window.py`, `dev/vhfctest4win-captures/` — the VHFCtest4WIN
  6767 reverse-engineering (protocol notes, sniff tools, packet captures).

Run: `python dev/test_render.py` / `python dev/bench_latency.py`.
