#!/bin/bash

pwd

while true; do
  sh /code/utils/prune_power_history.sh
  sleep 86400
done
