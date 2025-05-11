#!/bin/bash

echo "[map_update_runner] Started at $(date)"

while true; do
  echo "[map_update_runner] Running map_update.sh at $(date)"
  sh /code/utils/map_update.sh >> /code/logs/map.log 2>&1
  sleep 900  # 15 minutes
done