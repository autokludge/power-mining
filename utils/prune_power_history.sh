#!/bin/bash

pwd

# Change to the application directory
cd /code || { echo "Failed to change directory" > /code/logs/prune_history.log; exit 1; }

# Define logs directory with absolute path
LOGS_DIR="../logs"

# Add timestamp to beginning of log
echo "========================================" >> ${LOGS_DIR}/prune_history.log
echo "Power history pruning started: $(date)" >> ${LOGS_DIR}/prune_history.log

# Check if DATABASE_URL environment variable is set
if [ -z "$DATABASE_URL" ]; then
  echo "DATABASE_URL environment variable is not set, attempting to load from files..." >> ${LOGS_DIR}/prune_history.log
  
  # Try to source environment from envs_export.sh (primary)
  if [ -f "../env/envs_export.sh" ]; then
    echo "Found envs_export.sh file, sourcing environment" >> ${LOGS_DIR}/prune_history.log
    . "../env/envs_export.sh"
  # Fallback to dot.env if needed
  elif [ -f "../env/dot.env" ]; then
    echo "Found dot.env file, sourcing environment" >> ${LOGS_DIR}/prune_history.log
    . "../env/dot.env"
  fi
  
  # Simple check if we have the variable now
  if [ -z "$DATABASE_URL" ]; then
    echo "ERROR: Failed to load DATABASE_URL from environment files" >> ${LOGS_DIR}/prune_history.log
    echo "Power history pruning failed: $(date)" >> ${LOGS_DIR}/prune_history.log
    echo "========================================" >> ${LOGS_DIR}/prune_history.log
    exit 1
  else
    echo "Successfully loaded DATABASE_URL from environment file" >> ${LOGS_DIR}/prune_history.log
  fi
else
  echo "DATABASE_URL environment variable is already set" >> ${LOGS_DIR}/prune_history.log
fi

# Run the pruning script and log output
python3 utils/prune_power_history.py 2>&1 >> ${LOGS_DIR}/prune_history.log
if [ $? -eq 0 ]; then
  echo "Power history pruning completed successfully" >> ${LOGS_DIR}/prune_history.log
else
  echo "Error: Power history pruning failed with exit code $?" >> ${LOGS_DIR}/prune_history.log
fi

echo "Power history pruning finished: $(date)" >> ${LOGS_DIR}/prune_history.log
echo "========================================" >> ${LOGS_DIR}/prune_history.log 