# LAN cache sharing + MQTT + diagnostics — session reference

Where the 1.2–1.6 work was done, for `claude --resume`. The design and
"as built" detail is in `dev/lan-cache-sharing.md` and
`dev/mqtt-integration.md`; this file is just the history and pointers.

## Session (2026-09-03)

- Web: https://claude.ai/code/session_018VQesBs2tYog1wLnmRip9j
- Transcript:
  `C:\Users\Goran\.claude\projects\C--HAM-N1MM-Logger--N1MM-callbook\e46c11b4-e102-4b58-958a-1c4a97778d38.jsonl`
- Started from `C:\Users\Goran`; `cd` into this repo after resuming.

## What shipped, in order

| Rel | Commit | What |
|---|---|---|
| — | `2a4a66f` `27cc0d4` | DXLog.net works on 12060 unchanged (docs only) |
| — | `61ec200` | `dev/logger-feeds.md` — all feeds + how to add one; WriteLog to-do |
| — | `6fc7c48`…`d9c1dbf` | `dev/lan-cache-sharing.md` — design iterated to "locked" (one packet type, no TCP, ask-the-LAN-first, 50 ms grace) |
| **1.2** | `ebe28e0` | **LAN cache sharing** — `LANShare` on UDP 6768 |
| **1.3** | `9ecf775` | **MQTT output** — integrated PR #2 (S53ZO) on top of 1.2 by hand (branch predated it); `mqtt_client.py`, paho bundled |
| — | `3f416b8` | `dev/mqtt-integration.md` |
| **1.4** | `c3c9599` | Temporary footer tag `· online` / `· LAN 6768` / `· cache` |
| **1.5** | `6056eb1` | Multi-homed broadcast fix + `(N peers)` title + `dev/lan_probe.py` |
| **1.6** | `8293afa` | Removed the 1.4/1.5 temp diagnostics; kept the broadcast fix + probe |

## The multi-homed broadcast bug (1.5)

The user tested LAN sharing on two PCs and it did not work. Root cause:
`LANShare._send` broadcast only to `255.255.255.255`, which on a
multi-homed Windows PC can egress a **virtual adapter** (VirtualBox
host-only `192.168.56.1`, Hyper-V, a VPN) instead of the real LAN NIC —
so the datagrams never reached the other PC. This dev box shows the exact
shape: `local_interfaces()` → `['192.168.56.1', '169.254.177.224',
'192.168.178.55']`, where only the last is the real LAN.

Fix (`LANShare._broadcast_targets`): send to `255.255.255.255` **and**
each local interface's `<net>.255` directed broadcast, plus any
`lan_share_bcast=` extras from the .cfg for a non-/24 LAN. Kept in 1.6.

The user's other likely culprits, in the README "Not sharing between
PCs?" checklist: Windows Firewall inbound UDP 6768, a Public network
profile, different subnets / Wi-Fi client isolation.

`dev/lan_probe.py` (`listen` on one PC, `send` on the other) proves
whether 6768 crosses the network at all, independent of Callbooker.

## PR #2 reconciliation (1.3)

PR #2 keyed the cache `call|mode|source_labels` to avoid a mislabelled
slot after an HF↔VHF switch. That breaks LAN sharing (peers gossip under
the bare call; different QRZ-credential setups have different label sets).
Resolved by keeping the **bare-call** key and rejecting a wrong-length
cached entry in `CallbookApp._cached_sources()` instead. PR #2 closed with
a comment explaining the by-hand re-apply.

## Standing decisions from the user

- Features that send data **off the machine** (MQTT) default to
  **disabled**; LAN-local features (6768 sharing) default **on**.
- MQTT `paho-mqtt` is **bundled into `Callbooker.exe`** (not source-only).
- User-facing changes get the full release ritual (version bump both
  files, changelog, rebuilt exe, tag, `gh release create`); docs/`dev/`
  changes are commit + push only.
