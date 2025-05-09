#!/bin/bash

# Change to the application directory
cd /home/app/powermining/code || { echo "Failed to change directory" > /home/app/powermining/code/logs/map_update.log; exit 1; }

# Define logs directory with absolute path
LOGS_DIR="/home/app/powermining/code/logs"

# Add timestamp to beginning of log
echo "========================================" >> ${LOGS_DIR}/map_update.log
echo "Map update started: $(date)" >> ${LOGS_DIR}/map_update.log

# Check if DATABASE_URL_EXTERNAL environment variable is set
if [ -z "$DATABASE_URL_EXTERNAL" ]; then
  echo "DATABASE_URL_EXTERNAL environment variable is not set, attempting to load from files..." >> ${LOGS_DIR}/map_update.log
  
  # Try to source environment from envs_export.sh (primary)
  if [ -f "../env/envs_export.sh" ]; then
    echo "Found envs_export.sh file, sourcing environment" >> ${LOGS_DIR}/map_update.log
    . "../env/envs_export.sh"
  # Fallback to dot.env if needed
  elif [ -f "../env/dot.env" ]; then
    echo "Found dot.env file, sourcing environment" >> ${LOGS_DIR}/map_update.log
    . "../env/dot.env"
  fi
  
  # Simple check if we have the variable now
  if [ -z "$DATABASE_URL_EXTERNAL" ]; then
    echo "ERROR: Failed to load DATABASE_URL_EXTERNAL from environment files" >> ${LOGS_DIR}/map_update.log
    echo "Map update failed: $(date)" >> ${LOGS_DIR}/map_update.log
    echo "========================================" >> ${LOGS_DIR}/map_update.log
    exit 1
  else
    echo "Successfully loaded DATABASE_URL_EXTERNAL from environment file" >> ${LOGS_DIR}/map_update.log
  fi
else
  echo "DATABASE_URL_EXTERNAL environment variable is already set" >> ${LOGS_DIR}/map_update.log
fi

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