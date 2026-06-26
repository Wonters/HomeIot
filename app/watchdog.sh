#!/bin/bash
source /etc/profile
cd /app/
python watchdog.py >> /app/watchdog.log 2>&1
exit 0
