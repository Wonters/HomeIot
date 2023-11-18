#!/bin/bash
# This script is launch from crontab

export DOMEO_IP=192.168.1.97
export DOMEO_PORT=8899
export MONGO_ADDRESS=mongodb://db:27017

source /etc/profile
cd /app/
python -c "from domeo import save, retrieve; save(retrieve())" >> /app/cron.log 2>&1
exit 0