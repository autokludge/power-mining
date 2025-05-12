#!/bin/bash

pwd
LOGFILE="logs/map.log"
#mkdir -p /code/logs

if touch "$LOGFILE" && [ -w "$LOGFILE" ]; then
  CAN_LOG=1
else
  CAN_LOG=0
fi

log() {
  if [ "$CAN_LOG" -eq 1 ]; then
    echo "$1" >> "$LOGFILE"
  else
    echo "$1"
  fi
}

log "[prune_runner] Started at $(date)"

while true; do
  log "[prune_runner] Running prune_power_history.sh at $(date)"
  sh /code/utils/prune_power_history.sh 2>&1 | while read -r line; do log "[prune_runner] $line"; done
  sleep 86400
done
