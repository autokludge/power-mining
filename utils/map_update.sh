#!/bin/bash

# Change to the application directory
cd /home/app/powermining/code || { echo "Failed to change directory" > /home/app/powermining/code/logs/map_update.log; exit 1; }

# Define logs directory with absolute path
LOGS_DIR="/home/app/powermining/code/logs"

# Add timestamp to beginning of log
echo "========================================" >> ${LOGS_DIR}/map_update.log
echo "Map update started: $(date)" >> ${LOGS_DIR}/map_update.log

# Run the command and log output
python3 utils/dump_powerplay.py --db "$DATABASE_URL_EXTERNAL" --no-hudson 2>&1 >> ${LOGS_DIR}/map_update.log
if [ $? -eq 0 ]; then
  echo "Dump successful" >> ${LOGS_DIR}/map_update.log
else
  echo "Error: Dump failed with exit code $?" >> ${LOGS_DIR}/map_update.log
fi

# Compress the file and log output
gzip -k -v -9 -f json/powerplay.json 2>&1 >> ${LOGS_DIR}/map_update.log
if [ $? -eq 0 ]; then
  echo "Compression successful" >> ${LOGS_DIR}/map_update.log
else
  echo "Error: Compression failed with exit code $?" >> ${LOGS_DIR}/map_update.log
fi

echo "Map update finished: $(date)" >> ${LOGS_DIR}/map_update.log
echo "========================================" >> ${LOGS_DIR}/map_update.log