"""
Watchdog débit : LOW AIRFLOW à 150 m³/h si bypass actif et T° SAAS < T° Kitchen,
sinon 120 m³/h.
"""
import logging
from datetime import datetime, timezone

from capteurs.store import connect_mongo as connect_capteurs_mongo
from capteurs.xsense_devices import (
    device_temperature,
    find_kitchen_device,
    find_saas_device,
)
from .domeo import connect_modbus, connect_mongo

logging.basicConfig(
    filename='/app/watchdog.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ',
)

BYPASS_STATE_REG = 25
LOW_AIRFLOW_REG = 9
AIRFLOW_DEFAULT = 120
AIRFLOW_BOOST = 150


def _is_bypass_active(client) -> bool:
    return client.read_input_registers(address=BYPASS_STATE_REG).registers[0] == 1


def _target_airflow(bypass_active: bool, saas_temp: float | None, kitchen_temp: float | None) -> tuple[int, str]:
    if not bypass_active:
        return AIRFLOW_DEFAULT, "bypass_off"
    if saas_temp is None or kitchen_temp is None:
        return AIRFLOW_DEFAULT, "missing_temps"
    if saas_temp < kitchen_temp:
        return AIRFLOW_BOOST, "bypass_saas_cooler"
    return AIRFLOW_DEFAULT, "bypass_saas_warmer"


def run():
    with connect_capteurs_mongo() as client:
        devices = list(client.capteurs.devices.find({"source": "xsense-cloud"}))

    saas_device = find_saas_device(devices)
    kitchen_device = find_kitchen_device(devices)
    saas_temp = device_temperature(saas_device)
    kitchen_temp = device_temperature(kitchen_device)

    with connect_modbus() as mb:
        bypass_active = _is_bypass_active(mb)
        target, reason = _target_airflow(bypass_active, saas_temp, kitchen_temp)
        current = mb.read_holding_registers(address=LOW_AIRFLOW_REG).registers[0]
        if current != target:
            mb.write_register(address=LOW_AIRFLOW_REG, value=target)

    logging.info(
        'bypass=%s  saas=%s°C  kitchen=%s°C  airflow %s→%s m³/h (%s)',
        bypass_active,
        f'{saas_temp:.1f}' if saas_temp is not None else '—',
        f'{kitchen_temp:.1f}' if kitchen_temp is not None else '—',
        current,
        target,
        reason,
    )

    with connect_mongo() as mongo:
        mongo.domeo210.watchdog.insert_one({
            'date': datetime.now(timezone.utc),
            'bypass_active': bypass_active,
            'saas_temp': saas_temp,
            'kitchen_temp': kitchen_temp,
            'airflow_before': current,
            'airflow_target': target,
            'airflow_applied': current != target,
            'reason': reason,
        })


if __name__ == '__main__':
    run()
