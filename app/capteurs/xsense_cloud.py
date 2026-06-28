import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

from xsense import XSense
from xsense.entity_map import EntityType
from xsense.exceptions import AuthFailed, SessionExpired

from .store import (
    DB_NAME,
    connect_mongo,
    merge_device_state,
    replace_device_metrics,
    upsert_device_snapshot,
)

logger = logging.getLogger(__name__)

XSENSE_EMAIL = os.environ.get("XSENSE_EMAIL", "")
XSENSE_PASSWORD = os.environ.get("XSENSE_PASSWORD", "")
XSENSE_CLOUD_ENABLED = os.environ.get("XSENSE_CLOUD_ENABLED", "true").lower() in ("1", "true", "yes")
POLL_INTERVAL = int(os.environ.get("XSENSE_POLL_INTERVAL", "60"))
REFRESH_WAIT_SEC = float(os.environ.get("XSENSE_REFRESH_WAIT", "4"))
HISTORY_DAYS = int(os.environ.get("XSENSE_HISTORY_DAYS", "365"))
MAX_HISTORY_PAGES = int(os.environ.get("XSENSE_HISTORY_MAX_PAGES", "400"))
STALE_SAMPLE_MINUTES = int(os.environ.get("XSENSE_STALE_SAMPLE_MINUTES", "5"))

TEMPERATURE_TYPES = {"STH51", "STH0A", "STH0B"}

_api: XSense | None = None
_thread: threading.Thread | None = None
_stop_event = threading.Event()
_lock = threading.Lock()

_connected = False
_last_sync: datetime | None = None
_last_error: str | None = None
_device_count = 0

_reset_thread: threading.Thread | None = None
_reset_status: dict = {
    "running": False,
    "error": None,
    "device": "",
    "devices_done": 0,
    "devices_total": 0,
    "points": 0,
    "pages": 0,
}


def is_enabled() -> bool:
    return XSENSE_CLOUD_ENABLED and bool(XSENSE_EMAIL) and bool(XSENSE_PASSWORD)


def is_connected() -> bool:
    return _connected


def last_sync_time() -> datetime | None:
    return _last_sync


def last_error() -> str | None:
    return _last_error


def device_count() -> int:
    return _device_count


def history_reset_status() -> dict:
    return {
        **dict(_reset_status),
        "history_days": HISTORY_DAYS,
    }


def is_reset_running() -> bool:
    return bool(_reset_status.get("running"))


def _device_id(station_sn: str, device_sn: str) -> str:
    station = station_sn.upper()
    if not station.startswith("SBS"):
        station = f"SBS50{station}"
    return f"{station}_{device_sn}"


def _room_name(house, room_id: str | None) -> str | None:
    if not room_id:
        return None
    rooms = house.rooms
    if not rooms:
        return None
    if isinstance(rooms, dict):
        room = rooms.get(room_id)
        if isinstance(room, dict):
            return room.get("roomName") or room.get("name")
        if isinstance(room, str):
            return room
    if isinstance(rooms, list):
        for room in rooms:
            if isinstance(room, dict) and room.get("roomId") == room_id:
                return room.get("roomName") or room.get("name")
    return None


def _build_meta(house, station, device, *, include_source: bool = True) -> dict:
    meta = {
        "friendly_name": device.name or f"{device.type} {device.sn}",
        "model": device.type,
        "manufacturer": "X-Sense",
        "station_sn": station.sn,
        "device_sn": device.sn,
    }
    if include_source:
        meta["source"] = "xsense-cloud"
    if location := _room_name(house, device.room_id):
        meta["location"] = location
    return meta


def _parse_sample_time(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _extract_fields(device) -> dict:
    data = device.data
    updates = {}
    if "temperature" in data:
        updates["temperature"] = data["temperature"]
    if "humidity" in data:
        updates["humidity"] = data["humidity"]
    if "batInfo" in data:
        updates["battery"] = data["batInfo"]
    if device.online is not None:
        updates["online"] = device.online
    if sample_time := data.get("time"):
        updates["sample_time"] = sample_time
    return updates


def _reset_station_devices(station):
    for device in station.devices.values():
        device._data.clear()
        device.online = None


def _request_sth51_refresh(api: XSense, station) -> bool:
    sth_sns = [
        device.sn
        for device in station.devices.values()
        if device.type in TEMPERATURE_TYPES
    ]
    if not sth_sns:
        return False

    payload = {
        "state": {
            "desired": {
                "shadow": "appTempData",
                "deviceSN": sth_sns,
                "source": "1",
                "report": "1",
                "reportDst": "1",
                "timeoutM": "1",
                "userId": api.userid,
                "time": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                "stationSN": station.sn,
            }
        }
    }
    try:
        api.do_thing(station, "2nd_apptempdata", payload)
        return True
    except Exception:
        logger.exception("X-Sense appTempData request failed for station %s", station.sn)
        return False


def _read_station_state(api: XSense, station):
    _reset_station_devices(station)
    if _request_sth51_refresh(api, station):
        time.sleep(REFRESH_WAIT_SEC)
    api.get_state(station)


def _last_metric_at(device_id: str) -> datetime | None:
    with connect_mongo() as client:
        doc = client[DB_NAME].metrics.find_one(
            {"device": device_id, "field": "temperature"},
            sort=[("date", -1)],
            projection={"date": 1},
        )
    return _as_utc(doc["date"]) if doc else None


def _append_new_history_metrics(device_id: str, metrics: list[dict]) -> int:
    if not metrics:
        return 0
    last_at = _last_metric_at(device_id)
    new_metrics = [
        metric for metric in metrics
        if last_at is None or _as_utc(metric["date"]) > last_at
    ]
    if not new_metrics:
        return 0
    with connect_mongo() as client:
        client[DB_NAME].metrics.insert_many(new_metrics)
    return len(new_metrics)


def _needs_metric_backfill(device_id: str, sample_at: datetime | None, fields: dict) -> bool:
    if sample_at is None or "temperature" not in fields:
        return False
    with connect_mongo() as client:
        return client[DB_NAME].metrics.find_one({
            "device": device_id,
            "field": "temperature",
            "date": sample_at,
        }) is None


def _sync_temperature_device(
    device_id: str,
    fields: dict,
    meta: dict,
    *,
    sync_at: datetime,
) -> None:
    sample_at = _parse_sample_time(fields.get("sample_time"))
    meta = {**meta, "cloud_sync_at": sync_at}

    with connect_mongo() as client:
        doc = client[DB_NAME].devices.find_one({"_id": device_id}, {"state": 1})
    current = (doc or {}).get("state", {})

    new_sample = fields.get("sample_time")
    old_sample = current.get("sample_time")
    has_new_sample = bool(new_sample and new_sample != old_sample)
    has_value_change = any(
        fields.get(field) != current.get(field)
        for field in fields
        if field != "sample_time"
    )
    needs_backfill = _needs_metric_backfill(device_id, sample_at, fields)

    if has_new_sample or has_value_change or needs_backfill:
        merge_device_state(
            device_id,
            fields,
            meta,
            only_if_changed=False,
            seen_at=sample_at,
        )
        if sample_at and (sync_at - sample_at) > timedelta(minutes=15):
            logger.warning(
                "X-Sense %s: mesure cloud ancienne (%s, âge %s min)",
                device_id,
                sample_at.isoformat(),
                int((sync_at - sample_at).total_seconds() // 60),
            )
        return

    upsert_device_snapshot(device_id, device_meta=meta)


def _is_temperature_device(device) -> bool:
    return device.entity_type == EntityType.TEMPERATURE or device.type in TEMPERATURE_TYPES


def _parse_history_entry(day: datetime, entry: str) -> tuple[datetime, float, float] | None:
    parts = entry.split(",")
    if len(parts) < 3:
        return None
    try:
        clock = datetime.strptime(parts[0], "%H%M%S").time()
        dt = datetime.combine(day.date(), clock, tzinfo=timezone.utc)
        return dt, float(parts[1]), float(parts[2])
    except ValueError:
        return None


def _fetch_device_history(
    api: XSense,
    house,
    station,
    device,
    since: datetime,
    *,
    on_progress=None,
    max_pages: int | None = None,
) -> list[dict]:
    device_id = _device_id(station.sn, device.sn)
    metrics: list[dict] = []
    last_time = "0"
    next_token = ""
    empty_pages = 0
    prev_token: str | None = None
    page_limit = max_pages if max_pages is not None else MAX_HISTORY_PAGES

    for page_num in range(1, page_limit + 1):
        params = {
            "houseId": house.house_id,
            "stationId": station.entity_id,
            "deviceId": device.entity_id,
            "lastTime": last_time,
        }
        if next_token:
            params["nextToken"] = next_token

        re_data = api.api_call("104011", **params)
        data_list = re_data.get("dataList") or {}
        page_min_dt: datetime | None = None
        page_had_rows = False

        for day_key, values in data_list.items():
            try:
                day = datetime.strptime(day_key, "%Y%m%d").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            for entry in values or []:
                page_had_rows = True
                parsed = _parse_history_entry(day, entry)
                if not parsed:
                    continue
                dt, temperature, humidity = parsed
                if page_min_dt is None or dt < page_min_dt:
                    page_min_dt = dt
                if dt < since:
                    continue
                metrics.append({
                    "date": dt,
                    "device": device_id,
                    "field": "temperature",
                    "value": temperature,
                })
                metrics.append({
                    "date": dt,
                    "device": device_id,
                    "field": "humidity",
                    "value": humidity,
                })

        if on_progress:
            on_progress(len(metrics), page_num)

        if not page_had_rows:
            empty_pages += 1
        else:
            empty_pages = 0

        new_token = (re_data.get("nextToken") or "").strip()
        new_last_time = re_data.get("lastTime") or last_time

        if page_min_dt and page_min_dt < since:
            break
        if not new_token or empty_pages >= 3:
            break
        if new_token == prev_token and new_last_time == last_time:
            logger.warning("X-Sense history pagination stalled for %s", device_id)
            break

        prev_token = new_token
        next_token = new_token
        last_time = new_last_time
    else:
        logger.warning(
            "X-Sense history page limit reached for %s (%s pages)",
            device_id,
            page_limit,
        )

    return metrics


def _latest_history_fields(metrics: list[dict]) -> dict:
    latest: dict[str, tuple[datetime, float]] = {}
    for metric in metrics:
        field = metric["field"]
        current = latest.get(field)
        if current is None or metric["date"] > current[0]:
            latest[field] = (metric["date"], metric["value"])
    fields = {field: value for field, (_, value) in latest.items()}
    if latest:
        sample_at = max(dt for dt, _ in latest.values())
        fields["sample_time"] = sample_at.strftime("%Y%m%d%H%M%S")
    return fields


def _supplement_stale_fields(
    api: XSense,
    house,
    station,
    device,
    fields: dict,
    *,
    sync_at: datetime,
) -> dict:
    device_id = _device_id(station.sn, device.sn)
    sample_at = _parse_sample_time(fields.get("sample_time"))
    last_metric_at = _last_metric_at(device_id)

    if sample_at and last_metric_at and last_metric_at >= sample_at:
        return fields

    if sample_at and (sync_at - sample_at) < timedelta(minutes=STALE_SAMPLE_MINUTES):
        return fields

    since = last_metric_at or (sync_at - timedelta(hours=6))
    if last_metric_at:
        since = max(last_metric_at - timedelta(minutes=5), sync_at - timedelta(hours=6))
    metrics = _fetch_device_history(
        api,
        house,
        station,
        device,
        since,
        max_pages=1,
    )
    added = _append_new_history_metrics(device_id, metrics)
    if added:
        logger.info(
            "X-Sense %s: %s point(s) ajouté(s) depuis l'historique cloud",
            device_id,
            added,
        )

    history_fields = _latest_history_fields(metrics)
    if not history_fields:
        return fields

    history_sample = _parse_sample_time(history_fields.get("sample_time"))
    if history_sample and (sample_at is None or history_sample >= sample_at):
        if history_sample != sample_at:
            logger.info(
                "X-Sense %s: historique récent utilisé (%s)",
                device_id,
                history_sample.isoformat(),
            )
        return {**fields, **history_fields}
    return fields


def _latest_metric_fields(metrics: list[dict]) -> dict:
    latest: dict[str, tuple[datetime, float]] = {}
    for metric in metrics:
        field = metric["field"]
        current = latest.get(field)
        if current is None or metric["date"] > current[0]:
            latest[field] = (metric["date"], metric["value"])
    return {field: value for field, (_, value) in latest.items()}


def _run_history_reset():
    global _reset_status, _api

    _reset_status = {
        "running": True,
        "error": None,
        "device": "",
        "devices_done": 0,
        "devices_total": 0,
        "points": 0,
        "pages": 0,
    }

    since = datetime.now(timezone.utc) - timedelta(days=HISTORY_DAYS)

    with _lock:
        try:
            if _api is None:
                _api = XSense()
                _connect(_api)

            targets = []
            for house in _api.houses.values():
                for station in house.stations.values():
                    for device in station.devices.values():
                        if _is_temperature_device(device):
                            targets.append((house, station, device))

            _reset_status["devices_total"] = len(targets)

            total_points = 0

            for house, station, device in targets:
                device_id = _device_id(station.sn, device.sn)
                _reset_status["device"] = device.name or device_id
                _reset_status["pages"] = 0

                def on_progress(device_points, pages):
                    _reset_status["pages"] = pages
                    _reset_status["points"] = total_points + device_points

                metrics = _fetch_device_history(
                    _api,
                    house,
                    station,
                    device,
                    since,
                    on_progress=on_progress,
                )
                meta = _build_meta(house, station, device)
                replace_device_metrics(device_id, metrics)

                fields = _latest_metric_fields(metrics)
                last_seen = max((m["date"] for m in metrics), default=None)
                upsert_device_snapshot(
                    device_id,
                    fields or None,
                    meta,
                    last_seen=last_seen,
                )

                _reset_status["devices_done"] += 1
                total_points += len(metrics)
                _reset_status["points"] = total_points
                logger.info(
                    "X-Sense history reset %s: %s point(s)",
                    device_id,
                    len(metrics),
                )

            _reset_status["running"] = False
            logger.info(
                "X-Sense history reset done: %s point(s) on %s device(s)",
                _reset_status["points"],
                _reset_status["devices_done"],
            )
        except Exception as exc:
            _reset_status["running"] = False
            _reset_status["error"] = str(exc)
            logger.exception("X-Sense history reset failed")


def start_history_reset() -> tuple[bool, str]:
    global _reset_thread

    if not is_enabled():
        return False, "Cloud X-Sense désactivé"
    if _reset_status.get("running"):
        return False, "Réinitialisation déjà en cours"

    _reset_thread = threading.Thread(
        target=_run_history_reset,
        daemon=True,
        name="xsense-history-reset",
    )
    _reset_thread.start()
    return True, f"Téléchargement de {HISTORY_DAYS} jour(s) d'historique démarré"


def _sync_devices(api: XSense) -> int:
    count = 0
    sync_at = datetime.now(timezone.utc)
    for house in api.houses.values():
        try:
            api.get_house_state(house)
        except Exception:
            logger.exception("X-Sense get_house_state failed for house %s", house.house_id)

        for station in house.stations.values():
            try:
                _read_station_state(api, station)
            except Exception:
                logger.exception("X-Sense get_state failed for station %s", station.sn)
                continue

            for device in station.devices.values():
                device_id = _device_id(station.sn, device.sn)
                meta = _build_meta(house, station, device)

                if _is_temperature_device(device):
                    fields = _extract_fields(device)
                    fields = _supplement_stale_fields(
                        api,
                        house,
                        station,
                        device,
                        fields,
                        sync_at=sync_at,
                    )
                    if not fields and not meta.get("location"):
                        continue
                    _sync_temperature_device(
                        device_id,
                        fields,
                        meta,
                        sync_at=sync_at,
                    )
                    logger.debug(
                        "X-Sense cloud synced %s: temp=%s hum=%s t=%s",
                        device_id,
                        fields.get("temperature"),
                        fields.get("humidity"),
                        fields.get("sample_time"),
                    )
                else:
                    location_meta = {
                        k: meta[k]
                        for k in ("location", "device_sn", "station_sn")
                        if meta.get(k)
                    }
                    if not location_meta:
                        continue
                    merge_device_state(device_id, {}, location_meta)

                count += 1
    return count


def _close_api(api: XSense | None):
    if api is None:
        return
    close = getattr(api, "close", None)
    if callable(close):
        close()


def _connect(api: XSense):
    api.init()
    api.login(XSENSE_EMAIL, XSENSE_PASSWORD)
    api.load_all()


def _poll_once():
    global _connected, _last_sync, _last_error, _device_count, _api

    if not is_enabled():
        return

    with _lock:
        try:
            if _api is None:
                _api = XSense()
                _connect(_api)
            count = _sync_devices(_api)
            _connected = True
            _last_sync = datetime.now(timezone.utc)
            _last_error = None
            _device_count = count
            logger.info("X-Sense cloud sync: %s device(s)", count)
        except SessionExpired:
            try:
                _api.refresh()
                _api.load_aws()
                count = _sync_devices(_api)
                _connected = True
                _last_sync = datetime.now(timezone.utc)
                _last_error = None
                _device_count = count
                logger.info("X-Sense cloud sync after refresh: %s device(s)", count)
            except Exception as exc:
                _connected = False
                _last_error = str(exc)
                if _api is not None:
                    _close_api(_api)
                _api = None
                logger.exception("X-Sense cloud session refresh failed")
        except AuthFailed as exc:
            _connected = False
            _last_error = str(exc)
            if _api is not None:
                _close_api(_api)
            _api = None
            logger.error("X-Sense cloud auth failed: %s", exc)
        except Exception as exc:
            _connected = False
            _last_error = str(exc)
            logger.exception("X-Sense cloud sync failed")


def _run_loop():
    while not _stop_event.is_set():
        _poll_once()
        if _stop_event.wait(POLL_INTERVAL):
            break


def start_xsense_cloud():
    global _thread
    if not is_enabled():
        logger.info(
            "X-Sense cloud disabled (XSENSE_CLOUD_ENABLED=%s, credentials=%s)",
            XSENSE_CLOUD_ENABLED,
            "set" if XSENSE_EMAIL and XSENSE_PASSWORD else "missing",
        )
        return
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_run_loop, daemon=True, name="xsense-cloud")
    _thread.start()
    logger.info("X-Sense cloud poller started (interval=%ss)", POLL_INTERVAL)


def stop_xsense_cloud():
    global _api, _thread
    _stop_event.set()
    if _thread is not None:
        _thread.join(timeout=POLL_INTERVAL + 10)
        _thread = None
    if _api is not None:
        _close_api(_api)
        _api = None
