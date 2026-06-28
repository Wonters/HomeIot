from contextlib import contextmanager
from pathlib import Path
import logging
import yaml
import os
from tqdm import tqdm
import datetime
from pymongo.mongo_client import MongoClient
from pymodbus.client import ModbusTcpClient
from functools import wraps

# COILS and HOLDING REGISTERS R/W
# DISCRETE and INPUT REGISTERS R
# from pymodbus import pymodbus_apply_logging_config
# pymodbus_apply_logging_config("DEBUG")

logger = logging.getLogger(__name__)

DOMEO_IP = os.environ.get("DOMEO_IP")
DOMEO_PORT = os.environ.get("DOMEO_PORT")
MONGO_ADDRESS = os.environ.get("MONGO_ADDRESS")
MODBUS_CONFIGFILE = Path(__file__).parent / "config/domeo210_modbus.yml"


@contextmanager
def connect_modbus() -> ModbusTcpClient:
    with ModbusTcpClient(host=DOMEO_IP, port=DOMEO_PORT, timeout=10) as client:
        yield client


@contextmanager
def connect_mongo():
    with MongoClient(MONGO_ADDRESS) as client:
        yield client


def decode(name, available_values, modbus_response):
    if len(available_values) > 1:
        # find the value in the available ones
        try:
            value = [
                k["value"] for k in available_values if k["count"] == modbus_response
            ][0]
        except IndexError:
            logger.info(f"{name}:{modbus_response} => Not found in datasheet")
            value = "not found in datasheet"
        unit = ""
    else:
        if name == "UNBALANCE AIRFLOW SELECTION":
            value = (
                modbus_response - (2**16) if modbus_response > 15 else modbus_response
            )
        elif name in (
            "TEMPERATURE Tin PRE-HEATING BATTERY",
            "TEMPERATURE Tout PRE-HEATING BATTERY",
            "TEMPERATURE Tin POST-HEATING BATTERY",
            "TEMPERATURE Tout POST-HEATING BATTERY",
            "TEMPERATURE Tint",
            "TEMPERATURE Tout",
            "TEMPERATURE Text",
            "TEMPERATURE Timp",
        ):
            value = (
                (modbus_response - (2**16)) / 10
                if modbus_response > 500
                else modbus_response / 10
            )
        else:
            value = modbus_response
        unit = available_values[0]["value"]
    return value, unit


def retrieve():
    with MODBUS_CONFIGFILE.open("r") as f:
        modbus_commands = yaml.load(f, Loader=yaml.Loader)

    with connect_modbus() as client:
        domeo_data = dict(
            coils=client.read_coils(address=0, count=17).bits,
            discrete_inputs=client.read_discrete_inputs(address=0, count=17).bits,
            input_registers=client.read_input_registers(address=0, count=41).registers,
            holding_registers=client.read_holding_registers(
                address=0, count=101
            ).registers,
        )

    data = []
    for name, commands in tqdm(modbus_commands.items()):
        for command in commands:
            register_index = int(command["register_number"])
            response_data = domeo_data[name][register_index]
            # translate the response in value
            value, unit = decode(command["description"], command["data"], response_data)
            data.append(
                {
                    "name": command["description"],
                    "register": response_data,
                    "value": value,
                    "unit": unit,
                }
            )
    return data


def switch_coil(coil_address: int):
    with connect_modbus() as client:
        value = int(client.read_coils(address=coil_address).bits[0])
        if value == 0:
            client.write_coil(address=coil_address, value=True)
        else:
            client.write_coil(address=coil_address, value=False)


STANDBY_METRIC = "ACTIVATION MODE STANBY/ABSENCE"
BYPASS_STATE_METRIC = "STATE OF BYPASS"
BYPASS_MANUAL_METRIC = "MANUAL BYPASS"
BOOST_METRIC = "TYPE OF CONTROL"
BOOST_REGISTER_ON = 5


def build_status_doc(data: list[dict], date: datetime.datetime | None = None) -> dict:
    by_name = {d["name"]: d for d in data}
    standby = by_name.get(STANDBY_METRIC, {})
    bypass_state = by_name.get(BYPASS_STATE_METRIC, {})
    bypass_manual = by_name.get(BYPASS_MANUAL_METRIC, {})
    boost = by_name.get(BOOST_METRIC, {})
    return {
        "date": date or datetime.datetime.now(tz=datetime.timezone.utc),
        "standby": {
            "active": standby.get("register") == 1,
            "register": standby.get("register"),
            "value": standby.get("value"),
        },
        "bypass": {
            "active": bypass_state.get("value") == "ACTIVED",
            "register": bypass_state.get("register"),
            "value": bypass_state.get("value"),
        },
        "bypass_manual": {
            "active": bypass_manual.get("value") == "ACTIVED",
            "register": bypass_manual.get("register"),
            "value": bypass_manual.get("value"),
        },
        "boost": {
            "active": boost.get("register") == BOOST_REGISTER_ON,
            "register": boost.get("register"),
            "value": boost.get("value"),
        },
    }


def save_status(data: list[dict], date: datetime.datetime | None = None, *, client=None):
    doc = build_status_doc(data, date)
    if client is not None:
        client.domeo210.status.insert_one(doc)
        return
    with connect_mongo() as mongo:
        mongo.domeo210.status.insert_one(doc)


def save(data):
    now = datetime.datetime.now(tz=datetime.timezone.utc)
    with connect_mongo() as client:
        db = client.domeo210
        db.metrics.insert_many([{"date": now, **d} for d in data])
        save_status(data, now, client=client)


def request_domeo(func):
    """
    Wrapper to retrieve domeo info
    :param func:
    :return:
    """

    @wraps(func)
    def request(*args, **kwargs):
        result = func(*args, **kwargs)
        save(retrieve())
        return result

    return request
