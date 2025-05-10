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
            SELECT control_progress, timestamp, power_reinforcement, power_undermining, state_percent, control_points
            FROM power_history
            WHERE system_id64 = %s
            ORDER BY timestamp DESC
            LIMIT 1
        """, (system_id64,))
        
        prev_record = cursor.fetchone()
        
        # Check if we should add a new record (prevent too frequent updates)
        should_update = True
        
        # Calculate control points properly
        control_points = None
        
        # Method 1: Direct calculation if we have reinforcement and undermining values
        if power_reinforcement is not None and power_undermining is not None:
            control_points = power_reinforcement - power_undermining
            log_message("POWER", f"Control points calculated from R-U: {control_points}", level=3)
        
        # Method 2: Calculate from control_progress if available
        elif control_progress is not None:
            if control_progress < 0:
                # Negative progress means undermining
                control_points = int(control_progress * 120000)
                log_message("POWER", f"Control points calculated from negative progress: {control_points}", level=3)
            else:
                # Determine which band we're in based on control_progress value
                if control_progress < 1.0:
                    # Likely in Acquisition/contested phase (less than 100% Exploited)
                    control_points = int(control_progress * 120000)
                    log_message("POWER", f"Control points calculated from Acquisition progress: {control_points}", level=3)
                elif control_progress < 2.0:
                    # Likely in Exploited phase (100%-200% progress)
                    adjusted_progress = control_progress - 1.0  # Normalize to 0-1 range
                    control_points = 120000 + int(adjusted_progress * 333333)
                    log_message("POWER", f"Control points calculated from Exploited progress: {control_points}", level=3)
                elif control_progress < 3.0:
                    # Likely in Fortified phase (200%-300% progress)
                    adjusted_progress = control_progress - 2.0  # Normalize to 0-1 range
                    control_points = 453333 + int(adjusted_progress * 666667)
                    log_message("POWER", f"Control points calculated from Fortified progress: {control_points}", level=3)
                else:
                    # Likely in Stronghold phase (300%+ progress)
                    adjusted_progress = control_progress - 3.0  # Normalize to 0-1 range
                    control_points = 1120000 + int(adjusted_progress * 1000000)
                    log_message("POWER", f"Control points calculated from Stronghold progress: {control_points}", level=3)
        
        # Calculate state_percent based on control points
        state_percent = None
        if control_points is not None:
            if control_points < 0:
                # Undermined (negative control points)
                state_percent = round((control_points / 120000.0) * 100, 2)
            elif control_points < 120000:
                # Acquisition phase (0 to 119,999)
                state_percent = round((control_points / 120000.0) * 100, 2)
            elif control_points < 453333:
                # Exploited (120,000 to 453,332)
                state_percent = round(((control_points - 120000) / 333333.0) * 100, 2)
            elif control_points < 1120000:
                # Fortified (453,333 to 1,119,999)
                state_percent = round(((control_points - 453333) / 666667.0) * 100, 2)
            else:
                # Stronghold (1,120,000+)
                state_percent = round(((control_points - 1120000) / 1000000.0) * 100, 2)
        
        # Calculate trend_percent from previous state_percent
        trend_percent = None
        if state_percent is not None and prev_record and prev_record[4] is not None:
            trend_percent = round(state_percent - prev_record[4], 2)
            
        # Calculate cp_delta from previous control_points
        cp_delta = None
        if control_points is not None and prev_record and prev_record[5] is not None:
            cp_delta = control_points - prev_record[5]
            log_message("POWER", f"CP delta for {system_name}: {cp_delta:+} (from {prev_record[5]} to {control_points})", level=3)
        
        if prev_record:
            # Calculate trend if we have previous data
            if prev_record[0] is not None and control_progress is not None:
                # Calculate and round the trend to 3 decimal places
                raw_trend = control_progress - prev_record[0]
                trend = round(raw_trend, 3)  # Round to 3 decimal places
                
                # Use the rounded trend value for logging
                log_message("POWER", f"Trend for {system_name}: {trend:+.3f} (from {prev_record[0]:.3f} to {control_progress:.3f})", level=2)
            
            # Get the last update timestamp
            last_update_time = prev_record[1]
            
            # Calculate hours since last update
            hours_diff = (current_time - last_update_time).total_seconds() / 3600
            
            # Get previous values for comparison
            prev_control_progress = prev_record[0]
            prev_reinforcement = prev_record[2]
            prev_undermining = prev_record[3]
            
            # Determine if there's been a significant change
            significant_change = (
                # Control progress has changed by more than 1%
                (control_progress is not None and prev_control_progress is not None and abs(control_progress - prev_control_progress) > 0.01) or
                # Reinforcement value has changed
                (power_reinforcement is not None and prev_reinforcement is not None and power_reinforcement != prev_reinforcement) or
                # Undermining value has changed
                (power_undermining is not None and prev_undermining is not None and power_undermining != prev_undermining)
            )
            
            # Skip if less than 1 hour has passed AND there's no significant change
            if hours_diff < 1.0 and not significant_change:
                should_update = False
                log_message("POWER", f"Skipping {system_name} update - {hours_diff:.2f} hours since last update and no significant change", level=2)
        
        # Insert new record if needed
        if should_update:
            # Round control_progress to 3 decimal places for better display
            rounded_control_progress = round(control_progress, 3) if control_progress is not None else None
            
            cursor.execute("""
                INSERT INTO power_history (
                    timestamp, 
                    system_id64, 
                    power_id, 
                    powers_acquiring, 
                    control_progress, 
                    trend,
                    power_reinforcement, 
                    power_undermining,
                    control_points,
                    cp_delta,
                    state_percent,
                    trend_percent
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                current_time,
                system_id64,
                power_id,
                powers_acquiring if powers_acquiring else None,
                rounded_control_progress,  # Use the rounded value
                trend,  # Already rounded above
                power_reinforcement,
                power_undermining,
                control_points,
                cp_delta,
                state_percent,
                trend_percent
            ))
            
            # Log the record with new values
            state_info = ""
            if state_percent is not None:
                state_info = f", State: {state_percent:.2f}%"
                if trend_percent is not None:
                    state_info += f" ({trend_percent:+.2f}%)"
                    
            cp_info = f", CP: {control_points}" if control_points is not None else ""
            cp_delta_info = f" ({cp_delta:+})" if cp_delta is not None else ""
            log_message("POWER", f"Added power history for {system_name} - Trend: {trend:+.3f}{state_info}{cp_info}{cp_delta_info}", level=2)
            return True
        else:
            log_message("POWER", f"Skipped update for {system_name} (throttled)", level=3)
            
        return False
        
    except Exception as e:
        log_message("ERROR", f"Error updating power history for {system_name}: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False
