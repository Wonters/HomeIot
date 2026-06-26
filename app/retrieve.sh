#!/bin/bash
# This script is launch from crontab

source /etc/profile
cd /app/
python -c "from domeo import save, retrieve; save(retrieve())" >> /app/cron.log 2>&1
exit 0