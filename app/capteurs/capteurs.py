import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pymongo.collection import ObjectId

from nav import inject_app_nav
from .mqtt_client import is_connected, last_message_time, publish_command
from .xsense_cloud import (
    device_count as xsense_device_count,
    history_reset_status,
    is_connected as xsense_connected,
    is_enabled as xsense_enabled,
    last_error as xsense_last_error,
    last_sync_time as xsense_last_sync,
    start_history_reset,
)
from .store import connect_mongo

DASHBOARD_PATH = Path(__file__).parent / "dashboard.html"


def _dashboard_html() -> str:
    return inject_app_nav(DASHBOARD_PATH.read_text(), "Capteurs")

router = APIRouter()

FIELD_UNITS = {
    "temperature": "°C",
    "humidity": "%",
    "battery": "%",
    "pressure": "hPa",
    "voltage": "V",
    "current": "A",
    "power": "W",
    "energy": "kWh",
    "illuminance": "lx",
    "co2": "ppm",
}

CONTROLLABLE_FIELDS = {"state", "state_relay"}
XSENSE_SOURCES = {"xsense", "xsense-cloud"}
ZIGBEE_SOURCE = "zigbee2mqtt"
STH51_MODELS = {"STH51", "STH0A", "STH0B"}


def _normalize_station_sn(sn: str | None) -> str:
    if not sn:
        return ""
    s = sn.upper()
    if s.startswith("SBS50"):
        return s[5:]
    if s.startswith("SBS"):
        return s[3:]
    return s


def _sth51_slot(name: str) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    n = re.sub(r"[^a-z0-9]+", " ", n).strip()
    if "hygrom" not in n:
        return name
    m = re.search(r"\b(\d+)\s*$", n)
    return m.group(1) if m else "1"


def _sth51_score(doc: dict) -> tuple:
    state = doc.get("state") or {}
    last_seen = doc.get("last_seen")
    if isinstance(last_seen, str):
        last_seen = datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
    if last_seen is None:
        last_seen = datetime.min.replace(tzinfo=timezone.utc)
    device_sn = doc.get("device_sn") or doc.get("name", "").rsplit("_", 1)[-1]
    try:
        serial_rank = -int(device_sn, 16)
    except ValueError:
        serial_rank = 0
    return (
        doc.get("source") == "xsense-cloud",
        state.get("online") is True,
        last_seen,
        serial_rank,
    )


def _dedupe_sth51_devices(devices: list[dict]) -> list[dict]:
    kept: list[dict] = []
    best_by_sn: dict[str, dict] = {}

    for doc in devices:
        if doc.get("model") not in STH51_MODELS:
            kept.append(doc)
            continue

        device_sn = doc.get("device_sn") or doc.get("name", "").rsplit("_", 1)[-1]
        prev = best_by_sn.get(device_sn)
        if prev is None or _sth51_score(doc) > _sth51_score(prev):
            best_by_sn[device_sn] = doc

    return kept + list(best_by_sn.values())


def _filter_devices(devices: list[dict]) -> list[dict]:
    if xsense_enabled():
        devices = [
            d for d in devices
            if not (d.get("source") == "xsense" and d.get("model") in STH51_MODELS)
        ]
    return _dedupe_sth51_devices(devices)


def _device_protocol(doc: dict) -> str:
    source = doc.get("source")
    if source in XSENSE_SOURCES:
        return "lora"
    if source == ZIGBEE_SOURCE:
        return "zigbee"
    manufacturer = (doc.get("manufacturer") or "").upper()
    if manufacturer.startswith("X-SENSE"):
        return "lora"
    return "zigbee"


class MongoEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value.strftime("%Y-%m-%dT%H:%M:%SZ")
        return super().default(value)


def _json_response(data):
    return Response(
        media_type="application/json",
        content=json.dumps(data, cls=MongoEncoder),
    )


@router.get("/", response_class=HTMLResponse)
def dashboard():
    return _dashboard_html()


@router.get("/devices")
def list_devices():
    with connect_mongo() as client:
        devices = list(client.capteurs.devices.find())
    for d in devices:
        d["name"] = d.pop("_id")
        d["display_name"] = d.get("friendly_name") or d["name"]
        d["protocol"] = _device_protocol(d)
    devices = _filter_devices(devices)
    return _json_response(devices)


@router.get("/metrics/latest")
def get_latest_metrics():
    with connect_mongo() as client:
        pipeline = [
            {"$sort": {"date": -1}},
            {"$group": {
                "_id": {"device": "$device", "field": "$field"},
                "value": {"$first": "$value"},
                "date": {"$first": "$date"},
            }},
        ]
        result = {}
        for doc in client.capteurs.metrics.aggregate(pipeline):
            device = doc["_id"]["device"]
            field = doc["_id"]["field"]
            result.setdefault(device, {})[field] = {
                "value": doc["value"],
                "date": doc["date"],
                "unit": FIELD_UNITS.get(field, ""),
            }
        return _json_response(result)


@router.get("/metrics")
def get_metrics(device: str = "", field: str = ""):
    query = {}
    if device:
        query["device"] = device
    if field:
        query["field"] = field
    with connect_mongo() as client:
        docs = list(client.capteurs.metrics.find(query).sort("date", 1))
    return _json_response(docs)


def _load_metric_history(client, device: str, field: str, since: datetime, max_points: int = 300) -> list[dict]:
    query = {"device": device, "field": field, "date": {"$gte": since}}
    projection = {"date": 1, "value": 1, "_id": 0}
    total = client.capteurs.metrics.count_documents(query)
    if total <= max_points:
        return list(client.capteurs.metrics.find(query, projection).sort("date", 1))

    step = max(1, total // max_points)
    docs: list[dict] = []
    for index, doc in enumerate(client.capteurs.metrics.find(query, projection).sort("date", 1)):
        if index % step == 0:
            docs.append(doc)
    latest = client.capteurs.metrics.find_one(
        query,
        projection,
        sort=[("date", -1)],
    )
    if latest and (not docs or docs[-1]["date"] != latest["date"]):
        docs.append(latest)
    return docs


@router.get("/metrics/history")
def get_metric_history(
    device: str,
    field: str,
    period: str = "day",
):
    now = datetime.now(timezone.utc)
    if period == "year":
        since = now - timedelta(days=365)
    elif period == "month":
        since = now - timedelta(days=30)
    else:
        since = now - timedelta(days=1)

    with connect_mongo() as client:
        docs = _load_metric_history(client, device, field, since)

    points = [{"t": d["date"], "v": d["value"]} for d in docs]
    return _json_response(points)


@router.post("/set/{device}")
def set_device_state(device: str, body: dict):
    if not body:
        raise HTTPException(400, "Corps de requête vide")
    if not publish_command(device, body):
        raise HTTPException(503, "MQTT non connecté")
    return {"ok": True, "device": device, "command": body}


@router.get("/set/{device}")
def set_device_state_get(
    device: str,
    state: str = Query(default=""),
    field: str = Query(default="state"),
):
    if field not in CONTROLLABLE_FIELDS:
        raise HTTPException(400, f"Champ non contrôlable: {field}")
    value = state.upper()
    if value not in ("ON", "OFF", "TOGGLE"):
        raise HTTPException(400, "state doit être ON, OFF ou TOGGLE")

    if value == "TOGGLE":
        with connect_mongo() as client:
            doc = client.capteurs.devices.find_one({"_id": device})
        if not doc:
            raise HTTPException(404, f"Appareil inconnu: {device}")
        current = doc.get("state", {}).get(field, "OFF")
        value = "OFF" if str(current).upper() == "ON" else "ON"

    if not publish_command(device, {field: value}):
        raise HTTPException(503, "MQTT non connecté")
    return {"ok": True, "device": device, "field": field, "value": value}


@router.get("/status")
def get_status():
    return _json_response({
        "mqtt_connected": is_connected(),
        "last_message": last_message_time(),
        "xsense_cloud": {
            "enabled": xsense_enabled(),
            "connected": xsense_connected(),
            "last_sync": xsense_last_sync(),
            "device_count": xsense_device_count(),
            "error": xsense_last_error(),
            "reset": history_reset_status(),
        },
    })


@router.post("/xsense/reset-history")
def reset_xsense_history():
    ok, message = start_history_reset()
    if not ok:
        raise HTTPException(400, message)
    return {"ok": True, "message": message}


@router.get("/xsense/reset-history/status")
def xsense_reset_history_status():
    return _json_response(history_reset_status())


@router.get("/metrics/drop")
def drop_metrics():
    with connect_mongo() as client:
        client.capteurs.metrics.drop()
        client.capteurs.devices.drop()
