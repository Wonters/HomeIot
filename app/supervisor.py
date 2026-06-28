import logging
import os
import threading
import time
from typing import Callable

logger = logging.getLogger(__name__)

POLL_RATE_MIN = int(os.environ.get("CRON_RATE", "1"))
INTERVAL_SEC = POLL_RATE_MIN * 60

_workers: list[threading.Thread] = []
_stop_event = threading.Event()


def _loop(name: str, func: Callable, interval: float, initial_delay: float = 0):
    if initial_delay > 0 and _stop_event.wait(initial_delay):
        return
    while not _stop_event.is_set():
        try:
            func()
            logger.info("%s completed", name)
        except Exception:
            logger.exception("%s failed", name)
        if _stop_event.wait(interval):
            break


def start_supervisor():
    if _workers:
        return

    from vmc.domeo import retrieve, save
    from vmc.watchdog import run as watchdog_run

    _stop_event.clear()
    tasks = [
        ("retrieve", lambda: save(retrieve()), INTERVAL_SEC, 0),
        ("watchdog", watchdog_run, INTERVAL_SEC, INTERVAL_SEC // 2),
    ]
    for name, func, interval, delay in tasks:
        thread = threading.Thread(
            target=_loop,
            args=(name, func, interval, delay),
            daemon=True,
            name=f"supervisor-{name}",
        )
        thread.start()
        _workers.append(thread)

    logger.info("Supervisor started (interval=%s min)", POLL_RATE_MIN)


def stop_supervisor():
    _stop_event.set()
    for thread in _workers:
        thread.join(timeout=INTERVAL_SEC + 5)
    _workers.clear()


def is_running() -> bool:
    return bool(_workers) and all(t.is_alive() for t in _workers)
