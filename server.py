import json
from fastapi import FastAPI
from fastapi.responses import Response
from pymongo.collection import ObjectId
from datetime import datetime
from domeo import save, retrieve, connect_mongo, connect_modbus

app = FastAPI()


class MongoEncoder(json.JSONEncoder):
    def default(self, value):
        if isinstance(value, ObjectId):
            return str(value)
        elif isinstance(value, datetime):
            return value.strftime('%Y-%m-%dT%H:%M:%SZ')
        return super().default(value)


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
def change_standby():
    with connect_modbus() as client:
        value = int(client.read_coils(address=7).bits[0])
        if value == 0:
            client.write_coil(address=7, value=1)
        else:
            client.write_coil(address=7, value=0)
    save(retrieve())


@app.get("/change/bypass")
def change_bypass():
    with connect_modbus() as client:
        value = int(client.read_coils(address=9).bits[0])
        if value == 0:
            client.write_coil(address=9, value=1)
        else:
            client.write_coil(address=9, value=0)
    save(retrieve())


@app.get("/change/airflow")
def change_airflow(value: int = 120):
    with connect_modbus() as client:
        client.write_register(address=9, value=value)
    save(retrieve())


@app.get("/change/unbalance_flow")
def unbalance_flow(value: int = 0):
    if -15 <= value < 0:
        value = value + (2 << 15)
    with connect_modbus() as client:
        print(client.write_register(address=8, value=value))
    # save(retrieve())


@app.get("/metrics/drop")
def drop_metrics():
    with connect_mongo() as client:
        db = client.domeo210
        collection = db.metrics
        collection.drop()


@app.get("/retrieve")
def retrieve_vmc():
    save(retrieve())
