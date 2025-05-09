#!/usr/bin/env python3
"""
Power History Pruning Script

This script implements the tiered retention policy for power_history table:
- Keep hourly data for the last 7 days
- Keep daily data for days 8-360
- Keep weekly data beyond that

Should be run via cron job once per day during low-traffic hours.
"""

import os
import sys
import psycopg2
import traceback
from datetime import datetime

# Add the parent directory to the path to import our modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.update_log import log_message

def prune_power_history():
    """
    Main function to prune old power history records according to retention policy
    """
    # Get database connection string from environment
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        print("ERROR: DATABASE_URL environment variable is not set")
        return 1

    start_time = datetime.now()
    print(f"Power history pruning started at {start_time}")
    log_message("PRUNE", "Starting power history pruning", level=1)
    
    try:
        with psycopg2.connect(database_url) as conn:
            cursor = conn.cursor()
            
            # Start transaction
            cursor.execute("BEGIN")
            
            # Step 1: Delete excessive hourly records from past week
            # Keep only records at the start of each hour (minute, second = 0, 0)
            cursor.execute("""
                WITH hourly_candidates AS (
                    SELECT timestamp, system_id64,
                           ROW_NUMBER() OVER (PARTITION BY system_id64, 
                                             DATE_TRUNC('hour', timestamp) 
                                      ORDER BY timestamp) AS rn
                    FROM power_history
                    WHERE timestamp > NOW() - INTERVAL '7 days'
                      AND timestamp < NOW() - INTERVAL '1 hour'
                      AND NOT (EXTRACT(MINUTE FROM timestamp) = 0 AND 
                             EXTRACT(SECOND FROM timestamp) < 10)
                )
                DELETE FROM power_history
                WHERE (timestamp, system_id64) IN 
                    (SELECT timestamp, system_id64 FROM hourly_candidates WHERE rn > 1)
            """)
            
            hourly_pruned = cursor.rowcount
            log_message("PRUNE", f"Pruned {hourly_pruned} hourly records", level=1)
            
            # Step 2: For data 7-360 days old, keep one record per day
            cursor.execute("""
                WITH daily_candidates AS (
                    SELECT timestamp, system_id64,
                           ROW_NUMBER() OVER (PARTITION BY system_id64, 
                                             DATE_TRUNC('day', timestamp) 
                                      ORDER BY timestamp) AS rn
                    FROM power_history
                    WHERE timestamp BETWEEN NOW() - INTERVAL '360 days' AND NOW() - INTERVAL '7 days'
                      AND NOT (EXTRACT(HOUR FROM timestamp) = 0 AND 
                             EXTRACT(MINUTE FROM timestamp) = 0)
                )
                DELETE FROM power_history
                WHERE (timestamp, system_id64) IN 
                    (SELECT timestamp, system_id64 FROM daily_candidates WHERE rn > 1)
            """)
            
            daily_pruned = cursor.rowcount
            log_message("PRUNE", f"Pruned {daily_pruned} daily records", level=1)
            
            # Step 3: For data older than 360 days, keep one record per week
            cursor.execute("""
                WITH weekly_candidates AS (
                    SELECT timestamp, system_id64,
                           ROW_NUMBER() OVER (PARTITION BY system_id64, 
                                             DATE_TRUNC('week', timestamp) 
                                      ORDER BY timestamp) AS rn
                    FROM power_history
                    WHERE timestamp < NOW() - INTERVAL '360 days'
                      AND NOT (EXTRACT(DOW FROM timestamp) = 0 AND
                             EXTRACT(HOUR FROM timestamp) = 0)
                )
                DELETE FROM power_history
                WHERE (timestamp, system_id64) IN 
                    (SELECT timestamp, system_id64 FROM weekly_candidates WHERE rn > 1)
            """)
            
            weekly_pruned = cursor.rowcount
            log_message("PRUNE", f"Pruned {weekly_pruned} weekly records", level=1)
            
            # Commit changes
            conn.commit()
            
            total_pruned = hourly_pruned + daily_pruned + weekly_pruned
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            log_message("PRUNE", f"Completed power history pruning: {total_pruned} total records removed in {duration:.1f} seconds", level=1)
            print(f"Pruned {total_pruned} records: {hourly_pruned} hourly, {daily_pruned} daily, {weekly_pruned} weekly")
            print(f"Power history pruning completed at {end_time} (duration: {duration:.1f} seconds)")
            
            return 0
            
    except Exception as e:
        log_message("ERROR", f"Error pruning power history: {str(e)}", level=1)
        traceback.print_exc()
        print(f"ERROR: {str(e)}")
        print(traceback.format_exc())
        return 1

if __name__ == "__main__":
    sys.exit(prune_power_history()) 