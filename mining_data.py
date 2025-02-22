"""Constants and helper functions for mining materials."""

import csv
import json

# Materials that can be mined without hotspots
NON_HOTSPOT_MATERIALS = {
    # Metallic only
    'Gold': ['Metallic'],
    'Osmium': ['Metallic'],
    'Gallite': ['Metallic', 'Rocky'],
    'Palladium': ['Metallic'],
    'Painite': ['Metallic'],

    # Metallic or Metal Rich
    'Cobalt': ['Metallic', 'Metal Rich'],
    'Copper': ['Metallic', 'Metal Rich'],
    'Gallium': ['Metallic', 'Metal Rich'],
    'Silver': ['Metallic', 'Metal Rich'],
    'Aluminium': ['Metallic', 'Metal Rich'],
    'Beryllium': ['Metallic', 'Metal Rich'],
    'Bismuth': ['Metallic', 'Metal Rich'],
    'Hafnium': ['Metallic', 'Metal Rich'],
    'Indium': ['Metallic', 'Metal Rich'],
    'Lanthanum': ['Metallic', 'Metal Rich'],
    'Praseodymium': ['Metallic', 'Metal Rich'],
    'Samarium': ['Metallic', 'Metal Rich'],
    'Tantalum': ['Metallic', 'Metal Rich'],
    'Thallium': ['Metallic', 'Metal Rich'],
    'Thorium': ['Metallic', 'Metal Rich'],
    'Titanium': ['Metallic', 'Metal Rich'],
    'Uranium': ['Metallic', 'Metal Rich'],
    
    # Rocky only
    'Bauxite': ['Rocky'],
    'Lepidolite': ['Rocky'],
    'Moissanite': ['Rocky'],
    'Jadeite': ['Rocky'],
    'Pyrophyllite': ['Rocky'],
    'Taaffeite': ['Rocky'],
    
    # Rocky and Icy
    'Bertrandite': ['Rocky', 'Icy'],
    
    # Rocky and Metal Rich
    'Coltan': ['Rocky', 'Metal Rich'],
    'Indite': ['Rocky', 'Metal Rich'],
    'Uraninite': ['Rocky', 'Metal Rich'],
    
    # Rocky and Metallic
    'Gallite': ['Rocky', 'Metallic'],
    
    # Icy only
    'Methane Clathrate': ['Icy'],
    'Methanol Monohydrate Crystals': ['Icy'],
    'Goslarite': ['Icy'],
    'Cryolite': ['Icy'],
    'Lithium Hydroxide': ['Icy'],
    'Void Opal': ['Icy'],
    
    # Metal Rich and Rocky
    'Rutile': ['Metal Rich', 'Rocky']
}

# Load material mappings from JSON
with open('data/materials.json', 'r') as f:
    MATERIAL_MAPPINGS = json.load(f)

def get_material_ring_types(material_name: str) -> list:
    """Get the required ring types for a given material."""
    # Special case for Low Temperature Diamonds
    if material_name == 'Low Temperature Diamonds':
        return ['hotspot', 'LowTemperatureDiamond']
    
    # Non-hotspot materials
    if material_name in NON_HOTSPOT_MATERIALS:
        return NON_HOTSPOT_MATERIALS[material_name]
    
    # All other materials are hotspot-based
    return ['hotspot']

def is_non_hotspot_material(material_name: str) -> bool:
    """Check if a material can be mined without hotspots."""
    return material_name in NON_HOTSPOT_MATERIALS

def get_material_sql_conditions(material_name: str) -> tuple[str, list]:
    """Get SQL conditions and parameters for finding systems where a material can be mined."""
    ring_types = get_material_ring_types(material_name)
    
    if material_name == 'Low Temperature Diamonds':
        return 'ms.mineral_type = ?', ['LowTemperatureDiamond']
    elif 'hotspot' in ring_types:
        return 'ms.mineral_type = ?', [material_name]
    else:
        placeholders = ','.join(['?' for _ in ring_types])
        return f'ms.ring_type IN ({placeholders})', ring_types 

def get_ring_type_case_statement(commodity_column: str = 'commodity_name') -> str:
    """Generate SQL CASE statement for checking ring types."""
    cases = []
    for material, ring_types in NON_HOTSPOT_MATERIALS.items():
        if len(ring_types) == 1:
            cases.append(f"WHEN '{material}' THEN '{ring_types[0]}'")
        else:
            types_str = "', '".join(ring_types)
            cases.append(f"WHEN '{material}' THEN ms.ring_type IN ('{types_str}')")
    
    return f'CASE {commodity_column}\n' + '\n'.join(f'{case}' for case in cases) + '\nEND'

def get_non_hotspot_materials_list() -> str:
    """Get a comma-separated string of non-hotspot material names for SQL IN clause."""
    return ', '.join(f"'{material}'" for material in NON_HOTSPOT_MATERIALS.keys()) 

def load_price_data():
    """Load price data from CSV file."""
    price_data = {}
    with open('data/current_prices.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            price_data[row['Material']] = {
                'avg_price': int(row['Average Price']),
                'max_price': int(row['Max Price'])
            }
            #print(f"Loaded price data for {row['Material']}: avg={row['Average Price']}, max={row['Max Price']}")
    return price_data

def get_price_comparison(current_price, reference_price):
    """Calculate price comparison and return color and indicator."""
    if current_price == 0 or reference_price == 0:
        return None, ''
    
    percentage = (current_price / reference_price - 1) * 100  # Calculate percentage difference
    
    # Handle positive percentages first
    if percentage >= 125:
        return '#f0ff00', '     +++++'
    elif percentage >= 100:
        return '#fff000', '     ++++'
    elif percentage >= 75:
        return '#ffcc00', '     +++'
    elif percentage >= 50:
        return '#ff9600', '     ++'
    elif percentage >= 25:
        return '#ff7e00', '     +'
    # Handle near-average range
    elif percentage >= -5:
        return None, ''
    # Handle negative percentages
    elif percentage >= -25:
        return '#ff2a00', '     -'
    elif percentage >= -50:
        return '#af0019', '     --'
    else:
        return '#af0019', '     ---'

def normalize_commodity_name(name):
    """Normalize commodity names for price lookup."""
    # Special case for LowTemperatureDiamond
    if name == 'LowTemperatureDiamond':
        return 'Low Temperature Diamonds'
    
    # Create reverse mapping (full name to full name)
    full_names = {v: v for v in MATERIAL_MAPPINGS.values()}
    
    # Combine both mappings
    all_mappings = {**MATERIAL_MAPPINGS, **full_names}
    
    # Return the full name if found in mappings, otherwise return the original name
    return all_mappings.get(name, name)

def get_material_codes():
    """Load and return mapping of material codes to full names."""
    return MATERIAL_MAPPINGS.copy()

# Cache the material codes
MATERIAL_CODES = get_material_codes()

# Load price data when module is imported
PRICE_DATA = load_price_data() 

def get_mining_type_conditions(commodity: str, mining_types: list) -> tuple[str, list]:
    """Get SQL conditions for filtering by mining type."""
    if not mining_types or 'All' in mining_types:
        return '', []
        
    # Load material mining data
    try:
        with open('data/mining_data.json', 'r') as f:
            material_data = json.load(f)
            
        # Find the commodity data
        commodity_data = next((item for item in material_data['materials'] if item['name'] == commodity), None)
        if not commodity_data:
            return '', []
        
        # Build conditions for each ring type
        conditions = []
        params = []
        
        for ring_type, ring_data in commodity_data['ring_types'].items():
            mining_type_matches = []
            
            for mining_type in mining_types:
                if mining_type == 'Core' and ring_data['core']:
                    mining_type_matches.append(True)
                elif mining_type == 'Laser Surface' and ring_data['surfaceLaserMining']:
                    mining_type_matches.append(True)
                elif mining_type == 'Surface Deposit' and ring_data['surfaceDeposit']:
                    mining_type_matches.append(True)
                elif mining_type == 'Sub Surface Deposit' and ring_data['subSurfaceDeposit']:
                    mining_type_matches.append(True)
            
            if mining_type_matches:
                conditions.append('(ms.ring_type = ?)')
                params.append(ring_type)
    
    except Exception as e:
        app.logger.error(f"Error loading mining_data.json: {str(e)}")
        return '', []
        
    if not conditions:
        return '1=0', []  # No matches possible
        
    return '(' + ' OR '.join(conditions) + ')', params

def get_ring_materials():
    """Load ring materials and their associated ring types from mining_data.json."""
    materials = {}
    
    try:
        with open('data/mining_data.json', 'r') as f:
            material_data = json.load(f)
            
            for item in material_data['materials']:
                # Get list of ring types where this material can be found
                valid_ring_types = []
                for ring_type, ring_data in item['ring_types'].items():
                    if any([
                        ring_data['surfaceLaserMining'],
                        ring_data['surfaceDeposit'],
                        ring_data['subSurfaceDeposit'],
                        ring_data['core']
                    ]):
                        valid_ring_types.append(ring_type)
                
                if valid_ring_types:  # Only add if material can be found in at least one ring type
                    materials[item['name']] = {
                        'ring_types': valid_ring_types,
                        'abbreviation': '',  # These fields are kept for backward compatibility
                        'conditions': item['conditions'],
                        'value': ''
                    }
    except Exception as e:
        app.logger.error(f"Error loading mining_data.json: {str(e)}")
    
    return materials

def get_non_hotspot_materials_list():
    """Get the list of materials that don't use hotspots."""
    non_hotspot_minerals = {'Bauxite', 'Bertrandite', 
                        'Coltan', 'Gallite', 'Goslarite', 'Indite', 'Lepidolite', 'Methane Clathrate', 
                        'Methanol Monohydrate Crystals', 'Moissanite', 'Rutile', 
                        'Uraninite', 'Jadeite', 'Pyrophyllite', 'Taaffeite', 'Cryolite', 'Lithium Hydroxide', 'Void Opal'}
    non_hotspot_metals = {'Aluminium', 'Beryllium', 'Cobalt', 'Copper', 'Gallium', 'Gold', 'Hafnium 178', 'Indium',
                        'Lanthanum', 'Lithium', 'Osmium', 'Palladium','Praseodymium', 'Samarium', 'Silver', 'Tantalum', 
                        'Thallium', 'Thorium', 'Titanium', 'Uranium'}
    return non_hotspot_minerals | non_hotspot_metals 

def get_potential_ring_types(material_name: str) -> list:
    """Get potential ring types for a material from mining_data.json."""
    ring_types = set()  # Use a set to avoid duplicates
    
    try:
        with open('data/mining_data.json', 'r') as f:
            material_data = json.load(f)
            
            # Find the material data
            material = next((item for item in material_data['materials'] if item['name'] == material_name), None)
            if material:
                # Check each ring type if it's possible to mine there
                for ring_type, ring_data in material['ring_types'].items():
                    if any([
                        ring_data['surfaceLaserMining'],
                        ring_data['surfaceDeposit'],
                        ring_data['subSurfaceDeposit'],
                        ring_data['core']
                    ]):
                        ring_types.add(ring_type)
    except Exception as e:
        app.logger.error(f"Error loading mining_data.json: {str(e)}")
    
    # Also check NON_HOTSPOT_MATERIALS dictionary for backward compatibility
    if material_name in NON_HOTSPOT_MATERIALS:
        ring_types.update(NON_HOTSPOT_MATERIALS[material_name])
    
    return list(ring_types) 