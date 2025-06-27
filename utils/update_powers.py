import json
import psycopg2
from datetime import datetime, timezone
from utils.update_log import log_message

# Power state mapping dictionary (updated for Powerplay 2.0)
POWER_STATE_MAPPING = {
    'Exploited': 1,
    'Controlled': 1,  # Map incorrect 'Controlled' to Exploited (legacy compatibility)
    'Fortified': 2,
    'Stronghold': 3,
    'InPrepareRadius': 4,
    'Prepared': 5,
    'Turmoil': 6,
    'Unoccupied': 7,
    'Contested': 8,   # Added missing state
    None: 0,          # Default for null
    '': 0             # Default for empty string
}

def update_power_history(conn, system_id64, system_name, controlling_power, powers, 
                        control_progress, power_reinforcement, power_undermining, power_state=None, timestamp=None):
    """
    Update the power_history table with the latest Powerplay metrics
    Will calculate trend based on previous records and manage hourly snapshots
    
    POWERPLAY 2.0 MECHANICS (correct as of 2025):
    - control_progress ranges 0.0-2.0, relative to current power_state
    - Key thresholds: 35k (contested), 120k (control), 453k (fortified), 1.12M (stronghold), 2.12M (max)
    - Band sizes: Exploited=333k, Fortified=667k, Stronghold=1M
    - control_progress 1.0 = enough merits to advance to next state
    
    Args:
        conn: Database connection (from the parent function)
        system_id64: System ID64 value
        system_name: Name of the system (for logging only)
        controlling_power: Name of the controlling power
        powers: List of powers contesting the system
        control_progress: PowerplayStateControlProgress value (0.0-2.0, relative to current state)
        power_reinforcement: PowerplayStateReinforcement value (raw control points)
        power_undermining: PowerplayStateUndermining value (raw control points) 
        power_state: PowerplayState string value (CRITICAL for correct control_progress interpretation)
        timestamp: Original EDDN timestamp (converted to database-compatible format). Defaults to current time if None.
        
    Returns:
        bool: True if record was added, False if skipped
    """
    # Skip if we don't have any meaningful Powerplay data at all  
    # Power state changes are also valuable historical data
    if (controlling_power is None and not powers and control_progress is None and 
        power_reinforcement is None and power_undermining is None and power_state is None):
        return False
            
    # DEBUG: Log incoming power data to track consistency between tables
    log_message("POWER", f"update_power_history received: system={system_name}, control_progress={control_progress}, power_reinforcement={power_reinforcement}, power_undermining={power_undermining}, power_state={power_state}", level=1)
    
    try:
        cursor = conn.cursor()
        
        # Get power_id from the powers table
        power_id = None
        if controlling_power:
            cursor.execute("SELECT id FROM powers WHERE name = %s", (controlling_power,))
            power_id_result = cursor.fetchone()
            if power_id_result:
                power_id = power_id_result[0]
        
        # Convert power_state string to integer using mapping
        power_state_int = POWER_STATE_MAPPING.get(power_state, 0)
        if power_state and power_state_int != 0:
            log_message("POWER", f"Mapped power state '{power_state}' to {power_state_int}", level=2)
        
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
        
        # Calculate control points correctly using power_state context
        control_points = None
        
        # Method 1: Direct calculation if we have reinforcement and undermining values
        if power_reinforcement is not None and power_undermining is not None:
            control_points = power_reinforcement - power_undermining
            log_message("POWER", f"Control points calculated from R-U: {control_points}", level=3)
        
        # Method 2: Calculate from control_progress + power_state (the correct way)
        elif control_progress is not None and power_state is not None:
            # Get power_state integer value
            power_state_int = POWER_STATE_MAPPING.get(power_state, 0)
            
            if power_state_int == 1:  # Exploited
                # control_progress 0.0-1.0 spans the 333,333 CP Exploited band
                # Base is 0, so control_points = progress * band_width
                control_points = int(control_progress * 333333)
                log_message("POWER", f"Control points calculated for Exploited state: {control_points}", level=3)
                
            elif power_state_int == 2:  # Fortified  
                # Base Fortified threshold = 453,333, band width = 666,667
                control_points = 453333 + int(control_progress * 666667)
                log_message("POWER", f"Control points calculated for Fortified state: {control_points}", level=3)
                
            elif power_state_int == 3:  # Stronghold
                # Base Stronghold threshold = 1,120,000, band width = 1,000,000
                control_points = 1120000 + int(control_progress * 1000000)
                log_message("POWER", f"Control points calculated for Stronghold state: {control_points}", level=3)
                
            elif power_state_int in [5, 6, 7, 8]:  # Prepared, Turmoil, Unoccupied, Contested
                # These states should NOT have control_progress data
                # If we see this combination, it's likely a data interpretation error
                log_message("POWER", f"WARNING: Unexpected control_progress {control_progress} for power_state {power_state} - these states shouldn't have progression data", level=1)
                control_points = None  # Don't calculate bogus values
                
            else:
                # Unknown state, use control_progress as-is scaled to 120k
                control_points = int(control_progress * 120000)
                log_message("POWER", f"Control points calculated for unknown state {power_state}: {control_points}", level=3)
        
        # Method 3: Fallback when we have control_progress but no power_state
        elif control_progress is not None:
            # Without power_state context, assume acquisition/unoccupied context (120k scale)
            control_points = int(control_progress * 120000)
            log_message("POWER", f"Control points calculated without power_state context: {control_points}", level=3)
        
        # Calculate state_percent correctly based on current power_state
        state_percent = None
        if control_progress is not None:
            # state_percent is simply control_progress converted to percentage
            # This represents percentage through the current state band
            state_percent = round(control_progress * 100, 2)
            log_message("POWER", f"State percent calculated: {state_percent}% (from control_progress {control_progress})", level=3)
        
        # Calculate trend_percent from previous state_percent
        trend_percent = None
        if state_percent is not None and prev_record and prev_record[4] is not None:
            # Convert decimal.Decimal to float if needed
            prev_state_percent = float(prev_record[4]) if prev_record[4] is not None else None
            trend_percent = round(state_percent - prev_state_percent, 2)
            
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
            hours_diff = (timestamp - last_update_time).total_seconds() / 3600
            
            # Get previous values for comparison
            prev_control_progress = prev_record[0]
            prev_reinforcement = prev_record[2]
            prev_undermining = prev_record[3]
            
            # Determine if there's been a significant change - DISABLED but kept for reference
            """
            significant_change = (
                # Control progress has changed by more than 1%
                (control_progress is not None and prev_control_progress is not None and abs(control_progress - prev_control_progress) > 0.01) or
                # Reinforcement value has changed
                (power_reinforcement is not None and prev_reinforcement is not None and power_reinforcement != prev_reinforcement) or
                # Undermining value has changed
                (power_undermining is not None and prev_undermining is not None and power_undermining != prev_undermining)
            )
            """
            # Override: Always consider it a significant change (disabling the check)
            significant_change = True
            
            # Always update if it's been at least an hour or if there's a significant change
            if hours_diff >= 1.0 or significant_change:
                should_update = True
                if significant_change:
                    log_message("POWER", f"Updating {system_name} - significant change detected", level=2)
                else:
                    log_message("POWER", f"Updating {system_name} - {hours_diff:.2f} hours since last update", level=2)
            else:
                # Skip if less than 1 hour has passed AND there's no significant change
                # This should never happen now that significant_change is always True
                should_update = False
                log_message("POWER", f"Skipping {system_name} update - {hours_diff:.2f} hours since last update", level=2)
        
        # Insert new record if needed
        if should_update:
            # Round control_progress to 3 decimal places for better display
            rounded_control_progress = round(control_progress, 3) if control_progress is not None else None
            
            cursor.execute("""
                INSERT INTO power_history (
                    timestamp, 
                    system_id64, 
                    power_id, 
                    power_state,
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
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (timestamp, system_id64) DO UPDATE SET
                    power_id = EXCLUDED.power_id,
                    power_state = EXCLUDED.power_state,
                    powers_acquiring = EXCLUDED.powers_acquiring,
                    control_progress = EXCLUDED.control_progress,
                    trend = EXCLUDED.trend,
                    power_reinforcement = EXCLUDED.power_reinforcement,
                    power_undermining = EXCLUDED.power_undermining,
                    control_points = EXCLUDED.control_points,
                    cp_delta = EXCLUDED.cp_delta,
                    state_percent = EXCLUDED.state_percent,
                    trend_percent = EXCLUDED.trend_percent
            """, (
                timestamp,
                system_id64,
                power_id,
                power_state_int,
                powers_acquiring if powers_acquiring else [],
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
            power_state_info = f", Power State: {power_state}({power_state_int})" if power_state else ""
            log_message("POWER", f"Added power history for {system_name} - Trend: {trend:+.3f}{state_info}{cp_info}{cp_delta_info}{power_state_info}", level=2)
            return True
        else:
            log_message("POWER", f"Skipped update for {system_name} (throttled)", level=3)
            
        return False
        
    except Exception as e:
        log_message("ERROR", f"Error updating power history for {system_name}: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False

def update_power_conflicts(conn, system_id64, system_name, conflict_progress_list, power_state=None, timestamp=None):
    """
    Update the power_conflicts table with ConflictProgress data
    
    Args:
        conn: Database connection (from the parent function)
        system_id64: System ID64 value
        system_name: Name of the system (for logging only)
        conflict_progress_list: List of {"ConflictProgress": float, "Power": string} dictionaries
        power_state: PowerplayState string value for context
        timestamp: Original EDDN timestamp (converted to database-compatible format)
        
    Returns:
        bool: True if record was added, False if skipped
    """
    if not conflict_progress_list or not isinstance(conflict_progress_list, list):
        return False
        
    log_message("CONFLICT", f"update_power_conflicts received: system={system_name}, conflicts={len(conflict_progress_list)}, power_state={power_state}", level=1)
    
    try:
        cursor = conn.cursor()
        
        # Convert power_state string to integer using mapping
        power_state_int = POWER_STATE_MAPPING.get(power_state, 0)
        if power_state and power_state_int != 0:
            log_message("CONFLICT", f"Mapped power state '{power_state}' to {power_state_int}", level=2)
        
        # Initialize all power columns to NULL
        power_columns = {
            'aisling_duval': None,
            'arissa_lavigny_duval': None,
            'archon_delaine': None,
            'denton_patreus': None,
            'edmund_mahon': None,
            'felicia_winters': None,
            'jerome_archer': None,
            'li_yong_rui': None,
            'nakato_kaine': None,
            'pranav_antal': None,
            'yuri_grom': None,
            'zemina_torval': None
        }
        
        # Map power names to database column names
        power_name_mapping = {
            'Aisling Duval': 'aisling_duval',
            'A. Lavigny-Duval': 'arissa_lavigny_duval',
            'Archon Delaine': 'archon_delaine',
            'Denton Patreus': 'denton_patreus',
            'Edmund Mahon': 'edmund_mahon',
            'Felicia Winters': 'felicia_winters',
            'Jerome Archer': 'jerome_archer',
            'Li Yong-Rui': 'li_yong_rui',
            'Nakato Kaine': 'nakato_kaine',
            'Pranav Antal': 'pranav_antal',
            'Yuri Grom': 'yuri_grom',
            'Zemina Torval': 'zemina_torval'
        }
        
        # Process each conflict progress entry
        for conflict_entry in conflict_progress_list:
            if not isinstance(conflict_entry, dict):
                continue
                
            power_name = conflict_entry.get("Power")
            conflict_progress = conflict_entry.get("ConflictProgress")
            
            if power_name is None or conflict_progress is None:
                continue
                
            # Map power name to column name
            column_name = power_name_mapping.get(power_name)
            if column_name:
                power_columns[column_name] = conflict_progress
                log_message("CONFLICT", f"  {power_name}: {conflict_progress}", level=2)
            else:
                log_message("CONFLICT", f"Unknown power name: {power_name}", level=1)
        
        # Check if we have any valid conflict data
        has_data = any(value is not None for value in power_columns.values())
        if not has_data:
            log_message("CONFLICT", f"No valid conflict data for {system_name}", level=2)
            return False
        
        # Insert the conflict record with UPSERT to handle duplicate timestamps
        cursor.execute("""
            INSERT INTO power_conflicts (
                timestamp, 
                system_id64, 
                power_state,
                aisling_duval,
                arissa_lavigny_duval,
                archon_delaine,
                denton_patreus,
                edmund_mahon,
                felicia_winters,
                jerome_archer,
                li_yong_rui,
                nakato_kaine,
                pranav_antal,
                yuri_grom,
                zemina_torval
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (timestamp, system_id64) DO UPDATE SET
                power_state = EXCLUDED.power_state,
                aisling_duval = EXCLUDED.aisling_duval,
                arissa_lavigny_duval = EXCLUDED.arissa_lavigny_duval,
                archon_delaine = EXCLUDED.archon_delaine,
                denton_patreus = EXCLUDED.denton_patreus,
                edmund_mahon = EXCLUDED.edmund_mahon,
                felicia_winters = EXCLUDED.felicia_winters,
                jerome_archer = EXCLUDED.jerome_archer,
                li_yong_rui = EXCLUDED.li_yong_rui,
                nakato_kaine = EXCLUDED.nakato_kaine,
                pranav_antal = EXCLUDED.pranav_antal,
                yuri_grom = EXCLUDED.yuri_grom,
                zemina_torval = EXCLUDED.zemina_torval
        """, (
            timestamp,
            system_id64,
            power_state_int,
            power_columns['aisling_duval'],
            power_columns['arissa_lavigny_duval'],
            power_columns['archon_delaine'],
            power_columns['denton_patreus'],
            power_columns['edmund_mahon'],
            power_columns['felicia_winters'],
            power_columns['jerome_archer'],
            power_columns['li_yong_rui'],
            power_columns['nakato_kaine'],
            power_columns['pranav_antal'],
            power_columns['yuri_grom'],
            power_columns['zemina_torval']
        ))
        
        # Count participating powers
        participating_powers = [name for name, value in power_columns.items() if value is not None]
        power_state_info = f", Power State: {power_state}({power_state_int})" if power_state else ""
        log_message("CONFLICT", f"Added power conflict for {system_name} - {len(participating_powers)} powers participating{power_state_info}", level=2)
        return True
        
    except Exception as e:
        log_message("ERROR", f"Error updating power conflicts for {system_name}: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False

def route_power_data(conn, system_id64, system_name, message, timestamp):
    """
    Route power data to the appropriate table based on data type
    
    Routing Logic:
    - If "PowerplayStateControlProgress" is NOT NULL → save to power_history
    - If "PowerplayConflictProgress" exists at all → save to power_conflicts
    - These are mutually exclusive - no cross-contamination
    
    Args:
        conn: Database connection 
        system_id64: System ID64 value
        system_name: Name of the system (for logging)
        message: EDDN message data containing power fields
        timestamp: Original EDDN timestamp (converted to database-compatible format)
        
    Returns:
        bool: True if any data was processed, False otherwise
    """
    # Extract power data from message
    control_progress = message.get("PowerplayStateControlProgress")
    conflict_progress = message.get("PowerplayConflictProgress")
    power_state = message.get("PowerplayState")
    
    # Route based on data type (mutually exclusive)
    if control_progress is not None:
        # This is power history data - route to power_history table
        log_message("ROUTE", f"Routing {system_name} to power_history (PowerplayStateControlProgress={control_progress})", level=2)
        
        # Extract other power history fields
        controlling_power = message.get("ControllingPower")
        powers = message.get("Powers", [])
        power_reinforcement = message.get("PowerplayStateReinforcement") 
        power_undermining = message.get("PowerplayStateUndermining")
        
        return update_power_history(
            conn=conn,
            system_id64=system_id64,
            system_name=system_name,
            controlling_power=controlling_power,
            powers=powers,
            control_progress=control_progress,
            power_reinforcement=power_reinforcement,
            power_undermining=power_undermining,
            power_state=power_state,
            timestamp=timestamp
        )
        
    elif conflict_progress is not None:
        # This is conflict data - route to power_conflicts table
        log_message("ROUTE", f"Routing {system_name} to power_conflicts ({len(conflict_progress)} conflicts)", level=2)
        
        return update_power_conflicts(
            conn=conn,
            system_id64=system_id64,
            system_name=system_name,
            conflict_progress_list=conflict_progress,
            power_state=power_state,
            timestamp=timestamp
        )
        
    else:
        # No power progression data found
        log_message("ROUTE", f"No power progression data found for {system_name}", level=3)
        return False
