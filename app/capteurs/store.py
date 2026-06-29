import os
from contextlib import contextmanager
from datetime import datetime, timezone

from pymongo import MongoClient

MONGO_ADDRESS = os.environ.get("MONGO_ADDRESS")
DB_NAME = "capteurs"

NUMERIC_FIELDS = {
    "temperature", "humidity", "battery", "linkquality",
    "pressure", "voltage", "current", "power", "energy",
    "intensity", "analog_output_10", "illuminance", "co2",
}


def ensure_indexes():
    with connect_mongo() as client:
        client[DB_NAME].metrics.create_index(
            [("device", 1), ("field", 1), ("date", -1)],
            background=True,
        )


@contextmanager
def connect_mongo():
    with MongoClient(MONGO_ADDRESS) as client:
        yield client


def save_device_state(device: str, payload: dict):
    now = datetime.now(timezone.utc)
    metrics = []
    for field, value in payload.items():
        if field in ("update", "last_seen"):
            continue
        metrics.append({
            "date": now,
            "device": device,
            "field": field,
            "value": value,
        })

    with connect_mongo() as client:
        db = client[DB_NAME]
        if metrics:
            db.metrics.insert_many(metrics)
        db.devices.update_one(
            {"_id": device},
            {"$set": {"state": payload, "last_seen": now, "source": "zigbee2mqtt"}},
            upsert=True,
        )


def merge_device_state(
    device: str,
    field_updates: dict,
    device_meta: dict | None = None,
    *,
    only_if_changed: bool = False,
    record_metrics: bool = True,
    seen_at: datetime | None = None,
):
    now = datetime.now(timezone.utc)
    metric_when = seen_at or now

    if only_if_changed and field_updates:
        with connect_mongo() as client:
            doc = client[DB_NAME].devices.find_one({"_id": device}, {"state": 1})
        current = (doc or {}).get("state", {})
        new_sample = field_updates.get("sample_time")
        old_sample = current.get("sample_time")
        if new_sample and new_sample != old_sample:
            pass
        else:
            field_updates = {
                field: value
                for field, value in field_updates.items()
                if current.get(field) != value
            }

    if not field_updates and not device_meta:
        return

    metrics = []
    if record_metrics:
        for field, value in field_updates.items():
            if field not in NUMERIC_FIELDS:
                continue
            metrics.append({
                "date": metric_when,
                "device": device,
                "field": field,
                "value": value,
            })

    update = {
        **{f"state.{field}": value for field, value in field_updates.items()},
    }
    if field_updates:
        update["last_seen"] = metric_when
    if device_meta:
        update.update(device_meta)

    with connect_mongo() as client:
        db = client[DB_NAME]
        if metrics:
            db.metrics.insert_many(metrics)
        db.devices.update_one({"_id": device}, {"$set": update}, upsert=True)


def load_metric_history(
    client,
    device: str,
    field: str,
    since: datetime,
    *,
    db_name: str = DB_NAME,
    max_points: int = 300,
) -> list[dict]:
    query = {"device": device, "field": field, "date": {"$gte": since}}
    projection = {"date": 1, "value": 1, "_id": 0}
    db = client[db_name]
    total = db.metrics.count_documents(query)
    if total <= max_points:
        return list(db.metrics.find(query, projection).sort("date", 1))

    step = max(1, total // max_points)
    docs: list[dict] = []
    for index, doc in enumerate(db.metrics.find(query, projection).sort("date", 1)):
        if index % step == 0:
            docs.append(doc)
    latest = db.metrics.find_one(query, projection, sort=[("date", -1)])
    if latest and (not docs or docs[-1]["date"] != latest["date"]):
        docs.append(latest)
    return docs


def replace_device_metrics(device: str, metrics: list[dict]):
    with connect_mongo() as client:
        db = client[DB_NAME]
        db.metrics.delete_many({"device": device})
        batch_size = 2000
        for offset in range(0, len(metrics), batch_size):
            db.metrics.insert_many(metrics[offset:offset + batch_size])


def upsert_device_snapshot(
    device: str,
    state: dict | None = None,
    device_meta: dict | None = None,
    *,
    last_seen: datetime | None = None,
):
    update = {}
    if state:
        update.update({f"state.{field}": value for field, value in state.items()})
    if device_meta:
        update.update(device_meta)
    if last_seen is not None:
        update["last_seen"] = last_seen
    elif state:
        update["last_seen"] = datetime.now(timezone.utc)
    if not update:
        return

    with connect_mongo() as client:
        client[DB_NAME].devices.update_one({"_id": device}, {"$set": update}, upsert=True)
