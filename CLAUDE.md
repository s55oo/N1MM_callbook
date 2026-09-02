# CLAUDE.md — developer notes for N1MM_callbook

Context for anyone (human or AI) picking this repo up. Pair it with
`README.md`, which is the user-facing documentation.

## What it is

Always-on-top Tkinter windows that listen to the **N1MM Logger+** external
UDP broadcast (XML, port 12060) and look up the callsign being worked.
Every configured source is queried **in parallel** and *all* of its
values are shown side by side, so when sources disagree the wrong one is
obvious and the operator picks the right value for the exchange.

- **HF** (`n1mm_callbook.py`, v2.x): shows `name - state/zone state/zone …`;
  for DX (non-US) stations `name (country) - zone zone …`. When every
  source agrees the repeated token collapses to one in a larger green font
  (`Fred - MA/5`).
- **VHF** (`VHFcallbook.py`, v1.x): the same, showing the maidenhead
  locator per source instead of state/zone (`Hans - JN76HD` when all
  agree). `VHFcallbookApp` is a ~35-line subclass of the HF app's
  `CallbookApp`. It listens on **both** the N1MM port (12060) and
  VHFCtest4WIN's multi-op sharing broadcast (UDP 6767) at once, so it
  works with either logger; the 6767 feed also carries the callsign *as
  it is typed*, pre-log. `main()` reads `vhfctest_share` (**default yes**)
  *before* the GUI via `_wants_v4w_feed()` so the UAC self-relaunch can be
  skipped when the feed is off, then calls
  `run(..., always_vhfctest=<that bool>)` — passing the computed bool
  covers both "force on" and "off unless cfg opts in", so no engine
  change was needed. (History: `VHFcallbook` 1.0 merged and replaced the
  old `n1mm_VHFcallbook` + `VHFctest4WinCallbook`; 1.1 deleted them and
  folded `VHFApp` into `VHFcallbook.py`.)

Pure Python standard library — no third-party runtime dependencies. The
VHFCtest4WIN raw-capture (`_v4w_raw_listen`, a Windows `SIO_RCVALL`
socket) needs the app elevated; `VHFcallbook.main()` handles that by
relaunching itself via `ShellExecuteW "runas"` (`--elevated` guards the
loop) when 6767 is held and the process is not already admin, and
degrades to a footer hint if the UAC prompt is declined.
PyInstaller is only needed to build the EXEs. Public domain (Unlicense).

## Architecture (all in `n1mm_callbook.py` unless noted)

| Piece | Role |
|---|---|
| `packet_callsign()` | pull the worked call out of a `LookupInfo`/`ContactInfo`/`ContactReplace` XML packet (`RadioInfo` is ignored — it carries the local op's own call) |
| `packet_v4w()` | pull the callsign out of a VHFCtest4WIN `<V4W><QSOINLOG>` sharing packet (UDP 6767); empty `<CALLSIGN>` → `None` |
| `v4w_listener_loop()` | second listener (VHF only — on by default in `VHFcallbook`, `vhfctest_share=no` to disable). Tries a normal UDP bind on 6767; VHFCtest4WIN holds that port with `SO_EXCLUSIVEADDRUSE`, so if it is already running the bind fails and it falls back to `_v4w_raw_listen` — a Windows `SIO_RCVALL` raw socket that needs the app run as admin. Feeds callsigns to `_on_v4w_call` → `_v4w_inbox` → `_poll_inbox` (same cross-thread hand-off as `_inbox`; never touches Tk off-thread) → `_handle_call` |
| `normalize_call()` / `normalize_grid()` | sanitise the call; upper-case locators so a case-only difference isn't seen as a disagreement |
| `_HttpPool` / `http_get()` | one kept-alive HTTPS connection per host, gzip, per-host lock, stale-connection retry, busy-host fallback to a one-shot connection. **All source fetches go through `http_get`.** |
| `Cache` | JSON cache keyed by call. `put()` only marks dirty; `flush()` (driven from `_poll_inbox`, forced in `on_close`) writes at most once per `FLUSH_INTERVAL`. Stores only `_CACHE_FIELDS`. Prunes expired / wrong-`CACHE_SCHEMA` entries on load. `persist=False` (`cache_persist=no`) = in-memory only. |
| `qrzcq_lookup` / `hamqth_lookup` / `qrz_lookup` / `qrzdb_lookup` | the sources. Each returns a dict with the same keys (`name qth grid class state cqzone country`) or `None` on any failure. `Cache` stores only `_CACHE_FIELDS` (the 5 the display reads). `qrz_lookup` needs paid QRZ XML creds; `qrzdb_lookup` (VHF-only) computes the grid from `cs_lat`/`cs_lon` on the public QRZ page. |
| `qrz_session_load()` / `_qrz_session_save()` | persist the QRZ XML session key to `qrz_session.json` so a restart skips the ~0.6 s re-login |
| `load_config()` / `run()` | shared entry point — parse args + the `key=value` .cfg, build the app, run the Tk loop. Each `main()` is basically one `run()` call. `run(..., always_vhfctest=True)` forces the 6767 feed on regardless of `vhfctest_share`; `VHFcallbook` passes a *computed* bool there (feed on unless `vhfctest_share=no`). |
| `CallbookApp` | the window + all lookup orchestration. Subclassed only by `VHFcallbookApp` (in `VHFcallbook.py`). |

### CallbookApp lookup flow

`on_packet` → debounce 300 ms → `_on_stable` → cache hit renders immediately,
else `_start_lookup` → `_do_lookup` spawns **one thread per source** →
each posts `(call, slot_index, result_or_None)` to `self._inbox` →
`_poll_inbox` (GUI thread, every 100 ms) drains the queue, drops results
whose call != `self.current`, renders each slot as it lands, and caches
once every slot is in.

### Start-up self-test

`run()` resolves `selftest` / `selftest_call` (default `S55OO`, empty =
off) and passes the call to `__init__`, which schedules
`_start_precheck` ~150 ms after the window is up. It fires one thread per
source (same pattern as `_do_lookup`), each posting
`(slot_index, status, ms)` to `self._precheck_inbox` where `status` is
`"OK"` / `"no data"` (reachable, empty dict) / `"FAIL"` (`None`).
`_poll_inbox` drains it, `_render_precheck` draws one monospaced line per
source, and once every slot is in it schedules `_finish_precheck`
(`PRECHECK_HOLD_MS` later) to restore the idle `—`. A real callsign
supersedes it: `_handle_call` clears `_precheck_active` and
`_render_precheck` early-outs whenever `self.current` is set. The default
call is listed on every source (with the same locator), so a healthy run
is all-green; `status` only checks that a source *answered*, not that the
sources agree.

`_render_slots` builds the display string. `_source_value` joins the
`SLOT_FIELDS` into one `a/b` token per slot; the `state` field is dropped
when the source's country is non-US (`_US_NAMES`), but `cqzone` is kept.
`_is_dx` decides the `name (country)` vs `name` prefix – only consulted
when `DX_COUNTRY` is set (HF; the VHF apps turn it off). Slots are joined
by `SLOT_SEP`; an empty slot is `SLOT_EMPTY` (`·`), a pending one
`SLOT_PENDING` (`…`). When `all_done` and every real value matches (>=2 of
them) the text fill is `TEXT_AGREE` (light green) instead of `TEXT_DEFAULT`
(`agree`). When `agree` **and** `COLLAPSE_ON_AGREE` (on for every app),
that one value is shown once instead of `SLOT_SEP`-joined. The font is
`FONT_SIZE_BIG` for **any** result line `<= FONT_BIG_MAXLEN` chars (the
collapsed token, but also a short disagreement / partial answer), else
the length-based `_font_for`.

### Class attributes `VHFcallbookApp` overrides (base = HF behaviour)

```
VERSION       # title-bar version — set on the subclass, NOT the module __version__
APP_TITLE
SLOT_FIELDS   # HF ("state","cqzone");  VHF ("grid",)
SLOT_SEP      # HF " " (name already has " - " after it);  VHF " - "
SHOW_NAME     # HF True; VHF also True (name printed once, in front of the grids)
DX_COUNTRY    # HF True (name -> "name (country)" for DX);  VHF False
LOOKUP_CHAIN  # HF (qrzcq, hamqth); VHF adds qrzdb; qrz_lookup prepended by __init__ when creds exist
VHFCTEST_CAPABLE  # base False; True on VHF — allows the 6767 feed (run() wires the 2nd listener)
```

`COLLAPSE_ON_AGREE` is `True` on the base `CallbookApp` now (both apps
collapse a unanimous result), so `VHFcallbookApp` no longer overrides it.

## Gotchas / history (don't reintroduce these bugs)

- **No `_fetching` guard.** An earlier version skipped a new lookup while
  one was "in flight"; retyping a call mid-lookup then wedged all future
  lookups. `_start_lookup` now always starts fresh; stale results are
  dropped by the `call != self.current` check.
- **`CallbookApp.VERSION`, not module `__version__`.** `_build` reads
  `self.VERSION`. The VHF title bar used to show the HF version because it
  referenced the base module's global.
- **Bump `CACHE_SCHEMA`** only when an old entry would now display *wrong*
  (a field's meaning or normalisation changed) — not merely differently.
  v1→v2 added `cqzone` + upper-cased locators, so it bumped. v2.10 trimmed
  the stored fields but old wider entries still read fine, so it did not.
- **`normalize_grid` is applied twice**: in each lookup (so the cache is
  clean) and in `_source_field` on read (so a stale cache entry still
  displays consistently).
- Source pages are scraped with regex — markup drift fails silently
  (fields just go empty → `·`). `dev/bench_latency.py` doubles as a quick
  "are the sources still parsing?" check before a contest.

## Files the app writes (all gitignored, all safe to delete)

`*_cache.json` (lookup cache), `*_window.json` (last window position,
restored on start — position only, not size), `qrz_session.json` (QRZ XML
session key). They live next to the `.cfg`/exe.

**Never commit `callbook.cfg` / `VHFcallbook.cfg`** (nor the retired
`n1mm_VHFcallbook.cfg` / `VHFctest4WinCallbook.cfg`, still gitignored) —
they hold the QRZ login in plain text. Only `*.cfg.template`
(placeholders) is tracked.

## Build

```bat
python -m PyInstaller --onefile --windowed --name n1mm_callbook --manifest manifest.xml --noconfirm n1mm_callbook.py
python -m PyInstaller --onefile --windowed --name VHFcallbook --manifest manifest.xml --noconfirm VHFcallbook.py
copy /Y dist\n1mm_callbook.exe .
copy /Y dist\VHFcallbook.exe .
```

## Release ritual

A **user-facing change** (a feature or a bug fix) gets the full ritual and
a release. A **docs / `dev/` / comment change** is committed and pushed
only — no version bump, no release.

Full ritual:

1. Bump `__version__` in the changed app files + the `USER_AGENT` in
   `n1mm_callbook.py`. HF `n1mm_callbook` (~2.x) and VHF `VHFcallbook`
   (~1.x) carry independent numbers; a change to the shared engine
   (`n1mm_callbook.py`) bumps both, even when the other app's behaviour is
   unchanged. A change confined to one app file bumps only that app.
2. README: version banner near the top + a new entry at the top of
   `## 7. Changelog`.
3. Rebuild the affected EXEs, copy to repo root (`--noconfirm` also
   rewrites the `.spec` files — leave those, they're unchanged content).
4. `git grep` for your QRZ username / password → confirm no real
   credential reached a tracked file.
5. Commit straight to `main` (no branch), terse semicolon-joined message.
6. Push.
7. Release: `gh` authenticated via `GH_TOKEN` env only (never
   `gh auth login`), tag `main`, then
   `gh release create vX.Y --verify-tag --latest` attaching the EXEs, the
   `*.cfg.template` files and `LICENSE`.

## dev/

- `dev/test_render.py` — headless render-logic tests (fake canvas, no network).
- `dev/bench_latency.py` — measures per-source and end-to-end lookup
  latency (reads QRZ creds from `callbook.cfg` if present).

Run: `python dev/test_render.py` / `python dev/bench_latency.py`.
