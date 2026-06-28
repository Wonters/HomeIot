import os
from contextlib import contextmanager
from datetime import datetime, timezone

from pymongo import MongoClient

MONGO_ADDRESS = os.environ.get("MONGO_ADDRESS")
CONFIG_DB = "config"
MACRO_COL = "macro"


@contextmanager
def connect_mongo():
    with MongoClient(MONGO_ADDRESS) as client:
        yield client


def get_macro(key: str, defaults: dict | None = None) -> dict:
    defaults = defaults or {}
    with connect_mongo() as client:
        doc = client[CONFIG_DB][MACRO_COL].find_one({"_id": key})
    if not doc:
        return dict(defaults)
    merged = dict(defaults)
    for field, value in doc.items():
        if field != "_id":
            merged[field] = value
    return merged


def set_macro(key: str, values: dict) -> dict:
    payload = {**values, "updated_at": datetime.now(timezone.utc)}
    with connect_mongo() as client:
        client[CONFIG_DB][MACRO_COL].update_one(
            {"_id": key},
            {"$set": payload},
            upsert=True,
        )
    return get_macro(key)
