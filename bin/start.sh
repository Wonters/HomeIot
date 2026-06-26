#!/bin/bash
printenv | grep -E '^(DOMEO_IP|DOMEO_PORT|MONGO_ADDRESS)=' >> /etc/environment
service cron start
exec /start.sh
