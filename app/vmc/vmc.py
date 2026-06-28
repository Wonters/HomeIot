import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pymongo.collection import ObjectId

from nav import inject_app_nav
from supervisor import is_running as supervisor_running
from .domeo import connect_mongo, connect_modbus, switch_coil, request_domeo
from .settings import get_vmc_config

DASHBOARD_HTML = inject_app_nav(
    (Path(__file__).parent / "dashboard.html").read_text(),
    "VMC",
)

router = APIRouter()


class MongoEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, ObjectId):
            return str(value)
        if isinstance(value, datetime):
            return value.strftime('%Y-%m-%dT%H:%M:%SZ')
        return super().default(value)


@router.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@router.get("/metrics/latest")
def get_latest_metrics():
    with connect_mongo() as client:
        pipeline = [
            {"$sort": {"date": -1}},
            {"$group": {
                "_id": "$name",
                "value": {"$first": "$value"},
                "register": {"$first": "$register"},
                "unit": {"$first": "$unit"},
                "date": {"$first": "$date"},
            }},
        ]
        result = {
            doc["_id"]: {
                "value": doc["value"],
                "register": doc["register"],
                "unit": doc.get("unit", ""),
                "date": doc["date"],
            }
            for doc in client.domeo210.metrics.aggregate(pipeline)
        }
        return Response(
            media_type="application/json",
            content=json.dumps(result, cls=MongoEncoder),
        )


@router.get("/metrics")
def get_metrics(name: str = '', _id: str = ''):
    with connect_mongo() as client:
        collection = client.domeo210.metrics
        if name:
            query = collection.find({'name': name}).sort('date', 1)
        else:
            query = collection.find().sort('date', 1)
        return Response(
            media_type="application/json",
            content=json.dumps([m for m in query], cls=MongoEncoder),
        )


@router.get("/config")
def get_config():
    return Response(
        media_type="application/json",
        content=json.dumps(get_vmc_config(), cls=MongoEncoder),
    )


@router.get("/change/bypass_auto")
@request_domeo
def change_bypass_auto():
    switch_coil(coil_address=8)


@router.get("/config/bypass_auto_text_mini")
@request_domeo
def set_bypass_auto_text_mini(value: int = Query(...)):
    if not 11 <= value <= 20:
        raise HTTPException(400, "Text MINI doit être entre 11 et 20 °C")
    with connect_modbus() as client:
        client.write_register(address=22, value=value)


@router.get("/config/bypass_auto_tint_mini")
@request_domeo
def set_bypass_auto_tint_mini(value: int = Query(...)):
    if not 21 <= value <= 30:
        raise HTTPException(400, "Tint MINI doit être entre 21 et 30 °C")
    with connect_modbus() as client:
        client.write_register(address=23, value=value)


@router.get("/change/standby")
@request_domeo
def change_standby():
    switch_coil(coil_address=7)


@router.get("/change/bypass")
@request_domeo
def change_bypass():
    switch_coil(coil_address=9)


@router.get("/change/boost")
@request_domeo
def change_boost():
    """
    Activate or deactivate boost.
    Doesn't work reading AIRFLOW SET holding register, value stay at 0.
    Use TYPE OF CONTROL to get boost state:
    4 = PROPOSIONAL 0 - 10V => BOOST OFF
    5 = SWITCH ON/OFF => BOOST ON
    """
    with connect_modbus() as client:
        value = int(client.read_input_registers(address=10).registers[0])
        print(value)
        if value == 4:
            client.write_register(address=15, value=1)
        else:
            client.write_register(address=15, value=0)


@router.get("/change/airflow")
@request_domeo
def change_airflow(value: int = 120):
    with connect_modbus() as client:
        client.write_register(address=9, value=value)


@router.get("/change/boost_setting")
@request_domeo
def change_boost_setting(value: int = 120):
    with connect_modbus() as client:
        client.write_register(address=10, value=value)


@router.get("/change/unbalance_flow")
@request_domeo
def change_unbalance_flow(value: int = 0):
    if -15 <= value < 0:
        value = value + (2 ** 16)
    with connect_modbus() as client:
        print(client.write_register(address=8, value=value))


@router.get("/metrics/temperatures")
def get_temperature_history(period: str = 'day'):
    with connect_mongo() as client:
        now = datetime.utcnow()
        if period == 'year':
            since = now - timedelta(days=365)
        elif period == 'month':
            since = now - timedelta(days=30)
        else:
            since = now - timedelta(days=1)
        names = ['TEMPERATURE Timp', 'TEMPERATURE Text', 'TEMPERATURE Tout', 'TEMPERATURE Tint']
        result = {}
        for name in names:
            docs = list(client.domeo210.metrics.find(
                {'name': name, 'date': {'$gte': since}},
                {'date': 1, 'value': 1, '_id': 0}
            ).sort('date', 1))
            if len(docs) > 300:
                step = len(docs) // 300
                docs = docs[::step]
            result[name] = [{'t': d['date'], 'v': d['value']} for d in docs]
        return Response(
            media_type="application/json",
            content=json.dumps(result, cls=MongoEncoder),
        )


@router.get("/status")
def get_status():
    with connect_mongo() as client:
        last = client.domeo210.metrics.find_one(sort=[('date', -1)])
        last_date = last['date'] if last else None
        modes = client.domeo210.status.find_one(sort=[('date', -1)])
    return Response(
        media_type="application/json",
        content=json.dumps({
            'supervisor_running': supervisor_running(),
            'poll_interval_min': int(os.environ.get("CRON_RATE", "1")),
            'last_update': last_date,
            'modes': {
                'standby': modes.get('standby') if modes else None,
                'bypass': modes.get('bypass') if modes else None,
                'boost': modes.get('boost') if modes else None,
            } if modes else None,
        }, cls=MongoEncoder),
    )


@router.get("/status/history")
def get_status_history(period: str = 'day'):
    with connect_mongo() as client:
        now = datetime.utcnow()
        if period == 'year':
            since = now - timedelta(days=365)
        elif period == 'month':
            since = now - timedelta(days=30)
        else:
            since = now - timedelta(days=1)
        docs = list(client.domeo210.status.find(
            {'date': {'$gte': since}},
            {'_id': 0},
        ).sort('date', 1))
        return Response(
            media_type="application/json",
            content=json.dumps(docs, cls=MongoEncoder),
        )


@router.get("/metrics/drop")
def drop_metrics():
    with connect_mongo() as client:
        client.domeo210.metrics.drop()
