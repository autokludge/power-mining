import json
import psycopg2
from datetime import datetime
from utils.update_log import log_message
from utils.update_powers import update_power_history

# ANSI color codes for consistent styling
YELLOW = '\033[93m'  # Default/Colony Ship color
RED = '\033[91m'     # Error color
RESET = '\033[0m'    # Reset color

def handle_colony_ship_event(message, event_type, DATABASE_URL):
    """Process colony ship events (Docked and FSSSignalDiscovered)
    
    Args:
        message (dict): Event data
        event_type (str): 'Docked' or 'FSSSignalDiscovered'
        DATABASE_URL (str): Database connection string
        
    Returns:
        bool: Success or failure
    """
    try:
        # Check if this is a colony ship event
        is_colony_ship = False
        
        if event_type == 'Docked':
            station_name = message.get('StationName', '')
            # Check both exact match and the formatted version
            is_colony_ship = (station_name == 'System Colonisation Ship' or 
                             station_name == '$EXT_PANEL_ColonisationShip:#index=1;')
        elif event_type == 'FSSSignalDiscovered':
            signal_name = message.get('SignalName', '')
            # Check both exact match and the formatted version
            is_colony_ship = (signal_name == 'System Colonisation Ship' or 
                             signal_name == '$EXT_PANEL_ColonisationShip:#index=1;')
        
        if not is_colony_ship:
            return False
        
        # Extract common fields
        system_id64 = message.get('SystemAddress')
        if not system_id64:
            log_message("COLONY", f"Missing SystemAddress in {event_type} event", level=1)
            return False
        
        # Get system name from database
        system_name = None
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT name
                    FROM systems
                    WHERE id64 = %s
                """, (system_id64,))
                row = cursor.fetchone()
                if row:
                    system_name = row[0]
        except Exception as e:
            log_message("ERROR", f"Failed to get system name for ID64 {system_id64}: {str(e)}", level=1)
        
        # Initialize database fields
        station_id = None
        station_name = None
        station_type = None
        station_faction = None
        station_government = None
        economy = None
        economies = None
        landing_pads = None
        signal_type = None
        
        if event_type == 'Docked':
            # Extract Docked event specific fields
            raw_station_name = message.get('StationName')
            # Standardize the station name
            station_name = 'System Colonisation Ship' if raw_station_name == '$EXT_PANEL_ColonisationShip:#index=1;' else raw_station_name
            station_type = message.get('StationType')
            station_id = message.get('MarketID')
            station_faction = message.get('StationFaction')
            station_government = message.get('StationGovernment_Localised')
            economy = message.get('StationEconomy_Localised')
            economies = message.get('StationEconomies')
            landing_pads = message.get('LandingPads')
            
            log_message("COLONY", f"✓ Docked at colony ship in {system_name or 'Unknown System'} (ID64: {system_id64})", level=1)
        elif event_type == 'FSSSignalDiscovered':
            # Extract FSSSignalDiscovered event specific fields
            raw_signal_name = message.get('SignalName')
            # Standardize the signal name
            station_name = 'System Colonisation Ship' if raw_signal_name == '$EXT_PANEL_ColonisationShip:#index=1;' else raw_signal_name
            signal_type = message.get('SignalType')
            
            log_message("COLONY", f"✓ Discovered colony ship in {system_name or 'Unknown System'} (ID64: {system_id64})", level=1)
        
        # Save to database
        return save_colony_ship_to_db(
            DATABASE_URL,
            system_id64=system_id64,
            station_id=station_id,
            station_name=station_name,
            station_type=station_type,
            station_faction=station_faction,
            station_government=station_government,
            economy=economy,
            economies=economies,
            landing_pads=landing_pads,
            signal_type=signal_type
        )
        
    except Exception as e:
        log_message("ERROR", f"Error processing colony ship event: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False

def save_colony_ship_to_db(DATABASE_URL, system_id64, station_name, station_id=None, station_type=None, 
                          station_faction=None, station_government=None, economy=None, 
                          economies=None, landing_pads=None, signal_type=None):
    """Save colony ship information to the database
    
    Args:
        DATABASE_URL (str): Database connection string
        system_id64 (int): The system ID
        station_name (str): Name of the station/ship
        station_id (int, optional): Market ID of station
        station_type (str, optional): Type of station
        station_faction (dict, optional): Faction data
        station_government (str, optional): Government type
        economy (str, optional): Primary economy
        economies (list, optional): List of economy data
        landing_pads (dict, optional): Landing pad info
        signal_type (str, optional): Type of signal
        
    Returns:
        bool: True on success, False on failure
    """
    try:
        if not system_id64 or not station_name:
            log_message("ERROR", "Missing required fields for colony ship database entry", level=1)
            return False
        
        # Transform economies data to the new format if provided
        transformed_economies = transform_economy_data(economies)
        
        # Convert JSON fields to strings if they're not None
        station_faction_json = json.dumps(station_faction) if station_faction else None
        economies_json = json.dumps(transformed_economies) if transformed_economies else (json.dumps(economies) if economies else None)
        landing_pads_json = json.dumps(landing_pads) if landing_pads else None
        
        # Start transaction
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            
            try:
                # Use an UPSERT pattern with ON CONFLICT to handle duplicates
                cursor.execute("""
                    INSERT INTO colony_systems (
                        system_id64, station_id, station_name, station_type,
                        station_faction, station_government, economy,
                        economies, landing_pads, signal_type,
                        first_seen, last_updated
                    ) VALUES (
                        %s, %s, %s, %s, 
                        %s::jsonb, %s, %s, 
                        %s::jsonb, %s::jsonb, %s,
                        NOW(), NOW()
                    )
                    ON CONFLICT (system_id64, station_name)
                    DO UPDATE SET 
                        station_id = COALESCE(EXCLUDED.station_id, colony_systems.station_id),
                        station_type = COALESCE(EXCLUDED.station_type, colony_systems.station_type),
                        station_faction = COALESCE(EXCLUDED.station_faction, colony_systems.station_faction),
                        station_government = COALESCE(EXCLUDED.station_government, colony_systems.station_government),
                        economy = COALESCE(EXCLUDED.economy, colony_systems.economy),
                        economies = COALESCE(EXCLUDED.economies, colony_systems.economies),
                        landing_pads = COALESCE(EXCLUDED.landing_pads, colony_systems.landing_pads),
                        signal_type = COALESCE(EXCLUDED.signal_type, colony_systems.signal_type),
                        last_updated = NOW()
                    RETURNING id, (xmax = 0) AS is_insert
                """, (
                    system_id64, station_id, station_name, station_type,
                    station_faction_json, station_government, economy,
                    economies_json, landing_pads_json, signal_type
                ))
                
                # Get the result to determine if this was an insert or update
                result = cursor.fetchone()
                if result:
                    record_id, is_insert = result
                    if is_insert:
                        log_message("COLONY", f"✓ Created new colony ship record in database (ID: {record_id})", level=1)
                    else:
                        log_message("COLONY", f"✓ Updated existing colony ship record in database (ID: {record_id})", level=1)
                else:
                    log_message("ERROR", "Failed to insert/update colony ship record - no result returned", level=1)
                    cursor.execute("ROLLBACK")
                    return False
                
                # Commit transaction
                conn.commit()
                return True
                
            except Exception as e:
                log_message("ERROR", f"Database error saving colony ship: {str(e)}", level=1)
                import traceback
                log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
                cursor.execute("ROLLBACK")
                return False
                
    except Exception as e:
        log_message("ERROR", f"Error saving colony ship to database: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False

def handle_saa_signals(message, DATABASE_URL):
    """Process SAASignalsFound events to track Haematite signals
    
    Args:
        message (dict): SAA signal event data
        DATABASE_URL (str): Database connection string
        
    Returns:
        bool: True if signals were processed, False otherwise
    """
    try:
        # Extract basic information
        timestamp = message.get("timestamp")
        body_name = message.get("BodyName")
        system_id64 = message.get("SystemAddress")
        body_id = message.get("BodyID")
        signals = message.get("Signals", [])
        
        # Validate required fields
        if not all([timestamp, body_name, system_id64, body_id, signals]):
            log_message("ERROR", f"Missing required fields in SAASignalsFound event", level=1)
            return False
        
        # Check if any signals are Haematite/Hematite (with various spellings)
        hematite_signals = []
        for signal in signals:
            signal_type = signal.get("Type", "")
            if signal_type.lower() in ["haematite", "hematite", "hamaetite", "hemaetite"]:
                hematite_signals.append(signal)
        
        # Only proceed if we found Hematite signals
        if not hematite_signals:
            log_message("DEBUG", f"No Haematite signals found in {body_name}", level=3)
            return False
        
        # Get system name from database
        system_name = None
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM systems WHERE id64 = %s", (system_id64,))
                result = cursor.fetchone()
                if result:
                    system_name = result[0]
        except Exception as e:
            log_message("ERROR", f"Error fetching system name: {str(e)}", level=1)
        
        if not system_name:
            system_name = f"Unknown System ({system_id64})"
        
        # Process hematite signals
        total_count = sum(signal.get("Count", 0) for signal in hematite_signals)
        log_message("HEMATITE", f"Found {total_count} Haematite signals on {body_name} in {system_name}", level=1)
        
        # Save each hematite signal to the database
        for signal in hematite_signals:
            signal_type = signal.get("Type", "")
            signal_count = signal.get("Count", 0)
            
            # Standardize to Haematite
            if signal_type.lower() in ["haematite", "hematite", "hamaetite", "hemaetite"]:
                signal_type = "Haematite"
            
            try:
                with psycopg2.connect(DATABASE_URL) as conn:
                    cursor = conn.cursor()
                    cursor.execute("BEGIN")
                    
                    # Check if signal exists already
                    cursor.execute("""
                        SELECT id, signal_count 
                        FROM haematite_signals 
                        WHERE system_id64 = %s AND body_name = %s AND mineral_type = %s
                    """, (system_id64, body_name, signal_type))
                    
                    result = cursor.fetchone()
                    if result:
                        # Signal exists, update if count has changed
                        signal_id, existing_count = result
                        if existing_count != signal_count:
                            cursor.execute("""
                                UPDATE haematite_signals 
                                SET signal_count = %s, last_updated = NOW()
                                WHERE id = %s
                            """, (signal_count, signal_id))
                            log_message("HEMATITE", f"Updated {signal_type} count for {body_name} from {existing_count} to {signal_count}", level=2)
                    else:
                        # New signal, insert it
                        cursor.execute("""
                            INSERT INTO haematite_signals 
                            (system_id64, body_name, mineral_type, signal_count, first_seen, last_updated)
                            VALUES (%s, %s, %s, %s, NOW(), NOW())
                        """, (system_id64, body_name, signal_type, signal_count))
                        log_message("HEMATITE", f"Added new {signal_type} signal for {body_name} with count {signal_count}", level=2)
                    
                    conn.commit()
            except Exception as e:
                log_message("ERROR", f"Error saving Haematite signal to database: {str(e)}", level=1)
                import traceback
                log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
                try:
                    conn.rollback()
                except:
                    pass
        
        return True
        
    except Exception as e:
        log_message("ERROR", f"Error processing SAASignalsFound event: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False

def save_system_from_fsdjump(message, DATABASE_URL, max_distance=2000.0):
    """
    Save or update system data from an FSDJump event
    Only saves systems within the specified distance from Sol (in light years)
    
    Args:
        message (dict): FSDJump event data
        DATABASE_URL (str): Database connection string
        max_distance (float): Maximum distance from Sol in light years (default: 2000)
        
    Returns:
        bool: True if system was saved, False if skipped or failed
    """
    # Extract essential system information
    system_name = message.get("StarSystem")
    system_id64 = message.get("SystemAddress")
    
    if not system_name or not system_id64:
        log_message("ERROR", f"Missing required system info in FSDJump event", level=1)
        return False
    
    # Extract coordinates
    coords = message.get("StarPos", [0, 0, 0])
    if len(coords) == 3:
        x, y, z = coords
    else:
        x = y = z = 0
    
    # Calculate distance from Sol
    distance_from_sol = ((x**2) + (y**2) + (z**2))**0.5
    
    # Skip systems beyond the distance limit
    if distance_from_sol > max_distance:
        log_message("SYSTEM", f"Skipping system {system_name} at {distance_from_sol:.1f} ly (beyond {max_distance} ly limit)", level=2)
        return False
    
    # Extract political data
    controlling_power = message.get("ControllingPower")
    power_state = message.get("PowerplayState")
    powers = message.get("Powers", [])
    
    # Extract Powerplay 2.0 metrics - NEW
    control_progress = message.get("PowerplayStateControlProgress")
    power_reinforcement = message.get("PowerplayStateReinforcement")
    power_undermining = message.get("PowerplayStateUndermining")
    
    # Log powerplay metrics if they exist
    if any([control_progress is not None, power_reinforcement is not None, power_undermining is not None]):
        log_message("POWER", f"Powerplay metrics for {system_name}: Progress={control_progress}, Reinforcement={power_reinforcement}, Undermining={power_undermining}", level=2)
    
    # DEBUG: Log the exact power data before updating either table
    log_message("POWER", f"save_system_from_fsdjump - Updating system={system_name}: control_progress={control_progress}, power_reinforcement={power_reinforcement}, power_undermining={power_undermining}", level=1)

    # Extract economy data
    primary_economy = message.get("SystemEconomy", "").replace("$economy_", "").replace(";", "")
    # Convert "Agri" to "Agriculture"
    if primary_economy == "Agri":
        primary_economy = "Agriculture"
        
    secondary_economy = message.get("SystemSecondEconomy", "").replace("$economy_", "").replace(";", "")
    # Convert "Agri" to "Agriculture"
    if secondary_economy == "Agri":
        secondary_economy = "Agriculture"
    
    # Extract security and government - correctly formatted from Journal format
    security = message.get("SystemSecurity", "")
    
    # Handle different security string formats
    if security.startswith("$SYSTEM_SECURITY_"):
        # Handle $SYSTEM_SECURITY_high/medium/low
        security_level = security[len("$SYSTEM_SECURITY_"):].rstrip(";").lower()
        # Capitalize the first letter
        security = security_level[0].upper() + security_level[1:]
    elif security.startswith("$GALAXY_MAP_INFO_state_"):
        # Handle $GALAXY_MAP_INFO_state_anarchy
        security = security[len("$GALAXY_MAP_INFO_state_"):].rstrip(";")
        # Capitalize the first letter
        security = security[0].upper() + security[1:]
    elif security.startswith("$GAlAXY_MAP_INFO_state_"):  # Handle with lowercase "l"
        # Handle variant with lowercase "l" in $GAlAXY_MAP_INFO_state_anarchy
        security = security[len("$GAlAXY_MAP_INFO_state_"):].rstrip(";")
        # Capitalize the first letter
        security = security[0].upper() + security[1:]
    
    government = message.get("SystemGovernment", "")
    if government.startswith("$government_"):
        government = government[len("$government_"):].rstrip(";")
    
    # Get current timestamp in UTC
    from datetime import datetime, timezone
    current_timestamp = datetime.now(timezone.utc)
    
    # If controlling power exists in powers list, remove it
    if controlling_power and isinstance(powers, list) and controlling_power in powers:
        powers = [p for p in powers if p != controlling_power]
    
    # Log operation
    log_message("SYSTEM", f"Saving system data for {system_name} (ID64: {system_id64}, distance: {distance_from_sol:.1f} ly)", level=2)
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            # Use UPSERT pattern for the system data
            cursor.execute("""
                INSERT INTO systems (
                    id64, name, x, y, z, distance_from_sol, 
                    controlling_power, power_state, powers_acquiring,
                    control_progress, power_reinforcement, power_undermining,
                    primary_economy, secondary_economy, security, 
                    government, last_updated
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, 
                    %s, %s, %s::jsonb,
                    %s, %s, %s,
                    %s, %s, %s,
                    %s, %s
                )
                ON CONFLICT (id64) DO UPDATE SET
                    name = EXCLUDED.name,
                    x = EXCLUDED.x,
                    y = EXCLUDED.y,
                    z = EXCLUDED.z,
                    distance_from_sol = EXCLUDED.distance_from_sol,
                    controlling_power = COALESCE(EXCLUDED.controlling_power, systems.controlling_power),
                    power_state = COALESCE(EXCLUDED.power_state, systems.power_state),
                    powers_acquiring = EXCLUDED.powers_acquiring,
                    control_progress = EXCLUDED.control_progress,
                    power_reinforcement = EXCLUDED.power_reinforcement,
                    power_undermining = EXCLUDED.power_undermining,
                    primary_economy = COALESCE(EXCLUDED.primary_economy, systems.primary_economy),
                    secondary_economy = COALESCE(EXCLUDED.secondary_economy, systems.secondary_economy),
                    security = COALESCE(EXCLUDED.security, systems.security),
                    government = COALESCE(EXCLUDED.government, systems.government),
                    last_updated = EXCLUDED.last_updated
                RETURNING id64
            """, (
                system_id64, system_name, x, y, z, distance_from_sol,
                controlling_power, power_state, json.dumps(powers),
                control_progress, power_reinforcement, power_undermining, 
                primary_economy, secondary_economy, security,
                government, current_timestamp
            ))
            
            # Update power history if we have any Powerplay data
            if controlling_power or powers or control_progress is not None or power_reinforcement is not None or power_undermining is not None:
                # DEBUG: Log the exact power data before calling update_power_history
                log_message("POWER", f"Calling update_power_history for {system_name} with control_progress={control_progress}, power_reinforcement={power_reinforcement}, power_undermining={power_undermining}", level=1)
                
                # Update power history with the same transaction
                update_power_history(
                    conn=conn,
                    system_id64=system_id64,
                    system_name=system_name,
                    controlling_power=controlling_power,
                    powers=powers,
                    control_progress=control_progress,
                    power_reinforcement=power_reinforcement,
                    power_undermining=power_undermining,
                    power_state=power_state
                )
            
            result = cursor.fetchone()
            if result:
                log_message("SYSTEM", f"✓ Successfully saved system {system_name}", level=1)
                return True
            else:
                log_message("ERROR", f"Failed to save system {system_name}", level=1)
                return False
                
    except Exception as e:
        log_message("ERROR", f"Database error saving system: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False

def transform_economy_data(economies_data):
    """Transform StationEconomies data from the raw game format to a simplified JSON object
    
    Converts from:
    [
        {"Name": "$economy_Extraction;", "Proportion": 0.23},
        {"Name": "$economy_Industrial;", "Proportion": 0.77}
    ]
    
    To:
    {"Extraction": 23.0, "Industrial": 77.0}
    
    Args:
        economies_data (list): List of economy dictionaries from EDDN
        
    Returns:
        dict: Simplified economy dictionary or None if conversion failed
    """
    if not economies_data or not isinstance(economies_data, list):
        return None
        
    try:
        result = {}
        for economy in economies_data:
            if not isinstance(economy, dict) or 'Name' not in economy or 'Proportion' not in economy:
                continue
                
            # Extract economy name from the format "$economy_Industrial;"
            name = economy['Name']
            if name.startswith('$economy_'):
                name = name[len('$economy_'):].rstrip(';')
                
            # Convert proportion to percentage and round to 1 decimal place to avoid floating-point errors
            proportion = round(float(economy['Proportion']) * 100, 1)
            
            # Add to result dictionary
            result[name] = proportion
            
        return result if result else None
        
    except Exception as e:
        log_message("ERROR", f"Error transforming economy data: {str(e)}", level=1)
        return None

def save_station_from_docked(message, DATABASE_URL):
    """
    Save station data from a Docked event
    Only saves the station if:
    1. We have a matching system in the database (by SystemAddress)
    2. We don't already have this station (by MarketID) in the database
    3. Station is not a Fleet Carrier
    
    Args:
        message (dict): Docked event data
        DATABASE_URL (str): Database connection string
        
    Returns:
        bool: True if station was saved or already exists, False if failed
    """
    # Extract essential station information
    station_name = message.get("StationName")
    market_id = message.get("MarketID")
    system_id64 = message.get("SystemAddress")
    station_type = message.get("StationType")
    
    # Skip Fleet Carriers
    if station_type == "FleetCarrier":
        log_message("STATION", f"Skipping Fleet Carrier {station_name}", level=2)
        return True
    
    # Validate required fields
    if not all([station_name, market_id, system_id64]):
        log_message("ERROR", f"Missing required station info in Docked event", level=1)
        return False
    
    # Extract other station details
    primary_economy = None
    station_economy = message.get("StationEconomy")
    if station_economy:
        # Parse economy string correctly
        if station_economy.startswith("$economy_"):
            primary_economy = station_economy[len("$economy_"):].rstrip(";")
        else:
            primary_economy = station_economy
    
    distance_to_arrival = message.get("DistFromStarLS")
    
    # Determine landing pad size based on LandingPads data
    landing_pad_size = None
    landing_pads = message.get("LandingPads")
    if landing_pads:
        if landing_pads.get("Large", 0) > 0:
            landing_pad_size = "Large"
        elif landing_pads.get("Medium", 0) > 0:
            landing_pad_size = "Medium"
        elif landing_pads.get("Small", 0) > 0:
            landing_pad_size = "Small"
    
    # Extract economies data and transform it
    economies = message.get("StationEconomies")
    transformed_economies = transform_economy_data(economies)
    
    # Convert to JSON string for database
    economies_json = json.dumps(transformed_economies) if transformed_economies else json.dumps(economies)
    
    # Get current timestamp
    from datetime import datetime, timezone
    current_timestamp = datetime.now(timezone.utc)
    
    # Determine if station has a market based on services
    has_market = False
    station_services = message.get("StationServices", [])
    if "Commodities" in station_services:
        has_market = True
    
    # The Body field is not available in the Docked event - set to null for database
    body = None
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            # First, check if system exists
            cursor.execute("SELECT id64 FROM systems WHERE id64 = %s", (system_id64,))
            system_result = cursor.fetchone()
            
            if not system_result:
                log_message("STATION", f"Cannot save station {station_name} - system ID {system_id64} does not exist in the database", level=1)
                return False
            
            # Check if station already exists
            cursor.execute("SELECT station_id FROM stations WHERE station_id = %s AND system_id64 = %s", 
                          (market_id, system_id64))
            station_result = cursor.fetchone()
            
            if station_result:
                # Station already exists, update economies and return
                cursor.execute("UPDATE stations SET economies = %s::jsonb WHERE system_id64 = %s AND station_id = %s", 
                             (economies_json, system_id64, market_id))
                log_message("STATION", f"Updated economies for station {station_name}", level=2)
                return True
            
            # Insert new station
            cursor.execute("""
                INSERT INTO stations (
                    system_id64, station_id, station_name, station_type,
                    primary_economy, distance_to_arrival, landing_pad_size,
                    update_time, economies, has_market, body
                ) VALUES (
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s::jsonb, %s, %s
                )
                RETURNING station_id
            """, (
                system_id64, market_id, station_name, station_type,
                primary_economy, distance_to_arrival, landing_pad_size,
                current_timestamp, economies_json, has_market, body
            ))
            
            result = cursor.fetchone()
            if result:
                log_message("STATION", f"✓ Successfully saved new station {station_name} (ID: {market_id}) in system {system_id64}", level=1)
                return True
            else:
                log_message("ERROR", f"Failed to save station {station_name}", level=1)
                return False
                
    except Exception as e:
        log_message("ERROR", f"Database error saving station: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False

def update_station_body_from_location(message, DATABASE_URL):
    """
    Minimal function to update a station's body data from Location event
    Updates the body field ONLY IF it is currently NULL in the database
    Does nothing else - no other fields are touched
    
    Args:
        message (dict): Location event data (from section 4.12 in Journal Manual)
        DATABASE_URL (str): Database connection string
        
    Returns:
        bool: True if body was updated, False otherwise
    """
    # Check if this is a valid Location event while docked at a station
    if not message.get("Docked") or not message.get("StationName") or not message.get("Body"):
        return False

    # Extract essential information
    station_name = message.get("StationName")
    system_id64 = message.get("SystemAddress")
    body = message.get("Body")
    
    # Validate we have the required fields
    if not all([station_name, system_id64, body]):
        return False
    
    try:
        with psycopg2.connect(DATABASE_URL) as conn:
            cursor = conn.cursor()
            
            # Find the station and check if body is NULL
            cursor.execute("""
                SELECT station_id
                FROM stations
                WHERE system_id64 = %s 
                AND station_name = %s 
                AND body IS NULL
            """, (system_id64, station_name))
            
            result = cursor.fetchone()
            
            # If we found a station with a NULL body field, update it
            if result:
                station_id = result[0]
                
                cursor.execute("""
                    UPDATE stations
                    SET body = %s
                    WHERE system_id64 = %s
                    AND station_id = %s
                    RETURNING station_id
                """, (body, system_id64, station_id))
                
                if cursor.rowcount > 0:
                    log_message("STATION", f"✓ Updated body to '{body}' for station {station_name} in system {system_id64}", level=1)
                    return True
                    
            # No update was needed or station wasn't found
            return False
            
    except Exception as e:
        log_message("ERROR", f"Database error updating station body: {str(e)}", level=1)
        return False

def handle_system_factions(message, DATABASE_URL):
    """Process faction data from FSDJump and Location events
    
    Args:
        message (dict): FSDJump or Location event data
        DATABASE_URL (str): Database connection string
        
    Returns:
        bool: True if factions were processed, False otherwise
    """
    try:
        # Only process FSDJump or Location events
        event = message.get("event", "")
        if event not in ["FSDJump", "Location"]:
            return False

        # Extract required fields
        system_name = message.get("StarSystem", "")
        system_id64 = message.get("SystemAddress")
        
        if not system_name or not system_id64:
            log_message("FACTION", f"Missing system info in {event} event - Name: {system_name}, ID64: {system_id64}", level=2)
            return False
            
        # Extract system faction (controlling faction)
        system_faction_data = message.get("SystemFaction")
        if not system_faction_data or not isinstance(system_faction_data, dict):
            log_message("FACTION", f"No SystemFaction data in {event} event for system {system_name}", level=2)
            return False
            
        controlling_faction = system_faction_data.get("Name")
        if not controlling_faction:
            log_message("FACTION", f"No controlling faction name in {event} event for system {system_name}", level=2)
            return False
            
        log_message("FACTION", f"Processing factions for {system_name} (Controlling: {controlling_faction})", level=2)
            
        # Get all factions data
        factions = message.get("Factions", [])
        if not factions:
            log_message("FACTION", f"No Factions data in {event} event for system {system_name}", level=2)
            return False
            
        # Store entire factions array as JSONB
        all_factions_json = json.dumps(factions)
            
        # Find active states for controlling faction
        active_states = []
        for faction in factions:
            if faction.get("Name") == controlling_faction:
                faction_states = faction.get("ActiveStates", [])
                for state in faction_states:
                    if isinstance(state, dict) and "State" in state:
                        active_states.append(state["State"])
                break
                
        log_message("FACTION", f"Active states for {controlling_faction}: {active_states}", level=2)
        
        # Convert active states to JSONB
        active_states_json = json.dumps(active_states)
            
        # Get current timestamp
        current_timestamp = datetime.now()
            
        # Update database with faction data
        try:
            with psycopg2.connect(DATABASE_URL) as conn:
                cursor = conn.cursor()
                
                cursor.execute("""
                    UPDATE systems
                    SET controlling_faction = %s,
                        active_states = %s::jsonb,
                        all_factions = %s::jsonb,
                        last_updated = %s
                    WHERE id64 = %s
                    RETURNING id64
                """, (controlling_faction, active_states_json, all_factions_json, current_timestamp, system_id64))
                
                if cursor.rowcount > 0:
                    log_message("FACTION", f"✓ Updated faction data for {system_name} from {event} event: controlling={controlling_faction}, states={active_states}", level=1)
                    return True
                else:
                    log_message("FACTION", f"System {system_name} not found in database", level=2)
                    return False
                    
        except Exception as e:
            log_message("ERROR", f"Database error updating faction data: {str(e)}", level=1)
            import traceback
            log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
            return False
            
    except Exception as e:
        log_message("ERROR", f"Error processing faction data: {str(e)}", level=1)
        import traceback
        log_message("ERROR", f"Traceback: {traceback.format_exc()}", level=1)
        return False
