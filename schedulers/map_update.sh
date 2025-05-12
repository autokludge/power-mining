#!/bin/bash

pwd
LOGFILE="logs/map.log"
# mkdir -p /code/logs

# Try to open log file manually
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

log "[map_update_runner] Started at $(date)"

while true; do
  log "[map_update_runner] Running map_update.sh at $(date)"
  sh /code/utils/map_update.sh 2>&1 | while read -r line; do log "[map_update_runner] $line"; done
  sleep 900
done
