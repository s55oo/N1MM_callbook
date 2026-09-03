# LAN cache sharing — design notes (not yet implemented)

**Status: design locked, not built.** Nothing in the code yet. This
records the agreed design so it is ready to pick up.

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

Config: `lan_share=yes` (on by default) and `lan_share_port=6768`,
mirroring the `vhfctest_share` / `vhfctest_port` pattern.

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

**Entry packet** — the workhorse, carries one resolved callsign:

```json
{"cbshare": 1, "call": "S55OO",
 "fields": { ...same shape as a Callbooker_cache.json entry... },
 "ts": 1735900000, "schema": 3}
```

**Sync-request packet** — sent once on startup:

```json
{"cbshare": 1, "req": "sync", "since": 0}
```

That is the whole protocol. No TCP, no ephemeral ports, no gzip, no
fragment reassembly — each callsign is its own small (~200 byte) packet.

### Live sharing (Tier 1)

When an instance finishes resolving a call — from its own cache **or** a
fresh fetch — it broadcasts one **entry packet**.

Every instance also listens. On receiving an entry packet: if it is newer
than the local cache entry (or the entry is missing), merge it in, reusing
the exact freshness / `CACHE_SCHEMA` logic already used for
`Callbooker_cache.json`. **Received entries are not re-broadcast** (only
the resolver that actually fetched broadcasts) — O(1) messages per lookup,
no storms, no O(n²).

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
~10 s. `since` is `0` on a cold start; a warm restart can set it to the
newest local `ts` so peers only replay what is newer.

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
- README line to add when this ships (LAN-caching section): *"first run
  may show a Windows Firewall prompt for port 6768 — allow it for Private
  networks."* Same pattern as the VHFCtest4WIN 6767 note.

## Integration points (when implemented)

- New config keys: `lan_share=yes` (default on), `lan_share_port=6768`.
- A `LANShare` class using the existing socket/thread pattern: one
  listener thread on 6768 → an inbox drained on the GUI thread in
  `_poll_inbox` (same pattern as `_inbox` / `_v4w_inbox`), and a small
  send helper.
- Wire into `n1mm_callbook.py`'s cache path: broadcast an entry packet
  from wherever a lookup completes and the cache is updated
  (`_poll_inbox` after the last slot lands; also on a cache hit in
  `_on_stable`). Merge incoming entries through the same freshness/schema
  gate as `Cache` load.
- The Tier 2 responder is the same listener thread reacting to a
  `req:"sync"` packet with a rate-limited replay of `Cache` contents.
- Tests in the `dev/test_render.py` style: the merge freshness/schema
  logic and the responder rate/cap logic exercised headless, no sockets.
- This is a **user-facing change** → full release ritual when it ships
  (see `CLAUDE.md`).
