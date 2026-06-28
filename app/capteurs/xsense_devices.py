import os
import re
from datetime import datetime, timezone

XSENSE_CLOUD_SOURCE = "xsense-cloud"
XSENSE_SAAS_DEVICE = os.environ.get("XSENSE_SAAS_DEVICE", "")
XSENSE_KITCHEN_DEVICE = os.environ.get("XSENSE_KITCHEN_DEVICE", "")


def parse_sample_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _is_saas_device(device: dict) -> bool:
    if device.get("source") != XSENSE_CLOUD_SOURCE:
        return False
    if XSENSE_SAAS_DEVICE and device["_id"] == XSENSE_SAAS_DEVICE:
        return True
    name = (device.get("friendly_name") or "").lower()
    return bool(re.search(r"saas", name))


def _is_kitchen_device(device: dict) -> bool:
    if device.get("source") != XSENSE_CLOUD_SOURCE:
        return False
    if XSENSE_KITCHEN_DEVICE and device["_id"] == XSENSE_KITCHEN_DEVICE:
        return True
    location = (device.get("location") or "").lower()
    name = (device.get("friendly_name") or "").lower()
    return "kitchen" in location or "kitchen" in name


def find_saas_device(devices: list[dict]) -> dict | None:
    for device in devices:
        if _is_saas_device(device):
            return device
    return None


def find_kitchen_device(devices: list[dict]) -> dict | None:
    for device in devices:
        if _is_kitchen_device(device):
            return device
    return None


def device_temperature(device: dict | None) -> float | None:
    if not device:
        return None
    state = device.get("state") or {}
    temp = state.get("temperature")
    if isinstance(temp, (int, float)):
        return float(temp)
    return None


def device_measurement_time(device: dict | None) -> datetime | None:
    if not device:
        return None
    state = device.get("state") or {}
    if sample_at := parse_sample_time(state.get("sample_time")):
        return sample_at
    last_seen = device.get("last_seen")
    if isinstance(last_seen, datetime):
        return last_seen
    if isinstance(last_seen, str):
        return datetime.fromisoformat(last_seen.replace("Z", "+00:00"))
    return None
