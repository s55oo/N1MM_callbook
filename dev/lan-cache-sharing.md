# LAN cache sharing

**Status: shipped in Callbooker 1.2.** The `LANShare` class in
`n1mm_callbook.py` implements it; on by default, `lan_share=no` disables.
Tests: `dev/test_lan_share.py`. This file is the design and rationale.

## Goal

In a multi-op / multi-PC setup every Callbooker instance already listens
on 12060 and each PC independently resolves the call its own operator
typed (the "local computer only" rule). Today each PC also does its own
QRZ / QRZCQ / HamQTH fetch for that call. The idea: **the first PC to
resolve a callsign shares the result over the LAN**, so the other PCs get
it near-instantly instead of repeating the HTTP round trip.

Because of the local-computer-only rule, only one PC ever fetches a given
call in a session — so with sharing on there are **no duplicate fetches
across the LAN**. That is the real win.

## Transport: dedicated UDP 6768, broadcast

Stdlib sockets/threads, same style as the 6767 / 12060 listeners. No
central server (would need a process to run and manage on one PC), no
multicast (ham LANs are flat switches with hit-or-miss IGMP; broadcast is
what we already trust).

Config: `lan_share=yes` (on by default), `lan_share_port=6768`, and
`lan_share_bcast=` (extra broadcast addresses), mirroring the
`vhfctest_share` / `vhfctest_port` pattern.

**Send targets** (`LANShare._broadcast_targets`): `255.255.255.255` plus
each local interface's `<net>.255` (assuming /24), plus any
`lan_share_bcast` extras, de-duplicated. The limited broadcast alone can
egress the wrong adapter on a multi-homed PC — a VirtualBox host-only
`192.168.56.1`, a Hyper-V switch, a VPN — so aiming at the real LAN's
directed broadcast explicitly is the reliable path. Each datagram goes to
every target; the sender's own loopback copies merge to no-ops.

**Diagnostics** (temporary, 1.4–1.5): the title bar shows
`LAN 6768 (N peers)` where `N = len(LANShare.peers)` (distinct non-local
source IPs a valid `cbshare` packet arrived from); the footer tags each
resolution `· online` / `· LAN 6768` / `· cache`; `dev/lan_probe.py`
(`listen` / `send`) proves whether 6768 crosses the network without
involving Callbooker. If `N` stays 0 it is almost always the Windows
Firewall (inbound UDP 6768) or a Public network profile on the receiving
PC.

### Why 6768 and not 12060

12060 is **N1MM's real multi-op network port**, carrying inter-station
`LookupInfo` / `ContactInfo` / `RadioInfo` XML between logging PCs during a
networked contest. Broadcasting gossip on 12060 would:

- feed foreign packets to other PCs' N1MM / DXLog XML parsers (errors,
  warnings, worst case misbehaviour) — injecting risk into the **actual
  contest logging network**;
- create fragile multi-process send/receive-on-one-port situations that
  work on some Windows setups and not others;
- force sniffing every incoming 12060 packet to tell "N1MM XML or
  Callbooker gossip?" before parsing — CPU per packet, and a bad guess can
  throw on a real contest packet mid-QSO;
- widen the blast radius: a gossip bug should only ever break Callbooker's
  own cache, never the logger network carrying real QSOs.

A dedicated port keeps the gossip layer isolated — same reasoning as
VHFCtest4WIN getting its own 6767.

## Protocol: one packet type

Every datagram is JSON with a `cbshare` marker (protocol version). Any
datagram on 6768 without it is ignored without a parse throw — stray LAN
traffic can't break anything.

**Entry packet** — the workhorse, carries one resolved callsign. `sources`
is the per-source list exactly as `Callbooker_cache.json` stores it,
reduced to `_CACHE_FIELDS` by `_lan_trim` (no QRZ login, no session key):

```json
{"cbshare": 1, "call": "S55OO",
 "sources": [{"name": "...", "state": "...", "cqzone": "...",
              "grid": "...", "country": "..."}, ...],
 "ts": 1735900000.0, "schema": 2}
```

**Call-request packet** — "does anyone have this call?", sent on a local
cache miss in parallel with a grace-delayed HTTP lookup:

```json
{"cbshare": 1, "req": "call", "call": "S55OO"}
```

**Sync-request packet** — sent once on startup:

```json
{"cbshare": 1, "req": "sync", "since": 0}
```

That is the whole protocol — one entry packet plus two one-line requests.
No TCP, no ephemeral ports, no gzip, no fragment reassembly — each
callsign is its own small (~200 byte) packet.

### Lookup order — LAN before the callbook servers

When a call is committed (after the existing 300 ms debounce), the order
is:

1. **Local cache**, fresh → render, done. Nothing broadcast (peers already
   have it, or will ask).
2. **Local miss** → `_on_stable` broadcasts a **call-request packet**,
   arms `_await_lan = call`, and schedules `_lan_grace_expired` for
   `LAN_GRACE_MS` (50 ms) later:
   - A peer with a fresh cache entry replies with an **entry packet**.
     The listener thread appends it to `_lan_inbox`; `_lan_grace_expired`
     drains that inbox itself (`_drain_lan_inbox`), so the reply is picked
     up *within* the grace, not on the next 100 ms `_poll_inbox` tick. A
     merged entry that answers `_await_lan` clears the flag and renders —
     `_lan_grace_expired` then sees `_await_lan` gone and **does not start
     the HTTP lookup**. This is the win for calls *this* PC never worked
     but another PC did.
   - No entry by the grace deadline → `_lan_grace_expired` calls
     `_start_lookup` (QRZ / QRZCQ / HamQTH, exactly as before). A later
     LAN entry is merged by `_poll_inbox` like any gossip, and re-rendered
     only if no HTTP data is on screen yet.
3. **After an HTTP resolve** → `_poll_inbox` calls `lan.broadcast_entry`
   right after `cache.put` (Tier 1 live sharing, below).

**Grace = `LAN_GRACE_MS` (50 ms).** On a wired LAN the wire RTT is
sub-millisecond; the budget is a peer's thread wake-up + a dict lookup +
the reply, single-digit ms on a quiet gigabit segment. 50 ms is generous
margin for a busy peer, Windows timer granularity and jitter while staying
imperceptible — and because the HTTP lookup is only *scheduled*, not
blocked on, a full grace-period miss adds nothing beyond those 50 ms.
`_lan_grace_expired` draining `_lan_inbox` directly is what keeps the
100 ms poll cadence off the critical path. If two peers both answer, the
second entry packet has an equal-or-older `ts` and `Cache.merge` makes it
a no-op.

### Live sharing (Tier 1)

An instance broadcasts one **entry packet** when it resolves a call over
HTTP, and in reply to a **call-request packet** for a call it has fresh in
cache. A plain local cache hit is **not** broadcast — nobody asked.

Every instance also listens. On receiving an entry packet: if it is newer
than the local cache entry (or the entry is missing), merge it in, reusing
the exact freshness / `CACHE_SCHEMA` logic already used for
`Callbooker_cache.json`. **Received entries are not re-broadcast** (only
the resolver that actually fetched, or a peer answering a request,
sends) — O(1) messages per lookup, no storms, no O(n²).

Trust a **local fresh** cache entry over an **older** broadcast for the
same call — a real re-work (operator fixed a busted call) must win over a
stale gossip entry. Timestamp comparison handles this naturally.

### Startup catch-up (Tier 2) — "replay as gossip"

Tier 1 alone leaves a PC that joins mid-contest with an empty cache until
gossip trickles in. So on launch an instance broadcasts one
**sync-request packet**.

Every peer that hears it **re-broadcasts its own cache as ordinary entry
packets** — newest `ts` first — so the joiner merges them exactly like
live gossip. The joiner does nothing special; it is just receiving entry
packets faster for a few seconds.

Responder limits (keep it civil, and tame the contest-start case when
several PCs boot together):

- **rate-limit** each responder to ~200 entry packets/s (~40 KB/s);
- **cap** at ~1000 entries, newest first (older contest calls matter
  least, and Tier 1 fills the rest in as they are worked);
- **random 0–500 ms start stagger** before a responder begins, so peers
  don't all dump in lockstep;
- honor **at most one** sync request per ~30 s, whoever it came from;
- a peer that sent **its own** sync request in the last ~10 s **ignores**
  other peers' requests (it is still catching up itself);
- duplicate entries from multiple responders merge to a **no-op** (equal
  `ts`), so the redundancy of "everyone answers" is harmless.

Realistic multi-op is 2–6 PCs and a few thousand calls → a full sync in
~10 s. As built, `since` is always `0` (`request_sync` sends `"since": 0`)
— `_serve_sync` still honours a non-zero `since` from the wire, so a
warm-restart optimisation can be added later without a protocol change.

`items_since` also drops anything past the `cache_days` freshness window,
so a peer never replays entries the joiner would immediately prune.

## Security / safety

- Broadcast **only the displayed fields** — exactly what already goes to
  disk in `Callbooker_cache.json`. No QRZ credentials or session keys ever
  go over the wire; the existing security model is unchanged.
- Every packet carries the cache `schema`; a peer on an old EXE with a
  different `CACHE_SCHEMA` is **ignored**, not merged — no risk of
  corrupting the cache shape.
- The `cbshare` marker means non-Callbooker traffic on 6768 is dropped
  before any real parsing.
- A gossip bug can only ever affect Callbooker's own caching.

## Windows Firewall

Binding the 6768 listener triggers the standard "Windows Defender Firewall
has blocked some features of this app" dialog the **first time** — same as
the existing 12060 / 6767 listeners. Notes:

- It fires on **bind/listen**, not on send. Broadcasting out prompts
  nothing.
- The exception is keyed to the **exe path**, not its contents —
  rebuilding a new version at the same path does not re-prompt; renaming
  or moving the exe does.
- If the LAN is a **Public** network profile in Windows (common on club /
  contest stations, or Windows misdetecting the network), inbound is
  blocked by default and the user must tick that box or gossip packets
  silently never arrive — no error, just no LAN-cached data.
- The OS prompt cannot be pre-authorised or suppressed from inside the
  app; no manifest/code change helps.
- README covers it in section 1 ("LAN cache sharing (6768)") and the
  config template.

## As built — code map

All in `n1mm_callbook.py` unless noted.

- **Config** (`run()`): `lan_share` (default yes) and `lan_share_port`
  (default `LAN_SHARE_PORT` = 6768) → passed to `CallbookApp.__init__` as
  `lan_share_port` (0 = off).
- **`LANShare`** — the socket + listener thread. `start()` binds
  `("", port)` with `SO_REUSEADDR | SO_BROADCAST` (so several instances on
  one PC can share the port) and returns False if it can't (feature then
  stays off). `_send` fires one datagram to `255.255.255.255:<port>`;
  on a single-subnet multi-op LAN that reaches every host, and the sender
  also receives its own echo (harmless — `Cache.merge` no-ops it, and it
  never self-answers a `req:"call"` because a cache miss is why it asked).
  `close()` sets the stop event.
- **`LANShare._handle`** dispatches by `cbshare` marker then `req`:
  `"call"` → `_serve_call` (broadcast our entry if we have it fresh),
  `"sync"` → `_serve_sync` (rate/interval/self-hold guarded → a
  `_replay` thread: 0–500 ms stagger, `LAN_SYNC_RATE` pkt/s,
  `LAN_SYNC_CAP` entries, newest first), otherwise an entry packet →
  `_recv_entry` → `on_entry` (schema/ts validated).
- **`Cache`** gained `put()` returning the stored `ts`, `merge()`
  (newer-wins, returns whether it stored), `get_with_ts()`,
  `items_since()`. Keys stay the **bare call** so peers share entries
  regardless of HF/VHF view or per-PC QRZ-credential differences; the
  app's `_cached_sources()` rejects an entry whose source count no longer
  matches the active lookup chain (re-fetch) rather than keying by mode.
- **`CallbookApp`**: `self.lan` (LANShare or None), `self._lan_inbox`
  (listener-thread → GUI hand-off list, like `_v4w_inbox`),
  `self._await_lan` (callsign with an outstanding call-request).
  `_queue_lan_entry` (listener callback, list append only),
  `_drain_lan_inbox` (GUI: merge + conditional re-render), `_on_stable`
  (LAN-first), `_lan_grace_expired` (grace deadline → drain, else
  `_start_lookup`). `_poll_inbox` drains `_lan_inbox` every tick and
  broadcasts after an HTTP resolve. `on_close` calls `lan.close()`.
- **`CallbookerApp._build`** (`Callbooker.py`) adds `+ LAN <port>` to the
  title bar when the feed is up.

Tests: `dev/test_lan_share.py` — `Cache` helpers, `LANShare._handle`
dispatch (driven with bytes, `_send` stubbed), and the app lookup order
with a fake Tk root / canvas. `dev/lan_wire.py` is a real-UDP two-socket
smoke test (broadcast an entry, ask the LAN for a call, see what each
peer received) for confirming the wire works on a given LAN.
