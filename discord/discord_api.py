from flask import Blueprint, jsonify, request
from sqlalchemy.orm import sessionmaker, joinedload
from sqlalchemy import create_engine, func, or_
import json

# Import the models
from discord.bot_db_model import System, Station, StationCommodity, MineralSignal, Base

# Constants for acquisition search
FORTIFIED_RANGE = 20.0
STRONGHOLD_RANGE = 30.0

discord_api_bp = Blueprint('discord_api', __name__)

# Create engine and session factory
# Using the DATABASE_URL from app config at runtime
engine = None
Session = None

def get_session():
    global engine, Session
    if engine is None:
        from flask import current_app
        engine = create_engine(current_app.config['DATABASE_URL'])
        Session = sessionmaker(bind=engine)
    return Session()

def get_system_details(system_id64: int) -> dict:
    """Get full system details including stations and mineral signals using SQLAlchemy"""
    session = get_session()
    
    # Query the system with eager loading
    system = session.query(System).filter(System.id64 == system_id64).first()
    
    if not system:
        session.close()
        return None
    
    # Query stations with commodities
    stations_query = (
        session.query(Station)
        .filter(Station.system_id64 == system_id64)
        .all()
    )
    
    # Query mineral signals
    signals_query = (
        session.query(MineralSignal)
        .filter(MineralSignal.system_id64 == system_id64)
        .all()
    )
    
    # Format the basic system data
    response = {
        'id64': system.id64,
        'name': system.name,
        'coords': {
            'x': float(system.x),
            'y': float(system.y),
            'z': float(system.z)
        },
        'controllingPower': system.controlling_power,
        'powerState': system.power_state,
        'powers': json.loads(system.powers_acquiring) if system.powers_acquiring else [],
        'distanceFromSol': float(system.distance_from_sol) if system.distance_from_sol else None,
        'systemState': system.system_state if system.system_state and system.system_state != 'NULL' else 'None',
        'population': int(system.population) if system.population else None,
        'stations': [],
        'mineralSignals': []
    }
    
    # Add station data
    for station in stations_query:
        # Get commodities for this station
        commodities_query = (
            session.query(StationCommodity)
            .filter(StationCommodity.system_id64 == system_id64)
            .filter(StationCommodity.station_id == station.station_id)
            .all()
        )
        
        commodities = []
        for commodity in commodities_query:
            commodities.append({
                'name': commodity.commodity_name,
                'demand': commodity.demand,
                'sellPrice': commodity.sell_price
            })
            
        station_data = {
            'name': station.station_name,
            'id': station.station_id,
            'updateTime': station.update_time,
            'distanceToArrival': station.distance_to_arrival,
            'primaryEconomy': station.primary_economy,
            'body': station.body,
            'type': station.station_type,
            'landingPads': station.landing_pad_size,
            'market': {
                'commodities': commodities
            }
        }
        response['stations'].append(station_data)
    
    # Add mineral signal data
    for signal in signals_query:
        signal_data = {
            'body_name': signal.body_name,
            'ring_name': signal.ring_name,
            'ring_type': signal.ring_type,
            'mineral_type': signal.mineral_type,
            'signal_count': signal.signal_count,
            'reserve_level': signal.reserve_level
        }
        response['mineralSignals'].append(signal_data)
    
    session.close()
    return response

def find_systems_in_range(x: float, y: float, z: float, range_ly: float, power: str = None, power_state: str = None, unoccupied_only: bool = False) -> list:
    """Find systems within range matching power criteria using SQLAlchemy"""
    session = get_session()
    
    # Calculate distance in the query
    distance = func.sqrt(
        func.power(System.x - x, 2) + 
        func.power(System.y - y, 2) + 
        func.power(System.z - z, 2)
    ).label('distance')
    
    # Build the base query
    query = session.query(System, distance).filter(
        func.power(System.x - x, 2) + 
        func.power(System.y - y, 2) + 
        func.power(System.z - z, 2) <= 
        func.power(range_ly, 2)
    )
    
    # Add filters based on parameters
    if power:
        query = query.filter(System.controlling_power == power)
    if power_state:
        query = query.filter(System.power_state == power_state)
    if unoccupied_only:
        query = query.filter(System.controlling_power == None)
        query = query.filter(System.population > 0)
    
    # Execute the query
    results = query.all()
    
    # Format results
    systems = []
    for system, distance_value in results:
        systems.append({
            'id64': system.id64,
            'name': system.name,
            'coords': {'x': float(system.x), 'y': float(system.y), 'z': float(system.z)},
            'controllingPower': system.controlling_power,
            'powerState': system.power_state,
            'population': int(system.population) if system.population else None,
            'distance': float(distance_value)
        })
    
    session.close()
    return systems

def find_acquisition_systems(x: float, y: float, z: float, power: str) -> dict:
    """Find acquisition and control systems"""
    # Find fortified systems within 20ly
    fortified = find_systems_in_range(x, y, z, FORTIFIED_RANGE, power, "Fortified")
    
    # Find stronghold systems within 30ly
    strongholds = find_systems_in_range(x, y, z, STRONGHOLD_RANGE, power, "Stronghold")
    
    # Find unoccupied systems in range
    acquisition_systems = []
    if fortified or strongholds:
        acquisition_systems = find_systems_in_range(x, y, z, STRONGHOLD_RANGE, unoccupied_only=True)
    
    return {
        'fortified': fortified,
        'strongholds': strongholds,
        'acquisition': acquisition_systems
    }

@discord_api_bp.route('/api/discord/system/<path:system_identifier>')
def get_discord_system(system_identifier):
    """Get detailed system information by name or id64 using SQLAlchemy"""
    try:
        session = get_session()
        
        # Try to parse as id64 first
        try:
            id64 = int(system_identifier)
            system = session.query(System).filter(System.id64 == id64).first()
        except ValueError:
            # If not a number, treat as system name (case-insensitive)
            system = session.query(System).filter(func.lower(System.name) == func.lower(system_identifier)).first()
        
        session.close()
        
        if not system:
            return jsonify({'error': 'System not found'}), 404
        
        # Get full system details
        system_details = get_system_details(system.id64)
        
        return jsonify(system_details)
        
    except Exception as e:
        print(f"Error in get_discord_system: {str(e)}")
        print(f"System identifier: {system_identifier}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': f"Failed to fetch system data: {str(e)}"}), 500

@discord_api_bp.route('/api/discord/systems/acquire/<path:system_identifier>')
def discord_search_acquisition(system_identifier):
    """Search for acquisition opportunities using SQLAlchemy"""
    try:
        power = request.args.get('power')
        search_type = request.args.get('search', 'from_acquisition')
        
        if not power:
            return jsonify({'error': 'Power parameter is required'}), 400
            
        session = get_session()
        
        # Get system info
        try:
            id64 = int(system_identifier)
            system = session.query(System).filter(System.id64 == id64).first()
        except ValueError:
            system = session.query(System).filter(func.lower(System.name) == func.lower(system_identifier)).first()
            
        if not system:
            session.close()
            return jsonify({'error': 'System not found'}), 404
            
        system_info = {
            'id64': system.id64,
            'name': system.name,
            'coords': {'x': float(system.x), 'y': float(system.y), 'z': float(system.z)},
            'controllingPower': system.controlling_power,
            'powerState': system.power_state
        }
        
        session.close()
        
        result = {
            'power': power,
            'searchType': search_type,
            'systems': []
        }
        
        # Get full system details
        system_details = get_system_details(system_info['id64'])
        
        if search_type == 'from_acquisition':
            # Check if system is unoccupied
            if system_info['controllingPower'] is not None:
                return jsonify({'error': 'System must be unoccupied for from_acquisition search'}), 400
                
            # Find control systems
            nearby = find_acquisition_systems(
                system_info['coords']['x'], 
                system_info['coords']['y'], 
                system_info['coords']['z'], 
                power
            )
            
            # Add system types
            system_details['systemType'] = 'Acquisition'
            result['systems'].append(system_details)
            
            for sys in nearby['fortified']:
                sys_details = get_system_details(sys['id64'])
                sys_details['systemType'] = 'Fortified'
                sys_details['distanceToSource'] = sys['distance']
                result['systems'].append(sys_details)
                
            for sys in nearby['strongholds']:
                sys_details = get_system_details(sys['id64'])
                sys_details['systemType'] = 'Stronghold'
                sys_details['distanceToSource'] = sys['distance']
                result['systems'].append(sys_details)
                
        else:  # for_acquisition
            # Check if system is controlled by power
            if (system_info['controllingPower'] != power or 
                system_info['powerState'] not in ['Fortified', 'Stronghold']):
                return jsonify({'error': 'System must be Fortified or Stronghold and controlled by specified power'}), 400
                
            # Find acquisition systems
            range_ly = STRONGHOLD_RANGE if system_info['powerState'] == 'Stronghold' else FORTIFIED_RANGE
            acquisition_systems = find_systems_in_range(
                system_info['coords']['x'],
                system_info['coords']['y'],
                system_info['coords']['z'],
                range_ly,
                unoccupied_only=True
            )
            
            # Add system types
            system_details['systemType'] = system_info['powerState']
            result['systems'].append(system_details)
            
            # Add acquisition systems with distance
            for sys in acquisition_systems:
                sys_details = get_system_details(sys['id64'])
                sys_details['systemType'] = 'Acquisition'
                sys_details['distanceToSource'] = sys['distance']
                result['systems'].append(sys_details)
        
        return jsonify(result)
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
