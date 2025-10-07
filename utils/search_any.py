"""Query builder for Any material search"""
import json
import os
from utils.search_queries import (
    get_base_cte, get_station_cte, get_ring_join_conditions,
    get_main_select, get_main_joins, get_order_by
)
from utils.common import log_message, BLUE, BASE_DIR
from utils.search_common import get_time_filter_sql

def get_materials_for_ring_type(ring_type, mining_types):
    """Get list of materials minable in a ring type with specific mining methods"""
    materials_path = os.path.join(BASE_DIR, 'data/mining_materials.json')
    with open(materials_path, 'r') as f:
        mat_data = json.load(f)['materials']

    valid_materials = []
    for material_name, material in mat_data.items():
        if ring_type not in material.get('ring_types', {}):
            continue

        ring_data = material['ring_types'][ring_type]

        # If no mining types or 'All', include everything
        if not mining_types or 'All' in mining_types:
            valid_materials.append(material_name)
            continue

        # Check if ring supports ANY of the selected mining methods
        supports_any = False
        for mining_type in mining_types:
            mt_lower = mining_type.lower()
            if mt_lower == 'laser surface' and ring_data.get('surfaceLaserMining', False):
                supports_any = True
                break
            elif mt_lower == 'surface deposit' and ring_data.get('surfaceDeposit', False):
                supports_any = True
                break
            elif mt_lower == 'sub surface deposit' and ring_data.get('subSurfaceDeposit', False):
                supports_any = True
                break
            elif mt_lower == 'core' and ring_data.get('core', False):
                supports_any = True
                break

        if supports_any:
            valid_materials.append(material_name)

    return valid_materials

def build_any_material_query(params, coords, valid_ring_types, where_conditions, where_params):
    """Build query specifically for 'Any' material search that respects all filters"""
    rx, ry, rz = coords

    # Get time filter SQL
    time_filter_sql, time_filter_params = get_time_filter_sql(params)

    # Build material arrays filtered by mining type
    icy_materials = get_materials_for_ring_type('Icy', params['mining_types'])
    rocky_materials = get_materials_for_ring_type('Rocky', params['mining_types'])
    metal_rich_materials = get_materials_for_ring_type('Metal Rich', params['mining_types'])
    metallic_materials = get_materials_for_ring_type('Metallic', params['mining_types'])

    # Convert to SQL array format
    icy_array = "ARRAY[" + ",".join([f"'{m}'" for m in icy_materials]) + "]" if icy_materials else "ARRAY[]::text[]"
    rocky_array = "ARRAY[" + ",".join([f"'{m}'" for m in rocky_materials]) + "]" if rocky_materials else "ARRAY[]::text[]"
    metal_rich_array = "ARRAY[" + ",".join([f"'{m}'" for m in metal_rich_materials]) + "]" if metal_rich_materials else "ARRAY[]::text[]"
    metallic_array = "ARRAY[" + ",".join([f"'{m}'" for m in metallic_materials]) + "]" if metallic_materials else "ARRAY[]::text[]"

    # Debug logging of ALL input parameters
    # log_message(BLUE, "SEARCH", "Input parameters:")
    # log_message(BLUE, "SEARCH", f"- Reference system coordinates: ({rx}, {ry}, {rz})")
    # log_message(BLUE, "SEARCH", f"- Max distance: {params['max_dist']}")
    # log_message(BLUE, "SEARCH", f"- Power conditions: {where_conditions}")
    # log_message(BLUE, "SEARCH", f"- Power params: {where_params}")
    # log_message(BLUE, "SEARCH", f"- System state: {params.get('system_state', 'Any')}")
    # log_message(BLUE, "SEARCH", f"- Ring type filter: {params['ring_type_filter']}")
    # log_message(BLUE, "SEARCH", f"- Valid ring types: {valid_ring_types}")
    # log_message(BLUE, "SEARCH", f"- Mining types: {params['mining_types']}")
    # log_message(BLUE, "SEARCH", f"- Landing pad size: {params['landing_pad_size']}")
    # log_message(BLUE, "SEARCH", f"- Demand range: {params['min_demand']} - {params['max_demand']}")
    # log_message(BLUE, "SEARCH", f"- Time filter: {time_filter_sql} with params {time_filter_params}")
    # log_message(BLUE, "SEARCH", f"- Icy materials: {len(icy_materials)}")
    # log_message(BLUE, "SEARCH", f"- Rocky materials: {len(rocky_materials)}")
    # log_message(BLUE, "SEARCH", f"- Metal Rich materials: {len(metal_rich_materials)}")
    # log_message(BLUE, "SEARCH", f"- Metallic materials: {len(metallic_materials)}")
    
    query = """
    WITH RECURSIVE
    -- Step 1: Filter by power conditions first
    filtered_by_power AS MATERIALIZED (
        SELECT s.*
        FROM systems s
        WHERE """ + ((" AND ".join(where_conditions)) if where_conditions else "TRUE") + """
    ),
    -- Step 2: Calculate distances and apply system state filter
    filtered_systems AS MATERIALIZED (
        SELECT s.*, 
               SQRT(POWER(s.x - %s, 2) + POWER(s.y - %s, 2) + POWER(s.z - %s, 2)) as distance
        FROM filtered_by_power s
        WHERE CASE 
            WHEN %s != 'Any' THEN s.system_state = %s
            ELSE true
        END
        AND POWER(s.x - %s, 2) + POWER(s.y - %s, 2) + POWER(s.z - %s, 2) <= POWER(%s, 2)
    ),
    -- Step 3: Get valid ring signals and what can be mined in them
    valid_rings AS MATERIALIZED (
        SELECT 
            s.id64 as system_id64,
            s.name,
            s.controlling_power,
            s.power_state,
            s.powers_acquiring,
            s.system_state,
            s.distance,
            ms.mineral_type,
            ms.ring_type,
            ms.reserve_level,
            ms.body_name,
            ms.ring_name,
            ms.signal_count,
            -- For each ring, determine what can be mined there (filtered by mining type)
            CASE
                WHEN ms.mineral_type IS NOT NULL AND ms.ring_type = 'Icy' AND ms.mineral_type = ANY(""" + icy_array + """) THEN
                    ARRAY[ms.mineral_type]
                WHEN ms.mineral_type IS NOT NULL AND ms.ring_type = 'Rocky' AND ms.mineral_type = ANY(""" + rocky_array + """) THEN
                    ARRAY[ms.mineral_type]
                WHEN ms.mineral_type IS NOT NULL AND ms.ring_type = 'Metal Rich' AND ms.mineral_type = ANY(""" + metal_rich_array + """) THEN
                    ARRAY[ms.mineral_type]
                WHEN ms.mineral_type IS NOT NULL AND ms.ring_type = 'Metallic' AND ms.mineral_type = ANY(""" + metallic_array + """) THEN
                    ARRAY[ms.mineral_type]
                WHEN ms.mineral_type IS NULL AND ms.ring_type = 'Icy' THEN
                    """ + icy_array + """
                WHEN ms.mineral_type IS NULL AND ms.ring_type = 'Rocky' THEN
                    """ + rocky_array + """
                WHEN ms.mineral_type IS NULL AND ms.ring_type = 'Metal Rich' THEN
                    """ + metal_rich_array + """
                WHEN ms.mineral_type IS NULL AND ms.ring_type = 'Metallic' THEN
                    """ + metallic_array + """
                ELSE
                    ARRAY[]::text[]
            END as minable_materials
        FROM filtered_systems s
        JOIN mineral_signals ms ON s.id64 = ms.system_id64
        WHERE ms.ring_type = ANY(%s::text[])  -- Use valid_ring_types from material data
        AND CASE 
            WHEN %s = 'Hotspots' THEN ms.mineral_type IS NOT NULL
            WHEN %s = 'Without Hotspots' THEN ms.mineral_type IS NULL
            ELSE true  -- 'All' accepts both
        END
        AND CASE
            WHEN %s != 'All' THEN ms.reserve_level = %s
            ELSE true
        END
    ),
    -- Step 4: Get valid stations with commodity prices
    valid_stations AS MATERIALIZED (
        SELECT
            st.system_id64,
            st.station_id,
            st.station_name,
            st.landing_pad_size,
            st.distance_to_arrival,
            st.station_type,
            st.update_time,
            sc.commodity_name,
            sc.sell_price,
            sc.demand
        FROM stations st
        JOIN station_commodities sc ON st.system_id64 = sc.system_id64
            AND st.station_id = sc.station_id
        WHERE EXISTS (SELECT 1 FROM filtered_systems fs WHERE fs.id64 = st.system_id64)
        """ + ("AND " + time_filter_sql if time_filter_sql else "") + """
        AND sc.sell_price > 0
        AND (
            (%s = 0 AND %s = 0) OR  -- No demand limits
            (%s = 0 AND sc.demand <= %s) OR  -- Only max
            (%s = 0 AND sc.demand >= %s) OR  -- Only min
            (sc.demand >= %s AND sc.demand <= %s)  -- Both
        )
        AND (
            %s = 'Any' OR  -- Any pad size
            st.landing_pad_size = 'Unknown' OR  -- Always include Unknown
            st.landing_pad_size = %s  -- Match exact pad size
        )
    ),
    -- Step 5: Match stations with rings, but ONLY for materials that can be mined there
    matched_results AS MATERIALIZED (
        SELECT 
            vr.*,
            vs.station_id,
            vs.station_name,
            vs.landing_pad_size,
            vs.distance_to_arrival,
            vs.station_type,
            vs.update_time,
            vs.commodity_name,
            vs.sell_price,
            vs.demand
        FROM valid_rings vr
        JOIN valid_stations vs ON vr.system_id64 = vs.system_id64
        WHERE vs.commodity_name = ANY(vr.minable_materials)  -- Only match if material can be mined in this ring
    ),
    -- Step 6: Get best price per system while maintaining material availability
    best_matches AS MATERIALIZED (
        SELECT DISTINCT ON (system_id64)
            *
        FROM matched_results
        ORDER BY 
            system_id64,
            sell_price DESC  -- Highest price first, but only among minable materials
    )
    -- Final selection with proper ordering
    SELECT 
        name as system_name,
        system_id64,
        controlling_power,
        power_state,
        powers_acquiring,
        system_state,
        distance,
        CASE
            WHEN mineral_type IS NOT NULL 
            THEN commodity_name || ' (Hotspot)'
            ELSE commodity_name
        END as display_name,
        commodity_name,
        mineral_type,
        ring_type,
        reserve_level,
        body_name,
        ring_name,
        signal_count,
        station_name,
        landing_pad_size,
        distance_to_arrival,
        station_type,
        update_time,
        sell_price,
        demand
    FROM best_matches
    ORDER BY sell_price DESC, distance ASC"""
    
    # Build parameters list - CORRECT ORDER IS CRUCIAL
    query_params = []

    # 1. Add power condition params first if they exist
    if where_params:
        query_params.extend(where_params)

    # 2. Add the rest in correct order
    query_params.extend([
        # Distance calculation params
        rx, ry, rz,
        # System state params
        params.get('system_state', 'Any'),
        params.get('system_state', 'Any'),
        # Distance filter params
        rx, ry, rz,
        params['max_dist'],
        # Ring type params
        valid_ring_types,
        params['ring_type_filter'],
        params['ring_type_filter'],
        # Reserve level params
        params.get('reserve_level', 'All'),
        params.get('reserve_level', 'All')
    ])

    # 3. Add time filter params if they exist
    if time_filter_params:
        query_params.extend(time_filter_params)

    # 4. Add remaining params
    query_params.extend([
        # Demand filter params
        params['min_demand'], params['max_demand'],  # Zero-zero check
        params['min_demand'], params['max_demand'],  # Min=0 check
        params['max_demand'], params['min_demand'],  # Max=0 check
        params['min_demand'], params['max_demand'],  # Between check
        # Landing pad params
        params['landing_pad_size'],
        params['landing_pad_size']
    ])
    
    # Add limit if specified
    if params.get('limit'):
        query += " LIMIT %s"
        query_params.append(params['limit'])

    # Final debug logging
    log_message(BLUE, "SEARCH", f"Final parameter count: {len(query_params)}")
    log_message(BLUE, "SEARCH", f"Query placeholder count: {query.count('%s')}")

    # Run EXPLAIN ANALYZE for performance analysis (DISABLED)
    # Uncomment to debug query performance
    # try:
    #     from utils.common import get_db_connection
    #     conn = get_db_connection()
    #     cur = conn.cursor()
    #
    #     explain_query = "EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) " + query
    #     log_message(BLUE, "SEARCH", "Running EXPLAIN ANALYZE to measure performance...")
    #     cur.execute(explain_query, query_params)
    #     explain_results = cur.fetchall()
    #     log_message(BLUE, "SEARCH", "Query plan:")
    #     for row in explain_results:
    #         log_message(BLUE, "SEARCH", str(row[0]))
    #
    #     cur.close()
    #     conn.close()
    # except Exception as e:
    #     log_message(BLUE, "SEARCH", f"Failed to run EXPLAIN ANALYZE: {str(e)}")

    return query, query_params 