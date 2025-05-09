import json
import psycopg2
from datetime import datetime, timezone
from utils.update_log import log_message

def update_power_history(conn, system_id64, system_name, controlling_power, powers, 
                        control_progress, power_reinforcement, power_undermining):
    """
    Update the power_history table with the latest Powerplay metrics
    Will calculate trend based on previous records and manage hourly snapshots
    
    Args:
        conn: Database connection (from the parent function)
        system_id64: System ID64 value
        system_name: Name of the system (for logging only)
        controlling_power: Name of the controlling power
        powers: List of powers contesting the system
        control_progress: PowerplayStateControlProgress value
        power_reinforcement: PowerplayStateReinforcement value
        power_undermining: PowerplayStateUndermining value
        
    Returns:
        bool: True if record was added, False if skipped
    """
    # Skip if we don't have any Powerplay metrics at all
    if controlling_power is None and not powers and control_progress is None and power_reinforcement is None and power_undermining is None:
        return False
        
    # Current timestamp
    current_time = datetime.now(timezone.utc)
    
    try:
        cursor = conn.cursor()
        
        # Get power_id from the powers table
        power_id = None
        if controlling_power:
            cursor.execute("SELECT id FROM powers WHERE name = %s", (controlling_power,))
            power_id_result = cursor.fetchone()
            if power_id_result:
                power_id = power_id_result[0]
        
        # Convert powers list to powers_acquiring array of IDs
        powers_acquiring = []
        if powers and isinstance(powers, list) and len(powers) > 0:
            # Remove controlling power from powers list if it's there
            powers_filtered = [p for p in powers if p != controlling_power]
            
            # Only proceed if we have powers to map
            if powers_filtered:
                # Convert names to IDs using the powers table
                placeholders = ', '.join(['%s'] * len(powers_filtered))
                cursor.execute(f"SELECT id FROM powers WHERE name IN ({placeholders})", tuple(powers_filtered))
                power_ids = cursor.fetchall()
                if power_ids:
                    powers_acquiring = [pid[0] for pid in power_ids]
        
        # Calculate trend: find the most recent record for this system
        trend = 0.0
        cursor.execute("""
            SELECT control_progress
            FROM power_history
            WHERE system_id64 = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (system_id64,))
        
        prev_record = cursor.fetchone()
        if prev_record and prev_record[0] is not None and control_progress is not None:
            # Calculate change from previous value
            trend = control_progress - prev_record[0]
            log_message("POWER", f"Trend for {system_name}: {trend:+.6f} (from {prev_record[0]:.6f} to {control_progress:.6f})", level=2)
        
        # Check if we should add a new record (prevent too frequent updates)
        should_update = True
        cursor.execute("""
            SELECT timestamp
            FROM power_history
            WHERE system_id64 = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (system_id64,))
        
        last_update = cursor.fetchone()
        if last_update:
            # Calculate hours since last update
            hours_diff = (current_time - last_update[0]).total_seconds() / 3600
            
            # Skip if less than 1 hour has passed AND the values haven't changed significantly
            if hours_diff < 1.0:
                # Check if there's been a significant change in control_progress
                cursor.execute("""
                    SELECT control_progress, power_reinforcement, power_undermining
                    FROM power_history
                    WHERE system_id64 = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                """, (system_id64,))
                
                last_values = cursor.fetchone()
                # Only skip if the values are similar
                if last_values and abs(trend) < 0.01:
                    should_update = False
                    log_message("POWER", f"Skipping {system_name} update - less than 1 hour and no significant change", level=3)
        
        # Insert new record if needed
        if should_update:
            cursor.execute("""
                INSERT INTO power_history (
                    timestamp, 
                    system_id64, 
                    power_id, 
                    powers_acquiring, 
                    control_progress, 
                    trend,
                    power_reinforcement, 
                    power_undermining
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                current_time,
                system_id64,
                power_id,
                powers_acquiring if powers_acquiring else None,
                control_progress,
                trend,
                power_reinforcement,
                power_undermining
            ))
            
            log_message("POWER", f"Added power history record for {system_name} - Trend: {trend:+.6f}", level=2)
            return True
            
        return False
        
    except Exception as e:
        log_message("ERROR", f"Error updating power history for {system_name}: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False
