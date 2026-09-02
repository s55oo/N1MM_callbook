# SPDX-License-Identifier: Unlicense
"""MQTT configuration and payload tests; no broker or network required."""

import json
import os
import sys
import threading
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mqtt_client as mc  # noqa: E402


class PublishInfo:
    rc = 0

    def __init__(self):
        self.waited = False

    def is_published(self):
        return False

    def wait_for_publish(self, timeout=None):
        self.waited = True
        return True


class FakeClient:
    def __init__(self):
        self.calls = []
        self.infos = []
        self.on_connect = None
        self.on_disconnect = None

    def username_pw_set(self, username, password):
        self.calls.append(("auth", username, password))

    def tls_set(self, ca_certs=None):
        self.calls.append(("tls", ca_certs))

    def tls_insecure_set(self, insecure):
        self.calls.append(("tls_insecure", insecure))

    def max_queued_messages_set(self, count):
        self.calls.append(("queue", count))

    def reconnect_delay_set(self, min_delay, max_delay):
        self.calls.append(("reconnect", min_delay, max_delay))

    def connect_async(self, host, port, keepalive):
        self.calls.append(("connect", host, port, keepalive))

    def loop_start(self):
        self.calls.append(("loop_start",))

    def publish(self, topic, body, qos, retain):
        self.calls.append(("publish", topic, json.loads(body), qos, retain))
        info = PublishInfo()
        self.infos.append(info)
        return info

    def disconnect(self):
        self.calls.append(("disconnect",))

    def loop_stop(self):
        self.calls.append(("loop_stop",))


def check(label, condition):
    print("  [{}] {}".format("ok  " if condition else "FAIL", label))
    return bool(condition)


def import_engine():
    """Import the engine even when this Python was built without Tk."""
    try:
        import n1mm_callbook
        return n1mm_callbook
    except ModuleNotFoundError as exc:
        if exc.name != "_tkinter":
            raise
    for name in list(sys.modules):
        if name == "tkinter" or name.startswith("tkinter."):
            del sys.modules[name]
    tkinter = types.ModuleType("tkinter")
    tkinter.__path__ = []
    tkfont = types.ModuleType("tkinter.font")
    tkinter.font = tkfont
    sys.modules["tkinter"] = tkinter
    sys.modules["tkinter.font"] = tkfont
    import n1mm_callbook
    return n1mm_callbook


def main():
    ok = True
    generated_a = mc._client_id({})
    generated_b = mc._client_id({})
    ok &= check(
        "default client IDs are random Callbooker names",
        generated_a.startswith("callbooker-")
        and generated_b.startswith("callbooker-")
        and generated_a != generated_b,
    )
    ok &= check(
        "configured client ID is preserved",
        mc._client_id({"mqtt_client_id": "station-one"}) == "station-one",
    )

    class FakeMqttModule:
        MQTTv311 = 4
        MQTT_ERR_NO_CONN = 4
        CallbackAPIVersion = types.SimpleNamespace(VERSION2=2)

        def __init__(self):
            self.client_ids = []

        def Client(self, _callback_version, client_id, protocol):
            self.client_ids.append((client_id, protocol))
            return FakeClient()

    real_mqtt, fake_mqtt = mc.mqtt, FakeMqttModule()
    mc.mqtt = fake_mqtt
    try:
        production = mc.MqttPublisher({
            "mqtt_enabled": "yes", "mqtt_server": "broker.example",
            "mqtt_topic": "results",
        })
        production.start()
        production.close()
    finally:
        mc.mqtt = real_mqtt
    ok &= check(
        "production Paho constructor receives random client ID",
        len(fake_mqtt.client_ids) == 1
        and fake_mqtt.client_ids[0][0].startswith("callbooker-"),
    )
    fake = FakeClient()
    settings = {
        "mqtt_enabled": "yes",
        "mqtt_server": "broker.example",
        "mqtt_topic": "radio/callbook/results",
        "mqtt_qos": "2",
        "mqtt_retain": "yes",
        "mqtt_username": "operator",
        "mqtt_password_env": "CALLBOOKER_TEST_MQTT_PASSWORD",
        "mqtt_tls": "yes",
        "mqtt_ca_certs": "broker-ca.pem",
        "mqtt_queue_max": "25",
        "mqtt_reconnect_min": "2",
        "mqtt_reconnect_max": "20",
    }
    os.environ["CALLBOOKER_TEST_MQTT_PASSWORD"] = "secret"
    publisher = mc.MqttPublisher(settings, "/config", lambda: fake)
    ok &= check("valid configuration starts", publisher.start() == "")
    ok &= check("publish waits for broker connection", publisher.publish({"queued": True}))
    ok &= check("pre-connect result buffered", not any(c[0] == "publish" for c in fake.calls))
    fake.on_connect(fake, None, None, 0, None)
    ok &= check("buffer flushed on connect", any(c[0] == "publish" for c in fake.calls))
    ok &= check(
        "TLS defaults to 8883 and configured keepalive",
        ("connect", "broker.example", 8883, 60) in fake.calls,
    )
    ok &= check("username/password configured", ("auth", "operator", "secret") in fake.calls)
    ok &= check("relative CA path resolved", ("tls", "/config/broker-ca.pem") in fake.calls)
    ok &= check("bounded offline queue configured", ("queue", 25) in fake.calls)

    payload = {"callsign": "S55OO"}
    ok &= check("publish accepted", publisher.publish(payload))
    sent = [call for call in fake.calls if call[0] == "publish"][-1]
    ok &= check(
        "topic, JSON, QoS and retain forwarded",
        sent[1:] == ("radio/callbook/results", payload, 2, True),
    )
    publisher.close()
    ok &= check("QoS acknowledgements awaited on close", all(i.waited for i in fake.infos))
    ok &= check("network loop stopped cleanly", fake.calls[-2:] == [("disconnect",), ("loop_stop",)])

    invalid = mc.MqttPublisher(
        {"mqtt_enabled": "yes", "mqtt_server": "x", "mqtt_topic": "bad/+"},
        client_factory=FakeClient,
    )
    ok &= check("wildcard publish topic rejected", "concrete publish topic" in invalid.start())
    missing_secret = mc.MqttPublisher({
        "mqtt_enabled": "yes", "mqtt_server": "x", "mqtt_topic": "results",
        "mqtt_username": "operator", "mqtt_password_env": "CALLBOOKER_MISSING_SECRET",
    }, client_factory=FakeClient)
    os.environ.pop("CALLBOOKER_MISSING_SECRET", None)
    ok &= check(
        "missing password environment variable is reported",
        "CALLBOOKER_MISSING_SECRET is not set" in missing_secret.start(),
    )
    disabled = mc.MqttPublisher({})
    ok &= check("MQTT is optional and off by default", disabled.start() == "" and not disabled.active)

    queue_client = FakeClient()
    queued = mc.MqttPublisher(
        {"mqtt_enabled": "yes", "mqtt_server": "x", "mqtt_topic": "results",
         "mqtt_queue_max": "2"},
        client_factory=lambda: queue_client,
    )
    queued.start()
    queued.publish({"sequence": 1})
    queued.publish({"sequence": 2})
    queued.publish({"sequence": 3})
    ok &= check("offline queue keeps newest results", [
        json.loads(body)["sequence"] for body in queued._pending
    ] == [2, 3])
    oversized = mc.MqttPublisher(
        {"mqtt_enabled": "yes", "mqtt_server": "x", "mqtt_topic": "results"},
        client_factory=FakeClient,
    )
    oversized.start()
    ok &= check(
        "oversized payload rejected without queueing",
        not oversized.publish({"data": "x" * mc.MAX_PAYLOAD_BYTES})
        and not oversized._pending
        and "exceeds" in oversized.error,
    )

    rows = [
        {"name": "Goran", "grid": "JN76HD", "state": "", "cqzone": "15", "country": "Slovenia"},
        {"name": "Goran", "grid": "JN76HD", "state": "", "cqzone": "15", "country": "Slovenia"},
        None,
    ]
    result = mc.lookup_payload(
        call="S55OO", mode="vhf", feed="vhfctest4win", frequency_mhz=None,
        cached=False, name="Goran", source_labels=("QRZ", "QRZCQ", "HamQTH"),
        sources=rows, values=["JN76HD", "JN76HD", None],
        published_at="2026-09-02T18:30:00Z",
    )
    ok &= check("payload has schema and lookup context", (
        result["schema_version"], result["callsign"], result["mode"],
        result["feed"], result["cached"], result["frequency_mhz"],
    ) == (1, "S55OO", "vhf", "vhfctest4win", False, None))
    ok &= check("source order and failures preserved", [
        (row["source"], row["value"], row["result"] is None)
        for row in result["sources"]
    ] == [
        ("QRZ", "JN76HD", False),
        ("QRZCQ", "JN76HD", False),
        ("HamQTH", None, True),
    ])
    ok &= check("summary reports agreement among real values", result["summary"] == {
        "name": "Goran",
        "values": ["JN76HD", "JN76HD", None],
        "agreement": True,
        "selected_value": "JN76HD",
    })
    ok &= check("UTC timestamp emitted", result["published_at"] == "2026-09-02T18:30:00Z")

    # Integration boundary: cache hits and the final live source publish once,
    # and stale generations cannot contaminate a newer lookup with old metadata.
    cb = import_engine()

    class FakeCache:
        def __init__(self, hit=None):
            self.hit = hit
            self.get_keys = []
            self.puts = []

        def get(self, key):
            self.get_keys.append(key)
            return self.hit

        def put(self, key, sources):
            self.puts.append((key, sources))

        def flush(self, force=False):
            pass

    context = {
        "mode": "vhf", "feed": "vhfctest4win", "frequency_mhz": None,
        "source_labels": ("QRZ", "QRZCQ"),
    }
    cached_app = cb.CallbookApp.__new__(cb.CallbookApp)
    cached_app.current = "S55OO"
    cached_app._lookup_generation = 7
    cached_app.cache = FakeCache(hit=rows[:2])
    cached_app._slots = []
    cached_renders = []
    cached_publishes = []
    cached_app._render_slots = lambda *args: cached_renders.append(args)
    cached_app._publish_lookup_result = lambda *args, **kwargs: cached_publishes.append((args, kwargs))
    cached_app._on_stable("S55OO", 7, context)
    ok &= check(
        "cached lookup publishes once with captured context",
        len(cached_publishes) == 1
        and cached_publishes[0][1] == {"cached": True, "context": context}
        and cached_app.cache.get_keys == ["S55OO|vhf|QRZ,QRZCQ"],
    )

    live_app = cb.CallbookApp.__new__(cb.CallbookApp)
    live_app.current = "S55OO"
    live_app._lookup_generation = 9
    live_app._active_lookup_generation = 9
    live_app._active_lookup_context = context
    live_app._slots = [rows[0], None]
    live_app._pending_inds = {1}
    live_app._inbox = [
        ("S55OO", 8, 1, {"grid": "WRONG"}),
        ("S55OO", 9, 1, rows[1]),
    ]
    live_app._v4w_inbox = []
    live_app._v4w_status = None
    live_app._precheck_inbox = []
    live_app.mqtt = types.SimpleNamespace(error="")
    live_app._mqtt_error_seen = ""
    live_app.cache = FakeCache()
    live_app.stop = threading.Event()
    live_app.stop.set()
    live_renders = []
    live_publishes = []
    live_app._render_slots = lambda *args: live_renders.append(args)
    live_app._publish_lookup_result = lambda *args, **kwargs: live_publishes.append((args, kwargs))
    live_app._poll_inbox()
    ok &= check(
        "final live source publishes once and stale generation is dropped",
        len(live_publishes) == 1
        and live_publishes[0][1] == {"cached": False, "context": context}
        and live_app._slots[1] == rows[1],
    )
    ok &= check(
        "live cache key preserves mode and source attribution",
        live_app.cache.puts[0][0] == "S55OO|vhf|QRZ,QRZCQ",
    )

    class FakeLabel:
        def __init__(self):
            self.texts = []

        def configure(self, **kwargs):
            self.texts.append(kwargs.get("text"))

    live_app.call_label = FakeLabel()
    live_app.mqtt.error = "MQTT publish failed: test"
    live_app._poll_inbox()
    live_app._poll_inbox()
    ok &= check(
        "new MQTT error is shown once beside current call",
        live_app.call_label.texts == ["S55OO · MQTT publish failed: test"],
    )
    live_app.mqtt.error = ""
    live_app._poll_inbox()
    ok &= check(
        "footer recovers after MQTT error clears",
        live_app.call_label.texts[-1] == "S55OO" and live_app._mqtt_error_seen == "",
    )

    import Callbooker as ckr
    feed_app = ckr.CallbookerApp.__new__(ckr.CallbookerApp)
    feed_app.local = {"127.0.0.1"}
    feed_app._last_mhz = None
    feed_app._result_feed = None
    feed_app._result_frequency_mhz = None
    feed_app._apply_mode = lambda vhf: setattr(feed_app, "tested_vhf", vhf)
    feed_app._handle_call = lambda call: setattr(feed_app, "tested_call", call)
    feed_app.on_packet(
        "127.0.0.1",
        b"<lookupinfo><call>S55OO</call><rxfreq>14430000</rxfreq></lookupinfo>",
    )
    ok &= check(
        "N1MM event captures feed, frequency, and VHF mode",
        (feed_app._result_feed, feed_app._result_frequency_mhz,
         feed_app.tested_vhf, feed_app.tested_call)
        == ("n1mm", 144.3, True, "S55OO"),
    )
    original_poll = cb.CallbookApp._poll_inbox
    cb.CallbookApp._poll_inbox = lambda self: None
    try:
        feed_app._v4w_inbox = ["S55OO"]
        feed_app._poll_inbox()
    finally:
        cb.CallbookApp._poll_inbox = original_poll
    ok &= check(
        "VHFCtest4WIN event captures feed and clears frequency",
        (feed_app._result_feed, feed_app._result_frequency_mhz, feed_app.tested_vhf)
        == ("vhfctest4win", None, True),
    )

    print("\nALL PASS" if ok else "\nSOME FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
