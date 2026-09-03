# Logger feeds — what Callbooker listens to, and how to add another

Callbooker does not talk to any logger's API. It only **reads the UDP
broadcast** a logger already sends on the LAN and pulls two things out of
each datagram: the **worked callsign** and (for the HF/VHF view switch)
the **operating frequency**. Everything else — QRZ / QRZCQ / HamQTH
lookups, the side-by-side display — is downstream of that.

The one property that makes a feed *useful* is **timing**: the packet has
to arrive **before the QSO is logged** (as the operator tabs/spaces off
the callsign field), so a wrong locator or name can still be fixed. A
logger that only broadcasts *on log* (after Enter) can drive Callbooker
but the check then comes too late to matter.

Two listener sockets run at once (`n1mm_callbook.py`):

| Port | Feed | Parser | Trigger |
|---|---|---|---|
| **12060** UDP | N1MM Logger+, DXLog.net | `packet_callsign()` + `packet_freq_mhz()` | Space/Tab off the call field (pre-log) |
| **6767** UDP | VHFCtest4WIN | `packet_v4w()` | every keystroke (pre-log) |

---

## N1MM Logger+ — shipped

**The reference feed.** N1MM's *External Broadcast* sends XML datagrams to
a configurable `IP:port` (Callbooker expects **12060**):

- **`<lookupinfo>`** — sent when you type a call and press **Space** to
  move to the exchange field, *before* the QSO is logged. Needs the
  **External Callsign Lookup** broadcast option on. This is the primary
  trigger.
- **`<contactinfo>`** — sent when the QSO is added to the log. Needs the
  **Contacts** broadcast option on. Later than ideal, but supported.
- **`<contactreplace>`** — an edit to a logged QSO. Also parsed.
- **`<radioinfo>`** — the *local* operator's own call and current
  frequency. The call is **ignored** (it is not the worked station); the
  frequency **is** kept as `self._last_mhz`, a fallback for the HF/VHF
  decision when a `<lookupinfo>` carries no frequency yet.

Field shapes (`packet_callsign` / `packet_freq_mhz`):

- callsign: lowercase `<call>` (also accepts capitalised `<Call>`).
- frequency: `<rxfreq>` / `<txfreq>` on lookup/contact, `<Freq>` on radio
  info, **all in *tens of hertz*** — `14430000` → 144.300 MHz, hence
  `÷ 100000`.

Setup: README section 1, "N1MM Logger+".

---

## DXLog.net — shipped (documentation only, no code change)

DXLog.net's broadcast, with **Use N1MM QSO format** ticked, sends a
**byte-compatible `<lookupinfo>`** on 12060 — same tag, same lowercase
`<call>`, same `<txfreq>` in tens of Hz. `packet_callsign()` and
`packet_freq_mhz()` parse it unchanged.

Verified 2026-09 against **DXLog.net v2.6.34** by capturing a live packet
(`dev/sniff_multi.py 12060`) while working a QSO and running the bytes
through both parsers.

- Menu path: **Options → Broadcast**.
- Tick **Use N1MM QSO format** and **Callsign on space or tab**
  (`<reason>SpaceOrTab</reason>` in the packet — the pre-log trigger,
  same role as N1MM's *External Callsign Lookup*). **QSOs** is optional
  (adds the on-log `<contactinfo>`).
- Target defaults to `127.0.0.1:12060` (`Network_QSOsBroadcastPort` in
  `%AppData%\DXLog.net\DXLog.net.config`) — leave it when Callbooker is on
  the same PC. **Do not hand-edit that config while DXLog is running** —
  it rewrites the file on exit.
- Relevant config keys: `QSOsBroadcast`, `QSOsBroadcastN1MMformat`,
  `Network_QSOsBroadcastIP`, `Network_QSOsBroadcastPort`. The first two
  being `0` is why the first sniff attempts caught nothing.

Setup + screenshot: README section 1, "DXLog.net"
(`docs/dxlog-broadcast-setup.png`).

---

## VHFCtest4WIN — shipped (its own listener on 6767)

Different protocol, different port, needs elevation to read locally.
Fully covered in **`dev/vhfctest4win-integration.md`**; summary in
`CLAUDE.md`. Broadcasts `<V4W><QSOINLOG><CALLSIGN>…` **per keystroke** on
UDP 6767; `packet_v4w()` handles it; `v4w_listener_loop()` falls back to a
`SIO_RCVALL` raw socket (UAC prompt) because VHFCtest4WIN holds 6767 with
`SO_EXCLUSIVEADDRUSE`.

---

## WriteLog — not done; what it would take

**Status: unevaluated.** No WriteLog packet has been captured, so we do
not yet know its format or timing. The decision tree:

1. **Does WriteLog broadcast UDP, and in what format?**
   - If it can emit **N1MM-format XML** (some versions have an
     N1MM-compatible broadcast option, like DXLog) → likely **zero code**,
     documentation only, exactly like DXLog.
   - If it emits **WriteLog's own format** → a new parser branch is
     needed. WriteLog has historically broadcast its own QSO format, so
     assume this case until a capture proves otherwise.

2. **Capture a real packet.** Run `python dev/sniff_multi.py <ports>`
   (start with `12060`, then WriteLog's configured networking port) while
   the user works and logs a QSO in WriteLog. Record:
   - the UDP port;
   - the exact bytes — XML vs flat text, the callsign field name, the
     frequency field name **and its units** (Hz / kHz / tens of Hz);
   - **timing** — does a datagram arrive as the operator tabs off the
     call field (pre-log, useful) or only on Enter (post-log, weak)?
   - whether any packet carries the local op's own call to be ignored
     (like N1MM's `<radioinfo>`).

3. **Run the bytes through the parsers.** Feed the captured datagram to
   `n1mm_callbook.packet_callsign()` and `packet_freq_mhz()`.
   - `packet_callsign()` returns a call only when `root.tag.lower()` is
     `lookupinfo` / `contactinfo` / `contactreplace`. Any other root tag →
     add a branch (or a sibling `packet_writelog()` if the structure is
     unlike N1MM's, mirroring `packet_v4w()`).
   - `packet_freq_mhz()` only looks at `rxfreq` / `txfreq` / `freq` and
     assumes tens of Hz. A different field or unit → add a branch with the
     right divisor.

4. **Wire the listener.**
   - WriteLog on **12060** → the existing socket already receives it;
     `on_packet` just needs to try the extra parser.
   - WriteLog on a **different port** → add a second listener socket. The
     6767 path (`v4w_listener_loop` → `_v4w_inbox` → `_poll_inbox` →
     `_handle_call`) is the template; a plain UDP bind should be enough
     (WriteLog is unlikely to take the port with `SO_EXCLUSIVEADDRUSE`, so
     probably no raw-socket / UAC dance).
   - Config: reuse `--port` for a single custom port, or add a
     `writelog_port=` key if it needs its own.

5. **Tests + docs.**
   - A parser test with the captured sample packet, in the style of
     `dev/test_render.py`.
   - README section 1: a "WriteLog" subsection with a setup screenshot.
   - `CLAUDE.md` architecture table: note in the `packet_callsign()` row.

6. **Ship it.**
   - **Docs-only** (WriteLog turns out to be N1MM-format, no code change):
     commit to `main` + push, **no version bump, no release**.
   - **Parser change** (a new branch or listener): that is a user-facing
     change → full release ritual (`CLAUDE.md` "Release ritual") — version
     bump in both files, changelog, rebuilt EXE, tag, `gh release create`.

---

## The repeatable method (any new logger)

1. Find the logger's config; confirm it can UDP-broadcast and turn it on.
2. Sniff a real packet: `python dev/sniff_multi.py <port…>` while working
   *and* logging a QSO.
3. Run the bytes through `packet_callsign()` and `packet_freq_mhz()`.
4. Same root tag + fields as N1MM → **no code**, document only. Different
   → add a parser branch (or a `packet_<logger>()` sibling) and, if it is
   on a new port, a second listener socket modelled on the 6767 path.
5. Check the **timing** — a pre-log trigger is the whole point; a
   post-log-only feed still works but says so in the docs.
6. Document: README section 1 subsection + screenshot, `CLAUDE.md` note.
   Docs-only ships without a release; a parser/listener change is
   user-facing and gets the full release ritual.
