import json
from datetime import datetime, timezone

from fastapi import APIRouter
from fastapi.responses import Response
from pymongo.collection import ObjectId

from capteurs.store import connect_mongo as connect_capteurs_mongo
from capteurs.xsense_devices import (
    device_measurement_time,
    find_kitchen_device,
    find_saas_device,
)
from vmc.domeo import connect_mongo as connect_vmc_mongo

router = APIRouter()

VMC_TIMP = "TEMPERATURE Timp"
VMC_TINT = "TEMPERATURE Tint"
VMC_AIRFLOW = "CURRENT AIRFLOW"


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


def _as_utc(dt):
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = datetime.fromisoformat(dt.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _device_label(device: dict) -> str:
    device_id = device["_id"]
    label = device.get("friendly_name") or device_id
    location = device.get("location")
    if location:
        label = f"{label} ({location})"
    return label


def _xsense_temperature(client, device: dict | None) -> dict | None:
    if not device:
        return None

    device_id = device["_id"]
    state = device.get("state") or {}
    metric = client.capteurs.metrics.find_one(
        {"device": device_id, "field": "temperature"},
        sort=[("date", -1)],
    )
    state_date = device_measurement_time(device)
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

    if value is None:
        return None

    return {
        "label": _device_label(device),
        "value": value,
        "date": meas_date,
        "battery": state.get("battery"),
    }


@router.get("/summary")
def home_summary():
    result = {
        "vmc": {
            "airflow": None,
            "modes": None,
            "timp": None,
            "tint": None,
            "last_update": None,
        },
        "maison": {
            "actuelle": None,
            "exterieur": None,
            "interieur": None,
        },
    }

    with connect_vmc_mongo() as client:
        pipeline = [
            {"$sort": {"date": -1}},
            {"$group": {
                "_id": "$name",
                "value": {"$first": "$value"},
                "register": {"$first": "$register"},
                "date": {"$first": "$date"},
            }},
        ]
        metrics = {
            doc["_id"]: doc
            for doc in client.domeo210.metrics.aggregate(pipeline)
        }

        last = client.domeo210.metrics.find_one(sort=[("date", -1)])
        modes = client.domeo210.status.find_one(sort=[("date", -1)])

        if last:
            result["vmc"]["last_update"] = last["date"]

        airflow = metrics.get(VMC_AIRFLOW)
        if airflow:
            result["vmc"]["airflow"] = {
                "value": airflow["value"],
                "unit": "m³/h",
                "date": airflow["date"],
            }

        for key, name in (("timp", VMC_TIMP), ("tint", VMC_TINT)):
            metric = metrics.get(name)
            if metric:
                result["vmc"][key] = {
                    "value": metric["value"],
                    "unit": "°C",
                    "date": metric["date"],
                }

        if modes:
            result["vmc"]["modes"] = {
                "standby": modes.get("standby"),
                "bypass": modes.get("bypass"),
                "boost": modes.get("boost"),
            }

    with connect_capteurs_mongo() as client:
        devices = list(client.capteurs.devices.find({"source": "xsense-cloud"}))
        saas = _xsense_temperature(client, find_saas_device(devices))
        kitchen = _xsense_temperature(client, find_kitchen_device(devices))

        if saas:
            result["maison"]["exterieur"] = saas
        if kitchen:
            result["maison"]["interieur"] = kitchen
            result["maison"]["actuelle"] = kitchen

    return _json_response(result)
