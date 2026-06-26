"""
Watchdog : active le bypass si Tint > 27°C ET Tint > Tout (intérieur plus chaud qu'extérieur).
Appelé toutes les 10 minutes par crontab.
"""
import logging
from datetime import datetime, timezone
from domeo import connect_modbus, connect_mongo

logging.basicConfig(
    filename='/app/watchdog.log',
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    datefmt='%Y-%m-%dT%H:%M:%SZ',
)

TINT_REG = 21  # input register — inside temperature
TOUT_REG = 22  # input register — outside temperature
BYPASS_COIL = 9


def decode_temp(raw: int) -> float:
    if raw > 500:
        raw -= 2 ** 16
    return raw / 10


def run():
    with connect_modbus() as mb:
        tint = decode_temp(mb.read_input_registers(address=TINT_REG).registers[0])
        tout = decode_temp(mb.read_input_registers(address=TOUT_REG).registers[0])
        should_bypass = tint > 27 and tint > tout
        mb.write_coil(address=BYPASS_COIL, value=should_bypass)

    action = 'ACTIVATED' if should_bypass else 'DEACTIVATED'
    logging.info('Tint=%.1f°C  Tout=%.1f°C  (seuil 27°C)  → bypass %s', tint, tout, action)

    with connect_mongo() as mongo:
        mongo.domeo210.watchdog.insert_one({
            'date': datetime.now(timezone.utc),
            'tint': tint,
            'tout': tout,
            'bypass_set': should_bypass,
        })


if __name__ == '__main__':
    run()
