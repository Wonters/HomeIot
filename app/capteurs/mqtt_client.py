import json
import logging
import os
import threading
from datetime import datetime, timezone

import paho.mqtt.client as mqtt

from .store import merge_device_state, save_device_state
from .xsense_cloud import is_enabled as xsense_cloud_enabled

logger = logging.getLogger(__name__)

MQTT_HOST = os.environ.get("MQTT_HOST", "core-mosquitto")
MQTT_PORT = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER = os.environ.get("MQTT_USER", "mqtt-user")
MQTT_PASSWORD = os.environ.get("MQTT_PASSWORD", "mqtt")
MQTT_TOPIC_PREFIX = os.environ.get("MQTT_TOPIC_PREFIX", "zigbee2mqtt")
XSENSE_ENABLED = os.environ.get("MQTT_XSENSE_ENABLED", "true").lower() in ("1", "true", "yes")

_client: mqtt.Client | None = None
_thread: threading.Thread | None = None
_connected = False
_last_message: datetime | None = None
_lock = threading.Lock()


def is_connected() -> bool:
    return _connected


def last_message_time() -> datetime | None:
    return _last_message


def _on_connect(client, userdata, flags, reason_code, properties=None):
    global _connected
    if reason_code != 0:
        logger.error("MQTT connection failed: %s", reason_code)
        _connected = False
        return
    _connected = True
    client.subscribe(f"{MQTT_TOPIC_PREFIX}/+")
    client.subscribe(f"{MQTT_TOPIC_PREFIX}/bridge/#")
    if XSENSE_ENABLED:
        client.subscribe("homeassistant/+/+/+/state")
        client.subscribe("homeassistant/+/+/+/config")
    logger.info(
        "MQTT connected, subscribed to %s/+/+",
        MQTT_TOPIC_PREFIX,
    )
    if XSENSE_ENABLED:
        logger.info("MQTT subscribed to homeassistant X-Sense topics")


def _on_disconnect(client, userdata, flags, reason_code, properties=None):
    global _connected
    _connected = False
    logger.warning("MQTT disconnected: %s", reason_code)


NUMERIC_XSENSE_FIELDS = {
    "temperature", "humidity", "temp", "battery", "rssi", "wifi_signal",
}

TEMPERATURE_MODELS = {"STH51", "STH0A", "STH0B"}

_entity_config: dict[str, dict] = {}


def _normalize_xsense_field(field: str, device_class: str | None = None) -> str:
    if device_class in ("temperature", "humidity", "battery"):
        return device_class
    field = field.removeprefix("measure_")
    if field == "temp":
        return "temperature"
    return field


def _coerce_xsense_value(field: str, value):
    if field in NUMERIC_XSENSE_FIELDS or field.startswith("measure_"):
        try:
            return float(value)
        except (TypeError, ValueError):
            pass
    return value


def _extract_xsense_value(payload: dict, field: str, device_class: str | None = None) -> object | None:
    aliases = {
        "temperature": ("temperature", "temp", "measure_temperature"),
        "humidity": ("humidity", "measure_humidity"),
        "temp": ("temperature", "temp", "measure_temperature"),
    }

    for key in aliases.get(field, (field,)):
        if key in payload:
            return _coerce_xsense_value(field, payload[key])

    if "status" in payload:
        return _coerce_xsense_value(field, payload["status"])

    if device_class in payload:
        return _coerce_xsense_value(device_class, payload[device_class])

    if len(payload) == 1:
        return _coerce_xsense_value(field, next(iter(payload.values())))

    return None


def _handle_zigbee2mqtt_message(topic: str, payload: dict):
    prefix = f"{MQTT_TOPIC_PREFIX}/"
    suffix = topic[len(prefix):]
    if suffix.endswith("/set") or suffix.endswith("/get"):
        return
    if suffix.startswith("bridge/"):
        return

    device = suffix
    save_device_state(device, payload)
    logger.debug("Saved state for %s: %s", device, payload)


def _skip_sth51_mqtt(model: str | None) -> bool:
    return xsense_cloud_enabled() and model in TEMPERATURE_MODELS


def _handle_xsense_state(topic: str, payload: dict):
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != "homeassistant" or parts[-1] != "state":
        return

    device_id = parts[2]
    entity_id = parts[3]
    prefix = f"{device_id}_"
    if not entity_id.startswith(prefix):
        return

    entity_cfg = _entity_config.get(entity_id, {})
    if _skip_sth51_mqtt(entity_cfg.get("model")):
        return

    raw_field = entity_id[len(prefix):]
    device_class = entity_cfg.get("device_class")
    field = _normalize_xsense_field(raw_field, device_class)
    value = _extract_xsense_value(payload, raw_field, device_class)
    if value is None:
        logger.debug("Unhandled X-Sense payload on %s: %s", topic, payload)
        return

    merge_device_state(device_id, {field: value}, {"source": "xsense"})
    logger.debug("Saved X-Sense state for %s.%s: %s", device_id, field, value)


def _handle_xsense_config(topic: str, payload: dict):
    parts = topic.split("/")
    if len(parts) != 5 or parts[0] != "homeassistant" or parts[-1] != "config":
        return

    device_id = parts[2]
    entity_id = parts[3]
    _entity_config[entity_id] = {
        "device_class": payload.get("device_class"),
        "name": payload.get("name"),
        "model": payload.get("model"),
    }

    device_info = payload.get("device")
    if not isinstance(device_info, dict):
        return

    model = payload.get("model") or device_info.get("model")
    if _skip_sth51_mqtt(model):
        return

    meta = {"source": "xsense"}
    if name := device_info.get("name"):
        meta["friendly_name"] = name
    if model := device_info.get("model"):
        meta["model"] = model
    if manufacturer := device_info.get("manufacturer"):
        meta["manufacturer"] = manufacturer
    if area := payload.get("suggested_area") or device_info.get("suggested_area"):
        meta["location"] = area

    merge_device_state(device_id, {}, meta)
    logger.debug("Saved X-Sense metadata for %s", device_id)


def _on_message(client, userdata, msg):
    global _last_message
    topic = msg.topic

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        if topic.startswith("homeassistant/") or topic.startswith(f"{MQTT_TOPIC_PREFIX}/"):
            logger.warning("Invalid JSON on %s", topic)
        return

    if not isinstance(payload, dict):
        return

    with _lock:
        _last_message = datetime.now(timezone.utc)

    if topic.startswith("homeassistant/"):
        if topic.endswith("/state"):
            _handle_xsense_state(topic, payload)
        elif topic.endswith("/config"):
            _handle_xsense_config(topic, payload)
        return

    prefix = f"{MQTT_TOPIC_PREFIX}/"
    if not topic.startswith(prefix):
        return

    _handle_zigbee2mqtt_message(topic, payload)


def publish_command(device: str, command: dict) -> bool:
    if _client is None or not _connected:
        return False
    topic = f"{MQTT_TOPIC_PREFIX}/{device}/set"
    payload = json.dumps(command)
    result = _client.publish(topic, payload, qos=1)
    result.wait_for_publish(timeout=5)
    return result.rc == mqtt.MQTT_ERR_SUCCESS


def _run_client():
    global _client
    _client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USER:
        _client.username_pw_set(MQTT_USER, MQTT_PASSWORD or None)
    _client.on_connect = _on_connect
    _client.on_disconnect = _on_disconnect
    _client.on_message = _on_message
    _client.reconnect_delay_set(min_delay=1, max_delay=30)
    _client.connect_async(MQTT_HOST, MQTT_PORT, keepalive=60)
    _client.loop_forever()


def start_mqtt():
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _thread = threading.Thread(target=_run_client, daemon=True, name="mqtt-client")
    _thread.start()
    logger.info("MQTT client thread started (%s:%s)", MQTT_HOST, MQTT_PORT)


def stop_mqtt():
    global _client
    if _client is not None:
        _client.disconnect()
        _client.loop_stop()
