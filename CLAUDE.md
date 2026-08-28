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
| `Cache` | tiny JSON cache keyed by call. Carries `CACHE_SCHEMA`; `get()` drops entries whose `v` != current schema so an upgrade re-fetches once. Only complete, error-free result sets are cached. |
| `qrzcq_lookup` / `hamqth_lookup` / `qrz_lookup` / `qrzdb_lookup` | the sources. Each returns a dict with the same keys (`name qth grid class state cqzone country`) or `None` on any failure. `qrz_lookup` needs paid QRZ XML creds; `qrzdb_lookup` (VHF-only) computes the grid from `cs_lat`/`cs_lon` on the public QRZ page. |
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
when the source's country is non-US (`_US_NAMES`), but `cqzone` is kept.
`_is_dx` decides the `name (country)` vs `name` prefix.

### Class attributes a variant overrides

```
VERSION       # title-bar version — set per subclass, NOT the module __version__
APP_TITLE
SLOT_FIELDS   # HF ("state","cqzone");  VHF ("grid",)
SHOW_NAME     # HF True; VHF False
LOOKUP_CHAIN  # the free sources; qrz_lookup is prepended by __init__ when creds exist
```

## Gotchas / history (don't reintroduce these bugs)

- **No `_fetching` guard.** An earlier version skipped a new lookup while
  one was "in flight"; retyping a call mid-lookup then wedged all future
  lookups. `_start_lookup` now always starts fresh; stale results are
  dropped by the `call != self.current` check.
- **`CallbookApp.VERSION`, not module `__version__`.** `_build` reads
  `self.VERSION`. The VHF title bar used to show the HF version because it
  referenced the base module's global.
- **Bump `CACHE_SCHEMA`** whenever the per-source result dict changes shape
  (new field, different normalisation). Otherwise old cached entries are
  served forever. (v1→v2 added `cqzone` + upper-cased locators.)
- **`normalize_grid` is applied twice**: in each lookup (so the cache is
  clean) and in `_source_field` on read (so a stale cache entry still
  displays consistently).
- Source pages are scraped with regex — markup drift fails silently
  (fields go empty → `-`). `dev/bench_latency.py` and a `--selftest` idea
  in the README notes are the mitigations.

## Files the app writes (all gitignored, all safe to delete)

`*_cache.json` (lookup cache), `*_window.json` (last window position,
restored on start — position only, not size), `qrz_session.json` (QRZ XML
session key). They live next to the `.cfg`/exe.

**Never commit `callbook.cfg` / `n1mm_VHFcallbook.cfg`** — they hold the
QRZ login in plain text. Only `*.cfg.template` (placeholders) is tracked.

## Build

```bat
python -m PyInstaller --onefile --windowed --name n1mm_callbook --manifest manifest.xml --noconfirm n1mm_callbook.py
python -m PyInstaller --onefile --windowed --name n1mm_VHFcallbook --manifest manifest.xml --noconfirm n1mm_VHFcallbook.py
copy /Y dist\n1mm_callbook.exe .
copy /Y dist\n1mm_VHFcallbook.exe .
```

## Release ritual (every functional change)

1. Bump `__version__` in **both** files + the `USER_AGENT` in `n1mm_callbook.py`.
2. README: version banner + a new `## 7. Changelog` entry.
3. Rebuild both EXEs, copy to repo root.
4. `git grep` for your QRZ username / password → confirm no real
   credential reached a tracked file.
5. Commit straight to `main` (no branch), terse message.
6. Push.
7. To cut a release: `gh` authenticated via `GH_TOKEN` env only, then
   `gh release create vX.Y --verify-tag --latest` with the two EXEs, the
   two `*.cfg.template` files and `LICENSE` attached.

## dev/

- `dev/test_render.py` — headless render-logic tests (fake canvas, no network).
- `dev/bench_latency.py` — measures per-source and end-to-end lookup
  latency (reads QRZ creds from `callbook.cfg` if present).

Run: `python dev/test_render.py` / `python dev/bench_latency.py`.
