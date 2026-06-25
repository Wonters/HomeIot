import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import Response, HTMLResponse
from pymongo.collection import ObjectId
from datetime import datetime
from domeo import connect_mongo, connect_modbus, switch_coil, request_domeo

DASHBOARD_HTML = (Path(__file__).parent / "templates" / "dashboard.html").read_text()

app = FastAPI()


class MongoEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, ObjectId):
            return str(value)
        elif isinstance(value, datetime):
            return value.strftime('%Y-%m-%dT%H:%M:%SZ')
        return super().default(value)


@app.get("/", response_class=HTMLResponse)
def dashboard():
    return DASHBOARD_HTML


@app.get("/metrics/latest")
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
        return Response(media_type="application/json",
                        content=json.dumps(result, cls=MongoEncoder))


@app.get("/metrics")
def get_metrics(name: str = '', _id: str = ''):
    with connect_mongo() as client:
        db = client.domeo210
        collection = db.metrics
        if name:
            query = collection.find({'name': name}).sort('date', 1)
        else:
            query = collection.find().sort('date', 1)
        return Response(media_type="application/json",
                        content=json.dumps([m for m in query], cls=MongoEncoder))

@app.get("/change/standby")
@request_domeo
def change_standby():
    switch_coil(coil_address=7)


@app.get("/change/bypass")
@request_domeo
def change_bypass():
    switch_coil(coil_address=9)


@app.get("/change/boost")
@request_domeo
def change_boost():
    """
    Activate or deactivate boost
    Doesn't work reading AIRFLOW SET holding register, value stay at 0
    Use TYPE OF CONTROL to get boost state
    4 = PROPOSIONAL 0 - 10V => BOST OFF
    5 = SWITCH ON/OFF => BOOST ON
    :return:
    """
    with connect_modbus() as client:
        value = int(client.read_input_registers(address=10).registers[0])
        if value == 4:
            client.write_register(address=15, value=1)
        else:
            client.write_register(address=15, value=0)


@app.get("/change/airflow")
@request_domeo
def change_airflow(value: int = 120):
    with connect_modbus() as client:
        client.write_register(address=9, value=value)


@app.get("/change/boost_setting")
@request_domeo
def change_airflow(value: int = 120):
    with connect_modbus() as client:
        client.write_register(address=10, value=value)


@app.get("/change/unbalance_flow")
@request_domeo
def change_unbalance_flow(value: int = 0):
    if -15 <= value < 0:
        value = value + (2 ** 16)
    with connect_modbus() as client:
        print(client.write_register(address=8, value=value))


@app.get("/metrics/drop")
def drop_metrics():
    with connect_mongo() as client:
        db = client.domeo210
        collection = db.metrics
        collection.drop()

