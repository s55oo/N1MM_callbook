# SPDX-License-Identifier: Unlicense
"""Optional MQTT output for completed Callbooker lookups."""

from collections import deque
from datetime import datetime, timezone
import json
import os
import secrets
import threading
import time

try:
    import paho.mqtt.client as mqtt
except ImportError:  # The app still works without Paho when MQTT is disabled.
    mqtt = None


_TRUE = ("yes", "true", "1", "on")
MAX_PAYLOAD_BYTES = 16384


def _enabled(value):
    return str(value or "").strip().lower() in _TRUE


def _integer(settings, key, default, minimum=None, maximum=None):
    raw = settings.get(key, default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ValueError("{} must be an integer".format(key))
    if minimum is not None and value < minimum:
        raise ValueError("{} must be at least {}".format(key, minimum))
    if maximum is not None and value > maximum:
        raise ValueError("{} must be at most {}".format(key, maximum))
    return value


def _client_id(settings):
    configured = settings.get("mqtt_client_id", "").strip()
    return configured or "callbooker-{}".format(secrets.token_hex(4))


def lookup_payload(call, mode, feed, frequency_mhz, cached, name,
                   source_labels, sources, values, published_at=None):
    """Build the stable, Tk-free schema-v1 document sent to MQTT."""
    real_values = [value for value in values if value]
    agree = len(real_values) >= 2 and len(set(real_values)) == 1
    rows = []
    for i, source in enumerate(sources):
        rows.append({
            "source": (
                source_labels[i]
                if i < len(source_labels)
                else "source_{}".format(i + 1)
            ),
            "value": values[i] if i < len(values) else None,
            "result": source,
        })
    return {
        "schema_version": 1,
        "published_at": published_at or datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "callsign": call,
        "mode": mode,
        "feed": feed,
        "frequency_mhz": frequency_mhz,
        "cached": bool(cached),
        "summary": {
            "name": name,
            "values": values,
            "agreement": agree,
            "selected_value": real_values[0] if agree else None,
        },
        "sources": rows,
    }


class MqttPublisher:
    """Long-lived, reconnecting Paho client used by the Tk GUI thread.

    Paho owns its network thread. ``publish`` therefore returns quickly and
    broker outages never delay callsign lookup or repainting.
    """

    def __init__(self, settings, config_dir="", client_factory=None):
        self.settings = settings or {}
        self.config_dir = config_dir
        self.client_factory = client_factory
        self.client = None
        self.active = False
        self.connected = False
        self.error = ""
        self._lock = threading.Lock()
        self._pending = deque()
        self._inflight = []
        self.queue_max = 100

    @property
    def enabled(self):
        return _enabled(self.settings.get("mqtt_enabled", "no"))

    def start(self):
        """Start the background MQTT network loop; return an error string."""
        if not self.enabled:
            return ""
        if mqtt is None and self.client_factory is None:
            self.error = "MQTT disabled: install paho-mqtt"
            return self.error

        try:
            host = self.settings.get("mqtt_server", "").strip()
            topic = self.settings.get("mqtt_topic", "").strip()
            if not host:
                raise ValueError("mqtt_server is required")
            if not topic or "+" in topic or "#" in topic:
                raise ValueError("mqtt_topic must be a concrete publish topic")

            tls = _enabled(self.settings.get("mqtt_tls", "no"))
            port = _integer(
                self.settings, "mqtt_port", 8883 if tls else 1883, 1, 65535
            )
            self.qos = _integer(self.settings, "mqtt_qos", 1, 0, 2)
            self.keepalive = _integer(
                self.settings, "mqtt_keepalive", 60, 1, 65535
            )
            self.queue_max = _integer(
                self.settings, "mqtt_queue_max", 100, 1, 1000
            )
            reconnect_min = _integer(
                self.settings, "mqtt_reconnect_min", 1, 1, 3600
            )
            reconnect_max = _integer(
                self.settings, "mqtt_reconnect_max", 30, reconnect_min, 86400
            )
            self.topic = topic
            self.retain = _enabled(self.settings.get("mqtt_retain", "no"))

            if self.client_factory is not None:
                client = self.client_factory()
            else:
                client = mqtt.Client(
                    mqtt.CallbackAPIVersion.VERSION2,
                    client_id=_client_id(self.settings),
                    protocol=mqtt.MQTTv311,
                )

            username = self.settings.get("mqtt_username", "").strip()
            if username:
                password = self.settings.get("mqtt_password", "")
                password_env = self.settings.get("mqtt_password_env", "").strip()
                if password_env:
                    if password_env not in os.environ:
                        raise ValueError(
                            "environment variable {} is not set".format(password_env)
                        )
                    password = os.environ[password_env]
                client.username_pw_set(
                    username, password
                )
            if tls:
                ca_certs = self.settings.get("mqtt_ca_certs", "").strip() or None
                if ca_certs and not os.path.isabs(ca_certs):
                    ca_certs = os.path.abspath(os.path.join(self.config_dir, ca_certs))
                client.tls_set(ca_certs=ca_certs)
                client.tls_insecure_set(
                    _enabled(self.settings.get("mqtt_tls_insecure", "no"))
                )
            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.max_queued_messages_set(self.queue_max)
            client.reconnect_delay_set(min_delay=reconnect_min, max_delay=reconnect_max)
            client.connect_async(host, port, self.keepalive)
            # Assign before the network thread can deliver on_connect and
            # flush results queued during application startup.
            self.client = client
            client.loop_start()
            self.active = True
        except Exception as exc:
            self.error = "MQTT disabled: {}".format(exc)
        return self.error

    def _on_connect(self, _client, _userdata, _flags, reason_code, _properties):
        code = getattr(reason_code, "value", reason_code)
        self.connected = code == 0
        if self.connected:
            self.error = ""
            self._flush_pending()
        else:
            self.error = "MQTT connection rejected: {}".format(reason_code)

    def _on_disconnect(self, _client, _userdata, _flags, _reason_code, _properties):
        self.connected = False

    def _queue(self, body, front=False):
        with self._lock:
            if len(self._pending) >= self.queue_max:
                self._pending.popleft()
                self.error = "MQTT queue full: oldest result dropped"
            if front:
                self._pending.appendleft(body)
            else:
                self._pending.append(body)

    def _send(self, body):
        try:
            info = self.client.publish(
                self.topic, body, qos=self.qos, retain=self.retain
            )
        except Exception as exc:
            self.error = "MQTT publish failed: {}".format(exc)
            return False
        rc = getattr(info, "rc", 0)
        if rc == 0:
            self.error = ""
            if self.qos:
                self._track_inflight(info)
            return True
        # Paho queues QoS 1/2 internally if the socket vanished between our
        # connected check and publish(). QoS 0 needs our own retry queue.
        no_conn = getattr(mqtt, "MQTT_ERR_NO_CONN", 4) if mqtt else 4
        if rc == no_conn and self.qos:
            self._track_inflight(info)
            return True
        self.error = "MQTT publish failed: client returned {}".format(rc)
        return False

    def _track_inflight(self, info):
        """Keep only QoS acknowledgements that are still outstanding."""
        with self._lock:
            self._inflight = [
                old for old in self._inflight
                if not getattr(old, "is_published", lambda: False)()
            ]
            if not getattr(info, "is_published", lambda: False)():
                self._inflight.append(info)

    def _flush_pending(self):
        while self.connected:
            with self._lock:
                if not self._pending:
                    return
                body = self._pending.popleft()
            if not self._send(body):
                self._queue(body, front=True)
                return

    def publish(self, payload):
        """Queue one JSON document. Returns False when MQTT is inactive."""
        if not self.active or self.client is None:
            return False
        try:
            body = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            )
            if len(body.encode("utf-8")) > MAX_PAYLOAD_BYTES:
                raise ValueError("MQTT payload exceeds {} bytes".format(MAX_PAYLOAD_BYTES))
            if not self.connected:
                self._queue(body)
                return True
            if self._send(body):
                return True
            self._queue(body)
            return False
        except Exception as exc:
            self.error = "MQTT publish failed: {}".format(exc)
            return False

    def close(self):
        if self.client is None:
            return
        # Give accepted QoS 1/2 messages a short, bounded chance to receive
        # their broker acknowledgement before tearing down the network loop.
        deadline = time.monotonic() + 1.0
        with self._lock:
            inflight = list(self._inflight)
        for info in inflight:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                info.wait_for_publish(timeout=remaining)
            except Exception:
                break
        try:
            self.client.disconnect()
        except Exception:
            pass
        try:
            self.client.loop_stop()
        except Exception:
            pass
        self.active = False
        self.connected = False
