# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Domeo210** is a Python/FastAPI IoT control and monitoring system for a DOMEO210 ventilation unit (VMC). It communicates with the device via Modbus TCP through an ELFIN EW11A WiFi bridge, persists metrics to MongoDB, and visualizes data in Grafana.

## Run & Build

```bash
# Start all services (FastAPI :8000, MongoDB :6567, Grafana :3000)
docker compose up

# Rebuild after code changes
docker compose build
```

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `DOMEO_IP` | `192.168.1.97` | Modbus device IP |
| `DOMEO_PORT` | `8899` | Modbus TCP port |
| `MONGO_ADDRESS` | `mongodb://db:27017` | MongoDB connection string |
| `PORT` | `8000` | FastAPI port |

## Architecture

```
DOMEO210 device (Modbus TCP)
    ↓  pymodbus
domeo.py  ←→  MongoDB (metrics storage)
    ↓
main.py (FastAPI REST API)
    ↓
Grafana (JSON datasource → FastAPI)
```

**`app/domeo.py`** — core logic: `connect_modbus()`, `connect_mongo()`, `retrieve()` (reads all Modbus registers), `save()` (persists to MongoDB), `switch_coil()`, `decode()` (translates raw values to human-readable). The `@request_domeo` decorator auto-fetches and saves metrics after each state-change endpoint.

**`app/main.py`** — FastAPI endpoints: `GET /metrics`, `GET /change/standby|bypass|boost|airflow|boost_setting|unbalance_flow`, `GET /metrics/drop`.

**`app/config/domeo210_modbus.yml`** — Modbus register map (coils, discrete_inputs, input_registers, holding_registers). This drives all read/write logic; update here to add new registers without changing Python code.

**`app/cron.py`** — schedules `retrieve.sh` every 10 minutes via crontab.

## Key Implementation Notes

- **Temperature scaling**: device stores temperatures as 1/10th degrees; `decode()` divides by 10.
- **Signed integers**: `unbalance_flow` uses 16-bit signed int logic (`value - 2**16` for negatives).
- **Modbus sections**: coils and discrete_inputs are boolean (read via `read_coils`/`read_discrete_inputs`); input_registers and holding_registers are 16-bit integers.
- **Known bug**: `main.py` has two functions named `change_airflow()` — the second should be `change_boost_setting()`.

## Testing

No test framework is configured. Manual testing via `app/test.py` (uncomment the desired function call) or curl:

```bash
curl http://localhost:8000/metrics
curl http://localhost:8000/change/standby
curl "http://localhost:8000/change/airflow?value=150"
```
