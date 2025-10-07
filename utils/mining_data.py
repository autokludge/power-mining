"""Constants and helper functions for mining materials."""

import csv
import json
import psycopg2
from psycopg2.extras import DictCursor
import os
from utils.common import BASE_DIR

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

# Materials that can be both laser mined and core mined
BOTH_MINING_MATERIALS = {
    'Low Temperature Diamonds': {
        'laser': ['Icy'],
        'core': ['Icy']
    },
    'Platinum': {
        'laser': ['Metallic'],
        'core': ['Metallic', 'Metal Rich']
    },
    'Painite': {
        'laser': ['Metallic'],
        'core': ['Metallic', 'Metal Rich']
    }
}

# Load material mappings from JSON
with open(os.path.join(BASE_DIR, 'data/materials.json'), 'r') as f:
    MATERIAL_MAPPINGS = json.load(f)

def get_material_ring_types(material_name: str) -> list:
    """Get list of ring types where a material can be found."""
    if material_name == 'Low Temperature Diamonds':
        # LTDs can be found in Icy rings (both hotspot and non-hotspot)
        return ['hotspot', 'Icy']
    elif material_name in BOTH_MINING_MATERIALS:
        # For materials that can be both laser mined and core mined,
        # combine their ring types
        material_data = BOTH_MINING_MATERIALS[material_name]
        ring_types = set()
        ring_types.update(material_data['laser'])
        ring_types.update(material_data['core'])
        return list(ring_types)
    elif material_name in NON_HOTSPOT_MATERIALS:
        return NON_HOTSPOT_MATERIALS[material_name]
    else:
        # Default to hotspot only
        return ['hotspot']

def is_non_hotspot_material(material_name: str) -> bool:
    """Check if a material can be mined without hotspots."""
    return material_name in NON_HOTSPOT_MATERIALS

def get_material_sql_conditions(material_name: str) -> tuple[str, list]:
    """Get SQL conditions and parameters for finding systems where a material can be mined."""
    ring_types = get_material_ring_types(material_name)
    
    if material_name == 'Low Temperature Diamonds':
        # Special case for LTDs:
        # 1. Hotspots use mineral_type = 'LowTemperatureDiamond'
        # 2. Regular Icy rings for laser mining (no mineral_type)
        # Note: Use parameters to avoid SQL injection
        return '(ms.mineral_type = %s OR (ms.ring_type = %s AND ms.mineral_type IS NULL))', ['LowTemperatureDiamond', 'Icy']
    elif material_name in BOTH_MINING_MATERIALS:
        # For materials that can be both laser mined and core mined
        material_data = BOTH_MINING_MATERIALS[material_name]
        conditions = []
        params = []
        
        # Add laser mining conditions
        laser_rings = material_data['laser']
        if laser_rings:
            conditions.append('(ms.ring_type = ANY(%s) AND ms.mineral_type IS NULL)')
            params.append(laser_rings)
        
        # Add core mining conditions
        core_rings = material_data['core']
        if core_rings:
            conditions.append('(ms.ring_type = ANY(%s) AND ms.mineral_type = %s)')
            params.extend([core_rings, material_name])
        
        return '(' + ' OR '.join(conditions) + ')', params
    elif 'hotspot' in ring_types:
        return 'ms.mineral_type = %s', [material_name]
    else:
        placeholders = ','.join(['%s' for _ in ring_types])
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

def get_non_hotspot_materials_list():
    """Get list of non-hotspot materials."""
    non_hotspot_minerals = {'Bauxite', 'Bertrandite', 
                        'Coltan', 'Gallite', 'Goslarite', 'Indite', 'Lepidolite', 'Methane Clathrate', 
                        'Methanol Monohydrate Crystals', 'Moissanite', 'Rutile', 
                        'Uraninite', 'Jadeite', 'Pyrophyllite', 'Taaffeite', 'Cryolite', 'Lithium Hydroxide', 'Void Opal'}
    non_hotspot_metals = {'Aluminium', 'Beryllium', 'Cobalt', 'Copper', 'Gallium', 'Gold', 'Hafnium 178', 'Indium',
                        'Lanthanum', 'Lithium', 'Osmium', 'Palladium','Praseodymium', 'Samarium', 'Silver', 'Tantalum', 
                        'Thallium', 'Thorium', 'Titanium', 'Uranium'}
    return list(non_hotspot_minerals | non_hotspot_metals)

def load_price_data():
    """Load price data from CSV file."""
    price_data = {}
    with open(os.path.join(BASE_DIR, 'data/current_prices.csv'), 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            price_data[row['Material']] = {
                'avg_price': int(row['Average Price']),
                'max_price': int(row['Max Price'])
            }
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