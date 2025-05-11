#!/bin/bash

echo "[prune_history] Started at $(date)"

while true; do
  echo "[prune_history] Running prune_power_history.sh at $(date)"
  sh /code/utils/prune_power_history.sh >> /code/logs/prune.log 2>&1
  sleep 86400  # 24 hours
done