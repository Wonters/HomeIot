import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, Response
from pymongo.collection import ObjectId

from capteurs.store import connect_mongo as connect_capteurs_mongo, load_metric_history
from capteurs.xsense_devices import device_measurement_time, find_saas_device
from nav import inject_app_nav
from vmc.domeo import connect_mongo as connect_vmc_mongo

DASHBOARD_HTML = inject_app_nav(
    (Path(__file__).parent / "dashboard.html").read_text(),
    "Température extérieur",
)

router = APIRouter()

VMC_TOUT_NAME = "TEMPERATURE Tout"
MAX_POINTS = 300

VMC_TOUT_COLOR = "#73bf69"
XSENSE_SAAS_COLOR = "#ff9830"


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


def _since(period: str) -> datetime:
    now = datetime.utcnow()
    if period == "year":
        return now - timedelta(days=365)
    if period == "month":
        return now - timedelta(days=30)
    return now - timedelta(days=1)


def _downsample(docs: list[dict]) -> list[dict]:
    if len(docs) <= MAX_POINTS:
        return docs
    step = max(1, len(docs) // MAX_POINTS)
    sampled = docs[::step]
    if sampled[-1] is not docs[-1]:
        sampled.append(docs[-1])
    return sampled


def _points(docs: list[dict]) -> list[dict]:
    return [{"t": d["date"], "v": d["value"]} for d in docs]


def _device_label(device: dict) -> str:
    device_id = device["_id"]
    label = device.get("friendly_name") or device_id
    location = device.get("location")
    if location:
        label = f"{label} ({location})"
    return label


@router.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@router.get("/temperatures")
def get_comparison_temperatures(period: str = "day"):
    since = _since(period)

    with connect_vmc_mongo() as client:
        tout_docs = list(client.domeo210.metrics.find(
            {"name": VMC_TOUT_NAME, "date": {"$gte": since}},
            {"date": 1, "value": 1, "_id": 0},
        ).sort("date", 1))

    xsense_saas = {"label": "X-Sense SAAS", "points": []}
    with connect_capteurs_mongo() as client:
        devices = list(client.capteurs.devices.find({"source": "xsense-cloud"}))
        saas_device = find_saas_device(devices)
        if saas_device:
            device_id = saas_device["_id"]
            xsense_saas["label"] = _device_label(saas_device)
            docs = load_metric_history(
                client,
                device_id,
                "temperature",
                since,
                max_points=MAX_POINTS,
            )
            xsense_saas["points"] = _points(docs)

    return _json_response({
        "period": period,
        "vmc_tout": {
            "label": "VMC Tout (extérieur)",
            "points": _points(_downsample(tout_docs)),
        },
        "xsense_saas": xsense_saas,
        "colors": {
            "vmc_tout": VMC_TOUT_COLOR,
            "xsense_saas": XSENSE_SAAS_COLOR,
        },
    })


def _as_utc(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@router.get("/latest")
def get_latest_values():
    result = {"vmc_tout": None, "xsense_saas": None}

    with connect_vmc_mongo() as client:
        doc = client.domeo210.metrics.find_one(
            {"name": VMC_TOUT_NAME},
            sort=[("date", -1)],
        )
        if doc:
            result["vmc_tout"] = {
                "value": doc["value"],
                "date": doc["date"],
            }

    with connect_capteurs_mongo() as client:
        devices = list(client.capteurs.devices.find({"source": "xsense-cloud"}))
        saas_device = find_saas_device(devices)
        if saas_device:
            device_id = saas_device["_id"]
            state = saas_device.get("state") or {}
            metric = client.capteurs.metrics.find_one(
                {"device": device_id, "field": "temperature"},
                sort=[("date", -1)],
            )
            state_date = device_measurement_time(saas_device)
            if state_date:
                state_date = _as_utc(state_date)
            state_value = state.get("temperature")

            value = state_value
            meas_date = state_date
            if metric:
                metric_date = _as_utc(metric["date"])
                if meas_date is None or metric_date > meas_date:
                    value = metric["value"]
                    meas_date = metric_date

            if value is not None:
                result["xsense_saas"] = {
                    "label": _device_label(saas_device),
                    "value": value,
                    "date": meas_date,
                    "battery": state.get("battery"),
                    "cloud_sync_at": saas_device.get("cloud_sync_at"),
                }

    return _json_response(result)
