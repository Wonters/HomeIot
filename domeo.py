import pprint

from pymodbus.client import ModbusTcpClient
from contextlib import contextmanager
import yaml
from tqdm import tqdm
import datetime
from pymongo.mongo_client import MongoClient
from pymodbus import pymodbus_apply_logging_config
from pymodbus.client import ModbusTcpClient

# COILS and HOLDING REGISTERS R/W
# DISCRETE and INPUT REGISTERS R
# pymodbus_apply_logging_config("DEBUG")

@contextmanager
def connect_modbus() -> ModbusTcpClient:
    with ModbusTcpClient(host='192.168.1.97', port=8899) as client:
        yield client


@contextmanager
def connect_mongo():
    with MongoClient("mongodb://127.0.0.1:6567") as client:
        yield client


def retrieve():
    with open('domeo210_modbus.yml', 'r') as f:
        modbus_commands = yaml.load(f, Loader=yaml.Loader)
    data = []
    with connect_modbus() as client:
        for name, commands in tqdm(modbus_commands.items()):
            for command in commands:
                rep = client.__getattribute__(f'read_{name}')(address=int(command['register_number']))
                if name in ('coils', 'discrete_inputs'):
                    response_data = int(rep.bits[0])
                else:
                    response_data = rep.registers[0]
                if len(command['data']) > 1:
                    if [k['value'] for k in command['data'] if k['count'] == response_data]:
                        value = [k['value'] for k in command['data'] if k['count'] == response_data][0]
                else:
                    value = command['data'][0]['value']
                data.append({'name': command['description'], 'register': response_data, 'value': value})
    return data


def new_retrieve():
    with open('domeo210_modbus.yml', 'r') as f:
        modbus_commands = yaml.load(f, Loader=yaml.Loader)

    for register_name, commands in modbus_commands.items():
        print(register_name, len(commands))

    with connect_modbus() as client:
        coils = client.read_coils(address=0, count=17).bits
        discrete_inputs = client.read_discrete_inputs(address=0, count=17).bits
        input_registers = client.read_input_registers(address=0, count=41).registers
        holding_registers = client.read_holding_registers(address=0, count=101).registers
        print(coils)
        print(input_registers)
        print(holding_registers)
        print(discrete_inputs)
        print(len(coils),len(input_registers), len(holding_registers), len(discrete_inputs))
        print(client.read_coils(address=7).bits, coils[7])


def save(data):
    with connect_mongo() as client:
        db = client.domeo210
        collection = db.metrics
        collection.insert_many([{
            'date': datetime.datetime.now(tz=datetime.timezone.utc),
            'name': d['name'],
            'register': d['register'],
            'value': d['value']
        } for d in data])


