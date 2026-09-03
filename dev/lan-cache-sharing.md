# LAN cache sharing — design notes (not yet implemented)

**Status: proposed.** Nothing in the code yet. This records the design so
it is ready to pick up.

## Goal

In a multi-op / multi-PC setup, every Callbooker instance already listens
on 12060 and each PC independently resolves the call its own operator
typed (the "local computer only" rule). Today each PC also does its own
QRZ / QRZCQ / HamQTH fetch for that call. The idea: **the first PC to
resolve a callsign shares the result over the LAN**, so the other PCs get
it near-instantly instead of repeating the HTTP round trip.

Because of the local-computer-only rule, only one PC ever fetches a given
call in a session — so there are **no duplicate fetches across the LAN**
once sharing is on. That is the real win.

## Shape: UDP gossip, no central server

Fits the existing architecture — stdlib sockets/threads, JSON cache with a
schema version, "same app, nothing extra to install". No central cache
server (would need a process to run and manage on one PC), no multicast
(ham LANs are flat switches with hit-or-miss IGMP; broadcast is what we
already trust for 6767 / 12060).

### Dedicated port 6768 — **not** 12060

12060 is **N1MM's real multi-op network port**, carrying inter-station
`LookupInfo` / `ContactInfo` / `RadioInfo` XML between logging PCs during a
networked contest. Broadcasting JSON gossip on 12060 would:

- feed foreign packets to other PCs' N1MM / DXLog XML parsers (errors,
  warnings, worst case misbehaviour) — injecting risk into the **actual
  contest logging network**;
- create fragile multi-process send/receive-on-one-port situations that
  work on some Windows setups and not others;
- force sniffing every incoming 12060 packet to guess "N1MM XML or
  Callbooker JSON?" before parsing — CPU per packet, and a bad guess can
  throw on a real contest packet mid-QSO;
- widen the blast radius: a gossip-protocol bug should only ever break
  Callbooker's own cache, never the logger network carrying real QSOs.

A dedicated port keeps the gossip layer fully isolated — same reasoning as
VHFCtest4WIN getting its own 6767. Config key `lan_share_port=6768`,
mirroring `vhfctest_port`.

### Tier 1 — live gossip (the workhorse)

When an instance finishes resolving a call (from its own cache **or** a
fresh fetch), it broadcasts one small UDP packet on 6768:

```json
{"call": "S55OO", "fields": { ...same shape as a cache_file entry... },
 "ts": 1735900000, "schema": 3}
```

Every instance also listens on 6768. On receipt: if the entry is newer
than the local cache entry (or it is missing), merge it in — reuse the
exact freshness / `CACHE_SCHEMA` logic already used for
`Callbooker_cache.json`. **Received entries are not re-broadcast** (only
the resolver that actually fetched broadcasts) — O(1) messages per lookup,
no storms, no O(n²).

Trust a **local fresh** cache entry over an **older** broadcast for the
same call — a real re-work (operator fixed a busted call) must win over a
stale gossip entry. Timestamp comparison handles this naturally.

### Tier 2 — startup catch-up (bulk sync)

Tier 1 alone leaves a PC that joins mid-contest with an empty cache until
gossip trickles in. On launch, broadcast a small "sync request" on 6768
carrying an ephemeral **TCP** port. Any peer with a non-empty cache opens
a short TCP connection back and sends its cache (or just entries newer
than an optional `since` timestamp) as gzip'd JSON. TCP avoids UDP
fragmentation for a payload that can be hundreds of KB. **First responder
wins** — one recent cache is enough, no need to poll every peer.

## Security / safety

- Broadcast **only the displayed fields** — exactly what already goes to
  disk in `Callbooker_cache.json`. No QRZ credentials or session keys ever
  go over the wire; the existing security model is unchanged.
- The packet carries the cache `schema` version; a peer running an old EXE
  with a different `CACHE_SCHEMA` is **ignored**, not merged — no risk of
  corrupting the cache shape.
- A gossip-protocol bug can only ever affect Callbooker's own caching.

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

- New config keys: `lan_share=yes`, `lan_share_port=6768` — mirrors the
  `vhfctest_share` / `vhfctest_port` pattern.
- A `LANShare` class using the existing socket/thread pattern, wired into
  `n1mm_callbook.py`'s cache read/write path (`Cache.put` /
  `Cache.get` / the `_poll_inbox` flush).
- Tier 2's TCP responder as a small daemon thread, started with the
  listener.
- Tests in the `dev/test_render.py` style: gossip-merge freshness/schema
  logic exercised headless, no sockets.
- This is a **user-facing change** → full release ritual when it ships
  (see `CLAUDE.md`).
