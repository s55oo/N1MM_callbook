# CLAUDE.md — developer notes for N1MM_callbook

Context for anyone (human or AI) picking this repo up. Pair it with
`README.md`, which is the user-facing documentation.

## What it is

Two always-on-top Tkinter windows that listen to the **N1MM Logger+**
external UDP broadcast (XML, port 12060) and look up the callsign being
worked. Every configured source is queried **in parallel** and *all* of
its values are shown side by side, so when sources disagree the wrong one
is obvious and the operator picks the right value for the exchange.

- **HF** (`n1mm_callbook.py`, v2.x): shows `name - state/zone state/zone …`;
  for DX (non-US) stations `name (country) - zone zone …`.
- **VHF** (`n1mm_VHFcallbook.py`, v1.x): shows the maidenhead locator per
  source. It is a ~30-line subclass of the HF app's `CallbookApp`.

Pure Python standard library — no third-party runtime dependencies.
PyInstaller is only needed to build the EXEs. Public domain (Unlicense).

## Architecture (all in `n1mm_callbook.py` unless noted)

| Piece | Role |
|---|---|
| `packet_callsign()` | pull the worked call out of a `LookupInfo`/`ContactInfo`/`ContactReplace` XML packet (`RadioInfo` is ignored — it carries the local op's own call) |
| `normalize_call()` / `normalize_grid()` | sanitise the call; upper-case locators so a case-only difference isn't seen as a disagreement |
| `_HttpPool` / `http_get()` | one kept-alive HTTPS connection per host, gzip, per-host lock, stale-connection retry, busy-host fallback to a one-shot connection. **All source fetches go through `http_get`.** |
| `parse_cty` / `cty_lookup` / `cty_load` / `cty_autoupdate` | offline DXCC/CQ-zone source from cty.dat. `parse_cty` -> (exact `{=CALL}`, prefixes) records. `cty_lookup` = compound-call split (`_cty_basecall`) -> exact/longest-prefix -> `_cty_refine` (US/VE call-area zone + VE province, since cty.dat only carves out the rare zones). `cty_load` tries [config `cty_file`, `<data>/cty.dat`, bundled]. `cty_autoupdate` background-downloads a fresh one when `<data>/cty.dat` is missing or >30 days old. HF-only (`USE_CTY`). |
| `Cache` | JSON cache keyed by call. `put()` only marks dirty; `flush()` (driven from `_poll_inbox`, forced in `on_close`) writes at most once per `FLUSH_INTERVAL`. Stores only `_CACHE_FIELDS`. Prunes expired / wrong-`CACHE_SCHEMA` entries on load. `persist=False` (`cache_persist=no`) = in-memory only. |
| `qrzcq_lookup` / `hamqth_lookup` / `qrz_lookup` / `qrzdb_lookup` | the sources. Each returns a dict with the same keys (`name qth grid class state cqzone country`) or `None` on any failure. `Cache` stores only `_CACHE_FIELDS` (the 5 the display reads). `qrz_lookup` needs paid QRZ XML creds; `qrzdb_lookup` (VHF-only) computes the grid from `cs_lat`/`cs_lon` on the public QRZ page. |
| `qrz_session_load()` / `_qrz_session_save()` | persist the QRZ XML session key to `qrz_session.json` so a restart skips the ~0.6 s re-login |
| `load_config()` / `run()` | shared entry point — parse args + the `key=value` .cfg, build the app, run the Tk loop. Both `main()` functions are one call to `run()`. |
| `CallbookApp` | the window + all lookup orchestration. Subclassed by `VHFApp`. |

### CallbookApp lookup flow

`on_packet` → debounce 300 ms → `_on_stable` → cache hit renders immediately,
else `_start_lookup` → `_do_lookup` spawns **one thread per source** →
each posts `(call, slot_index, result_or_None)` to `self._inbox` →
`_poll_inbox` (GUI thread, every 100 ms) drains the queue, drops results
whose call != `self.current`, renders each slot as it lands, and caches
once every slot is in.

`_render_slots` builds the display string. `_source_value` joins the
`SLOT_FIELDS` into one `a/b` token per slot; the `state` field is dropped
unless the country is US/Canada (`_keeps_state` / `_STATE_COUNTRIES`).
`_is_dx` (US/Canada -> False) decides the `name (country)` vs plain-name
prefix. Slots are joined by `SLOT_SEP`; empty slot `SLOT_EMPTY` (`·`),
pending `SLOT_PENDING` (`…`).

`_agree` decides the green text: **per field**, not per whole token. For
each `SLOT_FIELD`, every source that reported a value must agree, and >=1
field must have >=2 sources confirming. So cty.dat's bare `5` lines up
with the web sources' `MA/5` (state and zone each agree); but if cty.dat's
zone contradicts the web sources the field disagrees -> white. A source
that just didn't report a field is not a disagreement. Green also needs
`all_done`.

### Class attributes a variant overrides

```
VERSION       # title-bar version — set per subclass, NOT the module __version__
APP_TITLE
SLOT_FIELDS   # HF ("state","cqzone");  VHF ("grid",)
SLOT_SEP      # HF " " (name already has " - " after it);  VHF " - "
SHOW_NAME     # HF True; VHF False
USE_CTY       # HF True (cty_lookup prepended as slot 0); VHF False
LOOKUP_CHAIN  # the free sources; cty_lookup then qrz_lookup are prepended by __init__
```

## Gotchas / history (don't reintroduce these bugs)

- **No `_fetching` guard.** An earlier version skipped a new lookup while
  one was "in flight"; retyping a call mid-lookup then wedged all future
  lookups. `_start_lookup` now always starts fresh; stale results are
  dropped by the `call != self.current` check.
- **`CallbookApp.VERSION`, not module `__version__`.** `_build` reads
  `self.VERSION`. The VHF title bar used to show the HF version because it
  referenced the base module's global.
- **Bump `CACHE_SCHEMA`** only when an old entry would now display *wrong*
  (a field's meaning changed, or the number of slots changed) — not merely
  differently. v1→v2 added `cqzone` + upper-cased locators; v3 prepended
  the cty.dat slot (old entries have one fewer). v2.10 only trimmed stored
  fields and old wider entries still read fine, so it did *not* bump.
- **cty.dat only carves out the rare CQ zones** (USA: the ~5000 `=CALL`
  list; Canada: zones 1 & 2). `_cty_refine` derives the rest from the call
  area — the `_US_AREA_ZONE` / `_VE_AREA` tables. W4 is genuinely split
  (AL/KY/TN=4, the rest=5) so it defaults to 5; the online sources are the
  cross-check. Do not "fix" a US zone that looks wrong by editing cty.dat.
- **`normalize_grid` is applied twice**: in each lookup (so the cache is
  clean) and in `_source_field` on read (so a stale cache entry still
  displays consistently).
- Source pages are scraped with regex — markup drift fails silently
  (fields just go empty → `·`). `dev/bench_latency.py` doubles as a quick
  "are the sources still parsing?" check before a contest.

## Files the app writes (all safe to delete)

`*_cache.json` (lookup cache), `*_window.json` (last window position —
position only, not size), `qrz_session.json` (QRZ XML session key),
`cty.dat` (auto-refreshed prefix DB). They live next to the `.cfg`/exe.
All gitignored **except** `cty.dat`, which is tracked as the bundled
fallback (PyInstaller ships it via `--add-data "cty.dat;."`, extracted to
`sys._MEIPASS`; `_resource_path()` finds it). Running from source, the
auto-download target *is* the tracked file — the 30-day age check keeps
that rare; if a refresh lands, just commit it.

**Never commit `callbook.cfg` / `n1mm_VHFcallbook.cfg`** — they hold the
QRZ login in plain text. Only `*.cfg.template` (placeholders) is tracked.

## Build

```bat
python -m PyInstaller --onefile --windowed --name n1mm_callbook --manifest manifest.xml --add-data "cty.dat;." --noconfirm n1mm_callbook.py
python -m PyInstaller --onefile --windowed --name n1mm_VHFcallbook --manifest manifest.xml --noconfirm n1mm_VHFcallbook.py
copy /Y dist\n1mm_callbook.exe .
copy /Y dist\n1mm_VHFcallbook.exe .
```

## Release ritual

A **user-facing change** (a feature or a bug fix) gets the full ritual and
a release. A **docs / `dev/` / comment change** is committed and pushed
only — no version bump, no release.

Full ritual:

1. Bump `__version__` in **both** files + the `USER_AGENT` in `n1mm_callbook.py`.
   HF and VHF carry independent numbers (HF ~2.x, VHF ~1.x).
2. README: version banner near the top + a new entry at the top of
   `## 7. Changelog`.
3. Rebuild both EXEs, copy to repo root (`--noconfirm` also rewrites the
   `.spec` files — leave those, they're unchanged content).
4. `git grep` for your QRZ username / password → confirm no real
   credential reached a tracked file.
5. Commit straight to `main` (no branch), terse semicolon-joined message.
6. Push.
7. Release: `gh` authenticated via `GH_TOKEN` env only (never
   `gh auth login`), tag `main`, then
   `gh release create vX.Y --verify-tag --latest` attaching the two EXEs,
   the two `*.cfg.template` files and `LICENSE`.

## dev/

- `dev/test_render.py` — headless render-logic tests (fake canvas, no network).
- `dev/bench_latency.py` — measures per-source and end-to-end lookup
  latency (reads QRZ creds from `callbook.cfg` if present).

Run: `python dev/test_render.py` / `python dev/bench_latency.py`.
