# VHFCtest4WIN integration

**Status: shipped** as `VHFctest4WinCallbook` (v1.0), and as the
`vhfctest_share=yes` option on `n1mm_VHFcallbook`. This file is the
background; the user-facing docs are README section 1 and `CLAUDE.md`.

## Goal

The user (S53ZO / S55OO) runs **VHFCtest4WIN** (VHF contest logger by
Peter Orešnik S52AA, VB6). He wants the locator check to warn about a
**wrong QRA locator before the QSO is logged** ("I don't want to log it
with wrong qra locator"). The post-Enter path does not interest him.

## What VHFCtest4WIN sends — confirmed by packet capture (2026-08-29)

As the operator types in the entry field, VHFCtest4WIN broadcasts one UDP
datagram **per keystroke** to its multi-op sharing address (the
`[Network] BroadcastIP` in `VHFCtest4Win.ini`; here `10.147.17.255`),
**source and destination port 6767**:

```
<V4W><QSOINLOG><CALLSIGN>S56M</CALLSIGN><CALLSIGN_COMPLETE>TRUE
</CALLSIGN_COMPLETE><BAND>144 MHz</BAND><QSONUMBER></QSONUMBER>
<WWL>JN76GB</WWL><WWL_COMPLETE>TRUE</WWL_COMPLETE></QSOINLOG></V4W>
```

- Fields grow as they are typed (`JN` → `JN7` → `JN76GB`); each has an
  optional `*_COMPLETE` flag. When the field is cleared an all-empty
  `<CALLSIGN></CALLSIGN>` datagram is sent.
- `<BAND>` mirrors the VHFCtest4WIN `Nickname` (`144 MHz`).
- **No working CAT connection is needed** — 232 packets were captured with
  CAT disconnected. CAT only adds the separate `<FREQUENCY>` broadcast.
  (This corrects the earlier "seems to need CAT" note.)
- `<contactinfo>` on 12060 (N1MM-style, post-Enter) also works but is not
  used — the user only wants the pre-log trigger.

Raw captures: `dev/vhfctest4win-captures/`.

## The port-6767 problem and the fix

VHFCtest4WIN binds `0.0.0.0:6767` with **`SO_EXCLUSIVEADDRUSE`**. While it
is running, **no second process on the same PC can bind 6767** — not
`0.0.0.0`, not a specific interface IP, not `127.0.0.1`, with or without
`SO_REUSEADDR` (all fail `WinError 10013`). Starting the callbook *first*
lets it bind, but then VHFCtest4WIN's own bind fails and it stops
broadcasting.

`v4w_listener_loop` therefore does:

1. Try an ordinary `SOCK_DGRAM` bind on 6767. Works when VHFCtest4WIN is
   on another PC on the network, or is not running. **Starting the
   callbook first so it grabs 6767 does NOT work** - VHFCtest4WIN then
   malfunctions and sends no `<QSOINLOG>` at all (tested 2026-08-29).
2. On bind failure, `_v4w_raw_listen`: a Windows **`SIO_RCVALL` raw
   socket** on each local interface, filtered to UDP dst port 6767. This
   reads the broadcast below the socket layer. Confirmed to capture the
   locally-originated subnet broadcast. **Needs the process elevated**
   (an admin *token*, not just an admin user account).
3. `VHFctest4WinCallbook.main()` bridges 1→2: if 6767 is held and the
   process is not admin, it relaunches itself elevated via
   `ShellExecuteW "runas"` (one UAC prompt; `--elevated` stops the loop).
4. If the UAC prompt is declined, it runs unelevated and `on_status` puts
   a one-line hint in the footer.

`dumpcap` (Wireshark) also captures 6767 unelevated *if* Npcap allows
non-admin capture, but that means installing Wireshark on every PC, which
the user did not want; bundling it is a non-starter (the Npcap kernel
driver cannot ride in the exe and its redistribution needs a paid OEM
licence). So elevation is the path.

## Code map

- `packet_v4w(data)` — callsign out of a `<V4W><QSOINLOG>` datagram.
- `_udp_payload(pkt, port)` — UDP payload out of a raw IPv4 packet.
- `_v4w_raw_listen` / `v4w_listener_loop` — the two-stage listener above.
- `CallbookApp`: `_v4w_inbox` / `_on_v4w_call(call, src)` / `_on_v4w_status`
  — the listener thread hands callsigns and the status hint to the GUI
  thread in `_poll_inbox` (same pattern as `_inbox`); `_handle_call` is
  the shared debounce → lookup path for callsigns from any feed.
  `_on_v4w_call` drops any datagram whose `src` is not in `self.local`,
  so in a multi-op each PC follows only its own operator (VHFCtest4WIN
  broadcasts the entry field to the whole subnet). Windows raw
  `SIO_RCVALL` was confirmed to also capture loopback (`127.x`) traffic
  on this Win11 box, so it works whether `BroadcastIP` is the subnet or
  `127.0.0.1`.
- `VHFCTEST_CAPABLE` (True on `VHFApp`) + `run(always_vhfctest=...)`.
- `VHFctest4WinCallbook.py` — `VHFApp` subclass, feed always on.

## Dev tools (`dev/`)

- `sniff_multi.py <ports…>` — UDP+TCP sniffer, one log per run.
- `test_rcvall2.py` — proves `SIO_RCVALL` captures a local broadcast
  (run elevated).
- `probe_window.py` — dumps VHFCtest4WIN's window controls (was the
  fallback plan if the packet route had failed; callsign box is a
  `TEdit`, locator box the unique `TLocatorEdit`).
