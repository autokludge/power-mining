#!/bin/bash

pwd

# Change to the application directory
cd /code || { exit 1; }

# Check if DATABASE_URL environment variable is set
if [ -z "$DATABASE_URL" ]; then
  # Try to source environment from envs_export.sh (primary)
  if [ -f "../env/envs_export.sh" ]; then
    . "../env/envs_export.sh"
  # Fallback to dot.env if needed
  elif [ -f "../env/dot.env" ]; then
    . "../env/dot.env"
  fi
  
  # Simple check if we have the variable now
  if [ -z "$DATABASE_URL" ]; then
    exit 1
  fi
fi

# Run the pruning script
python3 utils/prune_power_history.py