from flask import Blueprint, jsonify, request
import psycopg2
from utils.common import get_db_connection
from utils.map import find_systems_in_range, get_system_details, find_acquisition_systems
from utils.analytics import track_search

# Constants for acquisition search
FORTIFIED_RANGE = 20.0
STRONGHOLD_RANGE = 30.0

discord_api_bp = Blueprint('discord_api', __name__)

@discord_api_bp.route('/api/discord/system/<path:system_identifier>')
def get_discord_system(system_identifier):
    """Get detailed system information by name or id64"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500

        cur = conn.cursor()
        
        # Try to parse as id64 first
        try:
            id64 = int(system_identifier)
            where_clause = "s.id64 = %s"
            print(f"Using id64 where clause: {where_clause} with value {id64}")
        except ValueError:
            # If not a number, treat as system name (case-insensitive)
            where_clause = "LOWER(s.name) = LOWER(%s)"
            print(f"Using name where clause: {where_clause} with value {system_identifier}")
        
        # Get system info with stations and commodities
        cur.execute(f"""
            WITH system_stations AS (
                SELECT 
                    st.*,
                    json_agg(
                        json_build_object(
                            'name', sc.commodity_name,
                            'demand', sc.demand,
                            'sellPrice', sc.sell_price
                        )
                    ) FILTER (WHERE sc.commodity_name IS NOT NULL) as commodities
                FROM systems s
                LEFT JOIN stations st ON s.id64 = st.system_id64
                LEFT JOIN station_commodities sc 
                    ON st.system_id64 = sc.system_id64 
                    AND st.station_id = sc.station_id
                WHERE {where_clause}
                GROUP BY st.system_id64, st.station_id, st.station_name, st.station_type, st.landing_pad_size, 
                         st.distance_to_arrival, st.update_time, st.primary_economy, st.body
            ), mineral_signals AS (
                SELECT 
                    ms.system_id64,
                    ms.body_name,
                    ms.ring_name,
                    ms.ring_type,
                    ms.mineral_type,
                    ms.signal_count,
                    ms.reserve_level
                FROM mineral_signals ms
                JOIN systems s ON s.id64 = ms.system_id64
                WHERE {where_clause}
                ORDER BY ms.ring_name, ms.mineral_type
            )
            SELECT 
                s.id64,
                s.name,
                s.x,
                s.y,
                s.z,
                s.controlling_power,
                s.power_state,
                s.powers_acquiring,
                s.distance_from_sol,
                COALESCE(NULLIF(s.system_state, 'NULL'), 'None') as system_state,
                s.population,
                COALESCE(
                    json_agg(DISTINCT jsonb_build_object(
                        'name', ss.station_name,
                        'id', ss.station_id,
                        'updateTime', ss.update_time,
                        'distanceToArrival', ss.distance_to_arrival,
                        'primaryEconomy', ss.primary_economy,
                        'body', ss.body,
                        'type', ss.station_type,
                        'landingPads', ss.landing_pad_size,
                        'market', jsonb_build_object(
                            'commodities', ss.commodities
                        )
                    )) FILTER (WHERE ss.station_name IS NOT NULL),
                    '[]'::json
                ) as stations,
                COALESCE(
                    json_agg(DISTINCT jsonb_build_object(
                        'body_name', ms.body_name,
                        'ring_name', ms.ring_name,
                        'ring_type', ms.ring_type,
                        'mineral_type', ms.mineral_type,
                        'signal_count', ms.signal_count,
                        'reserve_level', ms.reserve_level
                    )) FILTER (WHERE ms.ring_name IS NOT NULL AND ms.system_id64 = s.id64),
                    '[]'::json
                ) as mineral_signals
            FROM systems s
            LEFT JOIN system_stations ss ON s.id64 = ss.system_id64
            LEFT JOIN mineral_signals ms ON s.id64 = ms.system_id64
            WHERE {where_clause}
            GROUP BY s.id64, s.name, s.x, s.y, s.z, s.controlling_power, s.power_state, s.powers_acquiring, s.distance_from_sol, s.system_state, s.population
        """, (system_identifier, system_identifier))
        
        result = cur.fetchone()
        if not result:
            cur.close()
            conn.close()
            return jsonify({'error': 'System not found'}), 404
            
        # Format response according to API format
        response = {
            'id64': result[0],
            'name': result[1],
            'coords': {
                'x': float(result[2]),
                'y': float(result[3]),
                'z': float(result[4])
            },
            'controllingPower': result[5],
            'powerState': result[6],
            'powers': result[7] if result[7] else [],
            'distanceFromSol': float(result[8]) if result[8] else None,
            'systemState': result[9],
            'population': int(result[10]) if result[10] else None,
            'stations': result[11] if result[11] else [],
            'mineralSignals': result[12] if result[12] else []
        }
        
        cur.close()
        conn.close()
        return jsonify(response)
        
    except Exception as e:
        if 'cur' in locals():
            cur.close()
        if 'conn' in locals():
            conn.close()
        print(f"Error in get_discord_system: {str(e)}")
        print(f"System identifier: {system_identifier}")
        import traceback
        print("Full traceback:")
        traceback.print_exc()
        return jsonify({'error': f"Failed to fetch system data: {str(e)}"}), 500

@discord_api_bp.route('/api/discord/systems/acquire/<path:system_identifier>')
def discord_search_acquisition(system_identifier):
    """Search for acquisition opportunities"""
    try:
        power = request.args.get('power')
        search_type = request.args.get('search', 'from_acquisition')
        
        if not power:
            return jsonify({'error': 'Power parameter is required'}), 400
            
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
            
        # Get system info
        try:
            id64 = int(system_identifier)
            where_clause = "s.id64 = %s"
        except ValueError:
            where_clause = "LOWER(s.name) = LOWER(%s)"
            
        cur = conn.cursor()
        cur.execute(f"SELECT id64, name, x, y, z, controlling_power, power_state FROM systems s WHERE {where_clause}", 
                   [system_identifier])
        system = cur.fetchone()
        cur.close()
        
        if not system:
            return jsonify({'error': 'System not found'}), 404
            
        system_info = {
            'id64': system[0],
            'name': system[1],
            'coords': {'x': float(system[2]), 'y': float(system[3]), 'z': float(system[4])},
            'controllingPower': system[5],
            'powerState': system[6]
        }
        
        result = {
            'power': power,
            'searchType': search_type,
            'systems': []
        }
        
        # Get full system details
        system_details = get_system_details(conn, system_info['id64'])
        
        if search_type == 'from_acquisition':
            # Check if system is unoccupied
            if system_info['controllingPower'] is not None:
                return jsonify({'error': 'System must be unoccupied for from_acquisition search'}), 400
                
            # Find control systems
            nearby = find_acquisition_systems(conn, system_info['coords']['x'], 
                                           system_info['coords']['y'], 
                                           system_info['coords']['z'], 
                                           power)
            
            # Add system types
            system_details['systemType'] = 'Acquisition'
            result['systems'].append(system_details)
            
            for sys in nearby['fortified']:
                sys_details = get_system_details(conn, sys['id64'])
                sys_details['systemType'] = 'Fortified'
                sys_details['distanceToSource'] = sys['distance']  # Add distance to source system
                result['systems'].append(sys_details)
                
            for sys in nearby['strongholds']:
                sys_details = get_system_details(conn, sys['id64'])
                sys_details['systemType'] = 'Stronghold'
                sys_details['distanceToSource'] = sys['distance']  # Add distance to source system
                result['systems'].append(sys_details)
                
        else:  # for_acquisition
            # Check if system is controlled by power
            if (system_info['controllingPower'] != power or 
                system_info['powerState'] not in ['Fortified', 'Stronghold']):
                return jsonify({'error': 'System must be Fortified or Stronghold and controlled by specified power'}), 400
                
            # Find acquisition systems
            range_ly = STRONGHOLD_RANGE if system_info['powerState'] == 'Stronghold' else FORTIFIED_RANGE
            acquisition_systems = find_systems_in_range(conn, 
                                                      system_info['coords']['x'],
                                                      system_info['coords']['y'],
                                                      system_info['coords']['z'],
                                                      range_ly,
                                                      unoccupied_only=True)
            
            # Add system types
            system_details['systemType'] = system_info['powerState']
            result['systems'].append(system_details)
            
            # Add acquisition systems with distance
            for sys in acquisition_systems:
                sys_details = get_system_details(conn, sys['id64'])
                sys_details['systemType'] = 'Acquisition'
                sys_details['distanceToSource'] = sys['distance']  # Add distance to source system
                result['systems'].append(sys_details)
        
        conn.close()
        return jsonify(result)
        
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        return jsonify({'error': str(e)}), 500

def get_system_details(conn, system_id64: int) -> dict:
    """Get full system details including stations and mineral signals"""
    cur = conn.cursor()
    
    # Get system info with stations and commodities
    cur.execute("""
        WITH system_stations AS (
            SELECT 
                st.*,
                json_agg(
                    json_build_object(
                        'name', sc.commodity_name,
                        'demand', sc.demand,
                        'sellPrice', sc.sell_price
                    )
                ) FILTER (WHERE sc.commodity_name IS NOT NULL) as commodities
            FROM systems s
            LEFT JOIN stations st ON s.id64 = st.system_id64
            LEFT JOIN station_commodities sc 
                ON st.system_id64 = sc.system_id64 
                AND st.station_id = sc.station_id
            WHERE s.id64 = %s
            GROUP BY st.system_id64, st.station_id, st.station_name, st.station_type, st.landing_pad_size, 
                     st.distance_to_arrival, st.update_time, st.primary_economy, st.body
        ), mineral_signals AS (
            SELECT 
                ms.system_id64,
                ms.body_name,
                ms.ring_name,
                ms.ring_type,
                ms.mineral_type,
                ms.signal_count,
                ms.reserve_level
            FROM mineral_signals ms
            WHERE ms.system_id64 = %s
        )
        SELECT 
            s.id64,
            s.name,
            s.x, s.y, s.z,
            s.controlling_power,
            s.power_state,
            s.powers_acquiring,
            s.distance_from_sol,
            COALESCE(NULLIF(s.system_state, 'NULL'), 'None') as system_state,
            s.population,
            COALESCE(
                json_agg(DISTINCT jsonb_build_object(
                    'name', ss.station_name,
                    'id', ss.station_id,
                    'updateTime', ss.update_time,
                    'distanceToArrival', ss.distance_to_arrival,
                    'primaryEconomy', ss.primary_economy,
                    'body', ss.body,
                    'type', ss.station_type,
                    'landingPads', ss.landing_pad_size,
                    'market', jsonb_build_object(
                        'commodities', ss.commodities
                    )
                )) FILTER (WHERE ss.station_name IS NOT NULL),
                '[]'::json
            ) as stations,
            COALESCE(
                json_agg(DISTINCT jsonb_build_object(
                    'body_name', ms.body_name,
                    'ring_name', ms.ring_name,
                    'ring_type', ms.ring_type,
                    'mineral_type', ms.mineral_type,
                    'signal_count', ms.signal_count,
                    'reserve_level', ms.reserve_level
                )) FILTER (WHERE ms.ring_name IS NOT NULL),
                '[]'::json
            ) as mineral_signals
        FROM systems s
        LEFT JOIN system_stations ss ON s.id64 = ss.system_id64
        LEFT JOIN mineral_signals ms ON s.id64 = ms.system_id64
        WHERE s.id64 = %s
        GROUP BY s.id64, s.name, s.x, s.y, s.z, s.controlling_power, s.power_state, 
                 s.powers_acquiring, s.distance_from_sol, s.system_state, s.population
    """, (system_id64, system_id64, system_id64))
    
    result = cur.fetchone()
    if not result:
        return None
        
    # Format response
    response = {
        'id64': result[0],
        'name': result[1],
        'coords': {
            'x': float(result[2]),
            'y': float(result[3]),
            'z': float(result[4])
        },
        'controllingPower': result[5],
        'powerState': result[6],
        'powers': result[7] if result[7] else [],
        'distanceFromSol': float(result[8]) if result[8] else None,
        'systemState': result[9],
        'population': int(result[10]) if result[10] else None,
        'stations': result[11] if result[11] else [],
        'mineralSignals': result[12] if result[12] else []
    }
    
    cur.close()
    return response

def find_systems_in_range(conn, x: float, y: float, z: float, range_ly: float, power: str = None, power_state: str = None, unoccupied_only: bool = False) -> list:
    """Find systems within range matching power criteria"""
    cur = conn.cursor()
    
    query = """
        SELECT id64, name, x, y, z, controlling_power, power_state, population,
               SQRT(POWER(x - %s, 2) + POWER(y - %s, 2) + POWER(z - %s, 2)) as distance
        FROM systems
        WHERE POWER(x - %s, 2) + POWER(y - %s, 2) + POWER(z - %s, 2) <= POWER(%s, 2)
    """
    params = [x, y, z, x, y, z, range_ly]
    
    if power:
        query += " AND controlling_power = %s"
        params.append(power)
    if power_state:
        query += " AND power_state = %s"
        params.append(power_state)
    if unoccupied_only:
        query += " AND controlling_power IS NULL AND population > 0"
    
    cur.execute(query, params)
    systems = cur.fetchall()
    cur.close()
    
    return [{
        'id64': s[0],
        'name': s[1],
        'coords': {'x': float(s[2]), 'y': float(s[3]), 'z': float(s[4])},
        'controllingPower': s[5],
        'powerState': s[6],
        'population': int(s[7]) if s[7] else None,
        'distance': float(s[8])
    } for s in systems]

def find_acquisition_systems(conn, x: float, y: float, z: float, power: str) -> dict:
    """Find acquisition and control systems"""
    # Find fortified systems within 20ly
    fortified = find_systems_in_range(conn, x, y, z, FORTIFIED_RANGE, power, "Fortified")
    
    # Find stronghold systems within 30ly
    strongholds = find_systems_in_range(conn, x, y, z, STRONGHOLD_RANGE, power, "Stronghold")
    
    # Find unoccupied systems in range
    acquisition_systems = []
    if fortified or strongholds:
        acquisition_systems = find_systems_in_range(conn, x, y, z, STRONGHOLD_RANGE, unoccupied_only=True)
    
    return {
        'fortified': fortified,
        'strongholds': strongholds,
        'acquisition': acquisition_systems
    }
