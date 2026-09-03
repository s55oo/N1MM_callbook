# MQTT lookup-result publishing

**Status: shipped in Callbooker 1.3.** `mqtt_client.py` + wiring in
`n1mm_callbook.py` / `Callbooker.py`. **Off by default**
(`mqtt_enabled=yes` to turn on). Tests: `dev/test_mqtt.py`. User-facing
docs: README section 3 ("MQTT output") and `Callbooker.cfg.template`.

## Provenance

Contributed by **S53ZO** as PR #2 (`feature/mqtt-result-publishing`,
commit `275c733`). That branch predated the 1.2 LAN-cache-sharing work
and conflicted in the same methods, so it was re-applied on top of `main`
by hand rather than merged — landed as commit `9ecf775`, released `v1.3`.
Reconciliation notes are in the closing comment on PR #2 and under
"Integration with LAN sharing" below.

## Goal

Publish one machine-readable record of every completed callsign lookup so
an external consumer (a scoreboard, a logging bridge, a shack dashboard)
can react to what the operator is working — **without** ever slowing down
or blocking the lookup window itself. A contest UI that stutters because a
broker is unreachable is worse than no feed at all.

## Design

### Dependency: paho-mqtt, optional and bundled

`mqtt_client.py` does `try: import paho.mqtt.client as mqtt / except
ImportError: mqtt = None`. The rest of the app is standard-library only
and runs unchanged when Paho is absent (MQTT then reports "install
paho-mqtt" if it was enabled, otherwise stays silent).

`requirements.txt` pins `paho-mqtt==2.1.0`. The Windows build bundles it:
`--hidden-import paho.mqtt.client` on the PyInstaller command (the lazy
import means static analysis needs the hint), baked into
`Callbooker.spec` so `pyinstaller Callbooker.spec` reproduces it.

### MqttPublisher — Paho owns the network thread

`MqttPublisher` wraps a **long-lived** `paho.mqtt.client.Client` with
`loop_start()` (Paho's own background network thread) and
`connect_async()`. `publish()` is called from the Tk GUI thread and
returns immediately:

- connected → hand the JSON to `client.publish(topic, body, qos, retain)`;
  for QoS 1/2 keep the `MQTTMessageInfo` in `_inflight` so `close()` can
  give acknowledgements a bounded (~1 s) chance to land.
- not connected → append to a bounded `deque` (`_pending`,
  `mqtt_queue_max`, default 100, hard max 1000); `_on_connect` flushes it
  oldest-first. A full queue drops the **oldest** entry and notes it in
  `error`.
- oversized payload (> `MAX_PAYLOAD_BYTES` = 16 KiB) → rejected, not
  queued.

`start()` validates config and returns an error string (empty = OK);
anything wrong (missing `mqtt_server`, a `+`/`#` in the publish topic, a
missing `mqtt_password_env` variable, a bad integer) disables MQTT with a
message rather than raising. TLS via `client.tls_set()` (custom
`mqtt_ca_certs`, resolved next to the config file; blank = OS trust
store), `tls_insecure` only for diagnosis. Reconnect backoff via
`reconnect_delay_set(mqtt_reconnect_min, mqtt_reconnect_max)`.

Client ID: `mqtt_client_id` if set, else a fresh random
`callbooker-XXXXXXXX` (`secrets.token_hex(4)`) each launch so several
stations don't collide on the broker.

### Payload — schema v1, built Tk-free

`lookup_payload(...)` in `mqtt_client.py` is a pure function (no Tk, no
app state) so it is trivially testable. It emits:

```
schema_version, published_at (UTC "...Z"), callsign, mode ("hf"/"vhf"),
feed ("n1mm"/"vhfctest4win"), frequency_mhz (null for VHFCtest4WIN),
cached (bool), summary {name, values[], agreement, selected_value},
sources[] {source, value, result | null}
```

`result` is the per-source `{name, grid, state, cqzone, country}`; a
failed source is `null`. Bump `schema_version` for any breaking change.

### When it publishes

`CallbookApp._publish_lookup_result(call, sources, cached, context)` is
the single choke point (bare `except` — MQTT must never touch the UI). It
is called from exactly three places, once per completed lookup:

- `_on_stable` — a local cache hit (`cached=True`).
- `_drain_lan_inbox` — a LAN peer answered the call-request instead of the
  websites (`cached=True`).
- `_poll_inbox` — the live lookup finished, on the tick that fills the
  last slot (`cached=False`; published even on a partial result — a failed
  source is a `null` entry).

### Per-lookup generation + context

Overlapping asynchronous lookups (the operator retypes mid-fetch) must not
let a slow stale source repaint **or publish** against the newer
callsign. `_handle_call` bumps `self._lookup_generation` and snapshots
`_capture_lookup_context()` — `{mode, feed, frequency_mhz,
source_labels}`. The generation and context travel through
`_on_stable → _lan_grace_expired → _start_lookup → _do_lookup` and into
each `_inbox` tuple `(call, generation, slot_index, result)`. `_poll_inbox`
drops any result whose generation ≠ the active lookup. `Callbooker.py`
sets `_result_feed` / `_result_frequency_mhz` on the N1MM and VHFCtest4WIN
feed paths so the snapshot has them.

### Footer error surfacing

`_poll_inbox` mirrors `self.mqtt.error` into the footer (`<call> ·
<error>`) when it changes, and restores the plain callsign when it clears
— the same "show once, then recover" pattern as the VHFCtest4WIN status
hint.

## Integration with LAN sharing (1.2)

The PR keyed the cache by `call|mode|source_labels` to stop a VHF QRZ slot
being relabelled as an HF QRZCQ result. That **breaks LAN sharing**: peers
gossip entries under the bare call, and two PCs with different QRZ
credentials have different label sets, so they would never share.

Resolution: **keep the bare-call cache key**. The HF↔VHF slot-count
mismatch is handled instead by `CallbookApp._cached_sources(call)` —
`cache.get(call)` but return `None` (→ re-fetch) if the stored source
count ≠ the current `lookup_chain` length. Same-config, same-mode PCs
(the overwhelmingly common case) hit the cache and share normally; a
genuine mismatch just costs a redundant fetch, never a mislabelled slot.

## Config keys

All optional; MQTT stays off until `mqtt_enabled=yes`.

```
mqtt_enabled, mqtt_server, mqtt_port (TLS default 8883, else 1883),
mqtt_topic (no + or #), mqtt_qos (0/1/2), mqtt_retain,
mqtt_client_id (blank = random), mqtt_username,
mqtt_password / mqtt_password_env, mqtt_tls, mqtt_ca_certs,
mqtt_tls_insecure, mqtt_keepalive, mqtt_queue_max, mqtt_reconnect_min,
mqtt_reconnect_max
```

`mqtt_password` / `mqtt_password_env` live only in the gitignored
`Callbooker.cfg`, like the QRZ login. `mqtt_password_env` (name an env
var) is preferred.

## Tests

`dev/test_mqtt.py` — no broker, no network:

- `_client_id` randomness / override; the production Paho constructor gets
  a random ID.
- `MqttPublisher` with a `FakeClient`: config → `connect`/`auth`/`tls`/
  `queue`/`reconnect` calls; pre-connect buffering and flush-on-connect;
  QoS/retain/topic forwarding; wildcard-topic and missing-env rejection;
  bounded queue keeps newest; oversized payload rejected; `close()` awaits
  QoS acks then `disconnect`/`loop_stop`.
- `lookup_payload` schema, source order, failure nulls, agreement summary.
- Engine integration with a fake cache + fake root: cache hit publishes
  once with the captured context; the final live source publishes once and
  a stale generation is dropped; the cache key is the bare call; the
  footer shows and recovers from an MQTT error; `Callbooker` feed events
  capture feed/frequency/mode.

The file carries a Tk-less `import_engine()` shim so it runs in CI on a
Python built without `_tkinter`.
