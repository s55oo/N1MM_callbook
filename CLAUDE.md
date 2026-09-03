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

The lookup, cache, LAN-sharing and UI code is pure Python standard
library. The **optional** MQTT output (`mqtt_client.py`, off unless
`mqtt_enabled=yes`) needs `paho-mqtt` — listed in `requirements.txt`,
bundled into `Callbooker.exe`, imported lazily so the app still runs
without it. PyInstaller is only needed to build the EXE. Public domain
(Unlicense).

## Architecture (all in `n1mm_callbook.py` unless noted)

| Piece | Role |
|---|---|
| `packet_callsign()` | pull the worked call out of a `LookupInfo`/`ContactInfo`/`ContactReplace` XML packet (`RadioInfo`'s call is the local op's — ignored for the callsign). DXLog.net's "N1MM format" broadcast sends a byte-compatible `<lookupinfo>` on 12060 (on Space/Tab, pre-log, `<txfreq>` in tens of Hz) — parses with no change |
| `packet_v4w()` | pull the callsign out of a VHFCtest4WIN `<V4W><QSOINLOG>` sharing packet (UDP 6767); empty `<CALLSIGN>` → `None` |
| `packet_freq_mhz()` | operating frequency in MHz from `<rxfreq>`/`<txfreq>`/`<Freq>` (N1MM's *tens of Hz*, so ÷100000), any packet type; `None` if absent. Callbooker's HF/VHF switch |
| `LANShare` | LAN cache sharing on a dedicated UDP port (default 6768, `lan_share=no` to disable). One JSON packet type with a `cbshare` marker: entry / call-request / sync-request. On a local cache miss `_on_stable` broadcasts a call-request and waits `LAN_GRACE_MS` (50 ms) before the HTTP lookup; a peer's entry cancels it. Only `_CACHE_FIELDS` on the wire — never a QRZ login. `_send` targets `255.255.255.255` **and** each interface's `<net>.255` (`_broadcast_targets`, plus `lan_share_bcast` extras) so a multi-homed PC doesn't only broadcast out a VirtualBox/VPN adapter. `dev/lan-cache-sharing.md` |
| `Cache.merge()` / `put()`→ts / `get_with_ts()` / `items_since()` | the cache hooks `LANShare` uses — newer-wins merge of a received entry, the `ts` to gossip, and the newest-first replay list for a sync |
| `v4w_listener_loop()` | the 6767 listener (Callbooker, on unless `vhfctest_share=no`). Tries a normal UDP bind; VHFCtest4WIN holds 6767 with `SO_EXCLUSIVEADDRUSE`, so if it is already running the bind fails and it falls back to `_v4w_raw_listen` — a Windows `SIO_RCVALL` raw socket that needs the app run as admin. Feeds callsigns to `_on_v4w_call` → `_v4w_inbox` → `_poll_inbox` (drained on the GUI thread) → `_handle_call` |
| `normalize_call()` / `normalize_grid()` | sanitise the call; upper-case locators so a case-only difference isn't seen as a disagreement |
| `_HttpPool` / `http_get()` | one kept-alive HTTPS connection per host, gzip, per-host lock, stale-connection retry, busy-host fallback to a one-shot connection. **All source fetches go through `http_get`.** |
| `Cache` | JSON cache keyed by the **bare call** (so LAN peers share entries regardless of view). `put()` only marks dirty; `flush()` (driven from `_poll_inbox`, forced in `on_close`) writes at most once per `FLUSH_INTERVAL`. Stores only `_CACHE_FIELDS`. Freshness window = `cache_days`, **default and hard max `MAX_CACHE_DAYS` (3)** — `run()` clamps a higher `cache_days` down; `get()` / `_load()` / `items_since()` drop older entries. Prunes expired / wrong-`CACHE_SCHEMA` entries on load. `persist=False` (`cache_persist=no`) = in-memory only. `_cached_sources(call)` on the app rejects an entry whose source count ≠ the active lookup chain (HF↔VHF changes whether QRZ has a slot) so it isn't mislabelled. |
| `mqtt_client.MqttPublisher` / `lookup_payload()` | **optional** MQTT output (`mqtt_client.py`, needs `paho-mqtt`). Long-lived reconnecting Paho client with its own network thread, bounded offline queue, optional auth/TLS. `_publish_lookup_result` builds a schema-v1 JSON doc (Tk-free `lookup_payload`) after every completed lookup — a cache hit in `_on_stable`, a LAN-answered hit in `_drain_lan_inbox`, the final live source in `_poll_inbox` — and hands it to `MqttPublisher.publish` (returns fast; never blocks the UI). Off unless `mqtt_enabled=yes`. Errors surface in the footer. |
| `updater` (`updater.py`, stdlib) | GitHub-release update check, **on** unless `update_check=no`. `_run_update_check` thread → `updater.check(VERSION, state_dir)` (once/day, cached in `update_check.json`) → `_update_inbox` → `_poll_inbox` sets `self._update` and refreshes the title suffix. `_open_help` on the `?` icon runs `_act_on_update` when `self._update` is set: frozen → `updater.download` the release's `Callbooker.exe` to `<exe>.new` (a worker thread flips `_update_state`); source / no asset / failure → open the releases page. `updater.apply_pending()` runs first thing in `Callbooker.main()`: if `<exe>.new` exists it renames the running exe aside, moves the new one in and relaunches (a running `.exe` can be renamed, not overwritten). |
| `qrzcq_lookup` / `hamqth_lookup` / `qrz_lookup` | the sources. Each returns a dict with the same keys (`name qth grid class state cqzone country`) or `None`. **`qrz_lookup` is one source**: `_qrz_xml_lookup` (paid XML API, needs creds + a live subscription) when it can, else `_qrz_web_lookup` (grid from `cs_lat`/`cs_lon` on the public `/db/` page, no login) — never both. It sets module `_QRZ_TIER` (`"xml"`/`"web"`) and `_QRZ_SUBEXP`, read by the self-test. |
| `qrz_session_load()` / `_qrz_session_save()` | persist the QRZ XML session key to `qrz_session.json` so a restart skips the ~0.6 s re-login |
| `load_config()` / `run()` | entry point — parse args + the `key=value` .cfg, build `CallbookerApp`, run the Tk loop. `run(..., always_vhfctest=<bool>)` — Callbooker computes it from `vhfctest_share` (default yes) and forces the 6767 listener on when true |
| `CallbookApp` | the window + all lookup orchestration. Subclassed only by `CallbookerApp`. |

### Lookup flow

`on_packet` → `_handle_call` bumps `_lookup_generation` and snapshots
`_capture_lookup_context()` (mode / feed / frequency / source labels) →
debounce 300 ms → `_on_stable(call, generation, context)` → **local cache
hit** renders + publishes (`cached=True`). Else, with LAN sharing on:
broadcast a call-request, arm `_await_lan`, schedule `_lan_grace_expired`
50 ms out — a peer's entry merges into the cache, renders and publishes
(lookup skipped); no peer → `_start_lookup(call, generation, context)`.
`_start_lookup` → `_do_lookup` spawns **one thread per source** → each
posts `(call, generation, slot_index, result_or_None)` to `self._inbox` →
`_poll_inbox` (GUI thread, every 100 ms) drains it (and `_lan_inbox`),
drops results whose call ≠ `self.current` **or generation ≠ the active
lookup** (a slow stale thread can't repaint or publish a newer callsign),
renders each slot as it lands, and once every slot is in: caches +
`lan.broadcast_entry` (full success only) and `_publish_lookup_result`
(`cached=False`, any completion).

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

### Footer info line (`call_label`)

Shows the worked call, plus ` · <source>` once the lookup resolves:
`local` (cache hit — `_show_call` / `_on_stable`), `LAN` (a peer answered —
`_drain_lan_inbox`), `online` (fresh fetch — `_poll_inbox` on the tick
that fills the last slot). `_set_resolved_from(src)` records it in
`self._resolved_from` (reset per call in `_show_call`) and repaints via
`_footer_text()`, **unless** `_mqtt_error_seen` is set — an MQTT error
owns the footer while it lasts, then `_poll_inbox` restores `_footer_text()`
on clear. The start-up self-test summary and the VHFCtest4WIN status hint
also transiently use this label.

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

- **Never call `_build()` twice** — it packs a fresh set of widgets each
  time (a 1.5 bug did this to update the title, and stacked frames).
  Runtime title changes go through `_refresh_title()` (→ `_title()` +
  `_update_suffix()`), never `_build()`. `_title()` is the per-class
  override point.
- **`Callbooker.exe` is a windowed (no-console) build** — `console=False`
  in `Callbooker.spec`. `pyinstaller Callbooker.py` *without* flags builds
  a console exe; always build from the spec (or pass `--windowed`). Any
  `subprocess` call from the frozen app passes `DEVNULL` std handles +
  `CREATE_NO_WINDOW` (see `updater.apply_pending`) so nothing flashes.
- **No `_fetching` guard.** An earlier version skipped a new lookup while
  one was "in flight"; retyping a call mid-lookup then wedged all future
  lookups. `_start_lookup` always starts fresh; stale results are dropped
  by the `call != self.current` **and generation** checks.
- **`_lookup_generation` threads through everything.** `_handle_call`
  bumps it and every downstream call (`_on_stable`, `_lan_grace_expired`,
  `_start_lookup`, `_do_lookup`, the `_inbox` tuple) carries it. A result
  whose generation ≠ the current one is dropped — this is what stops a
  slow stale source from repainting *or MQTT-publishing* against a newer
  callsign. If you add a new path into the lookup, carry the generation.
- **MQTT must never block.** `_publish_lookup_result` is wrapped in a bare
  `except`, and `MqttPublisher.publish` returns immediately (Paho owns the
  network thread; offline results go to a bounded queue). Don't add a
  synchronous broker call on the GUI thread.
- **Cache key is the bare call** — LAN sharing depends on it. The HF↔VHF
  slot-count mismatch is handled by `_cached_sources` rejecting a
  wrong-length entry, *not* by a composite key.
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
python -m pip install -r requirements.txt
python -m PyInstaller --onefile --windowed --name Callbooker --manifest manifest.xml --hidden-import paho.mqtt.client --noconfirm Callbooker.py
copy /Y dist\Callbooker.exe .
```

`--hidden-import paho.mqtt.client` bundles the MQTT dependency (its import
in `mqtt_client.py` is lazy, so PyInstaller needs the hint). `--noconfirm`
rewrites `Callbooker.spec`, which now carries the manifest and that hidden
import — so `python -m PyInstaller Callbooker.spec` reproduces the build.

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
- `dev/test_lan_share.py` — headless LAN cache-sharing tests (no sockets):
  `Cache` helpers, `LANShare._handle` packet dispatch, and the LAN-first
  lookup order via a fake Tk root / canvas.
- `dev/test_mqtt.py` — MQTT config parsing, schema-v1 `lookup_payload`,
  and the publish integration points (fake Paho client + fake cache, no
  broker). Has a Tk-less engine-import shim for CI.
- `dev/test_updater.py` — `updater.py`: version compare, the daily-check
  throttle, `download()` (fake `urlopen`), and the exe-swap file dance.
- `dev/lan_wire.py` — real-UDP two-socket LAN-sharing smoke test (one PC).
- `dev/lan_probe.py` — real-UDP **two-PC** diagnostic: `listen` on one,
  `send` on the other; isolates firewall/network from Callbooker.
- `dev/bench_latency.py` — per-source and end-to-end lookup latency
  (reads QRZ creds from `Callbooker.cfg` if present).
- `dev/logger-feeds.md` — every logger feed (N1MM, DXLog.net,
  VHFCtest4WIN) and the step-by-step method for adding another; the
  WriteLog to-do lives here.
- `dev/lan-cache-sharing.md` — LAN cache sharing (`LANShare`, shipped in
  1.2): dedicated port 6768 (why not 12060), one entry packet + two
  request lines, ask-the-LAN-before-the-callbook-sites lookup order,
  live broadcast + startup "replay as gossip" catch-up, storm guards,
  firewall behaviour, and an "as built" code map.
- `dev/mqtt-integration.md` — MQTT output (`mqtt_client.py`, shipped in
  1.3, off by default): the optional/bundled paho dependency, the
  non-blocking `MqttPublisher`, schema-v1 `lookup_payload`, the three
  publish points, the per-lookup generation/context, and how the PR #2
  composite cache key was reconciled with LAN sharing's bare-call key.
- `dev/lan-mqtt-session.md` — history/pointers for the 1.2–1.6 work
  (LAN sharing, MQTT, the multi-homed broadcast bug, PR #2 reconciliation)
  and the standing decisions from the user.
- `dev/vhfctest4win-*.md`, `dev/sniff_multi.py`, `dev/test_rcvall2.py`,
  `dev/probe_window.py`, `dev/vhfctest4win-captures/` — the VHFCtest4WIN
  6767 reverse-engineering (protocol notes, sniff tools, packet captures).

Run: `python dev/test_render.py` / `python dev/test_lan_share.py` /
`python dev/test_mqtt.py` / `python dev/test_updater.py` /
`python dev/bench_latency.py`.
