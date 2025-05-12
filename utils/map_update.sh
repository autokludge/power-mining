#!/bin/bash

pwd

# Change to the application directory
cd /code || { exit 1; }

# Check if DATABASE_URL_EXTERNAL environment variable is set
if [ -z "$DATABASE_URL_EXTERNAL" ]; then
  # Try to source environment from envs_export.sh (primary)
  if [ -f "../env/envs_export.sh" ]; then
    . "../env/envs_export.sh"
  # Fallback to dot.env if needed
  elif [ -f "../env/dot.env" ]; then
    . "../env/dot.env"
  fi
  
  # Simple check if we have the variable now
  if [ -z "$DATABASE_URL_EXTERNAL" ]; then
    exit 1
  fi
fi

# Run the command
python3 utils/dump_powerplay.py --db "$DATABASE_URL_EXTERNAL" --no-hudson

# Compress the file
gzip -k -v -9 -f json/powerplay.json