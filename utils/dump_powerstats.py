#!/usr/bin/env python3
import json
import psycopg2
import os
import argparse
from urllib.parse import urlparse
from datetime import datetime

# Constants for state mapping
POWER_STATE_MAP = {
    # Note: There is no mapping for 'Controlled' in our official mapping
    # 'Controlled' (which appears in some EDDN messages) is mapped to 'Exploited' (ID 1)
    # but only at the database view level, not in our official documentation
    0: 'NULL/EMPTY',
    1: 'Exploited',
    2: 'Fortified', 
    3: 'Stronghold',
    4: 'InPrepareRadius',
    5: 'Prepared',
    6: 'Turmoil',
    7: 'Unoccupied'
}

def dump_power_stats_from_view(db_url, output_file, debug=False):
    """
    Dump power statistics from the power_stats materialized view to a JSONL file.
    """
    print(f"Starting power statistics export from view to {output_file}")
    start_time = datetime.now()
    
    # Parse database URL
    url = urlparse(db_url)
    dbname = url.path[1:]
    user = url.username
    password = url.password
    host = url.hostname
    port = url.port
    
    # Connect to the database
    print(f"Connecting to database {host}:{port}/{dbname}...")
    conn = psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port
    )
    print("Connected successfully")
    
    try:
        with conn.cursor() as cursor:
            # Ensure the materialized view is refreshed (if it's already created)
            try:
                print("Refreshing materialized view...")
                cursor.execute("REFRESH MATERIALIZED VIEW power_stats")
                conn.commit()
                print("Materialized view refreshed successfully")
            except psycopg2.Error as e:
                print(f"Could not refresh view (may not exist yet): {str(e)}")
                conn.rollback()
            
            # Ensure output directory exists
            os.makedirs(os.path.dirname(output_file), exist_ok=True)
            
            # Open the output file
            with open(output_file, 'w', encoding='utf-8') as f:
                # Write the header line
                header_line = '{ "id64", "name", ["x", "y", "z"], "controlling_power", "power_state", ["powers_acquiring"], "control_progress", "control_points", "cp_delta", "state_percent", "trend_percent", ["trend_array_24h"], ["trend_array_days"], "transition", "danger", "distance_from_sol", ["active_states"] },'
                f.write(header_line + '\n')
                
                print(f"Fetching data from power_stats view...")
                
                # Use batched fetching to manage memory usage
                cursor.execute("SELECT COUNT(*) FROM power_stats")
                total_rows = cursor.fetchone()[0]
                print(f"Found {total_rows} systems with power data")
                
                # Query all fields from the view
                cursor.execute("""
                    SELECT 
                        system_id64, system_name, x, y, z, power_id, power_state_id, 
                        powers_acquiring, control_progress, control_points, cp_delta,
                        state_percent, trend_percent, trend_array_24h, trend_array_days,
                        transition, danger, distance_from_sol, active_state_ids
                    FROM power_stats
                    ORDER BY system_name
                """)
                
                # Process in batches
                count = 0
                batch_size = 1000
                
                while True:
                    rows = cursor.fetchmany(batch_size)
                    if not rows:
                        break
                    
                    print(f"Processing batch of {len(rows)} systems (total so far: {count})")
                    
                    for row in rows:
                        if debug and count >= 10:
                            print("Debug mode: stopping after 10 systems")
                            break
                        
                        count += 1
                        if count % 1000 == 0:
                            print(f"Processed {count}/{total_rows} systems ({count/total_rows*100:.1f}%)")
                        
                        # Extract and format the JSONL line
                        line = (
                            f"{{ {row[0]}, \"{row[1]}\", [{row[2]}, {row[3]}, {row[4]}], {row[5] or 0}, {row[6]}, "
                            f"{json.dumps(row[7] if row[7] else [])}, {row[8]}, "
                            f"{row[9] if row[9] is not None else 0}, "
                            f"{row[10] if row[10] is not None else 0}, "
                            f"{row[11]}, {row[12]}, "
                            f"{json.dumps(row[13])}, {json.dumps(row[14])}, "
                            f"{row[15]}, {row[16]}, {row[17]}, {json.dumps(row[18] if row[18] else [])} }},"
                        )
                        
                        # Write the system line
                        f.write(line + '\n')
                
                if count > 0:
                    print("Removing trailing comma from last line...")
                    f.seek(0, os.SEEK_END)
                    pos = f.tell() - 2  # Position right before the last comma and newline
                    f.seek(pos, os.SEEK_SET)
                    f.truncate()
                    f.write('\n')
                
                end_time = datetime.now()
                duration = (end_time - start_time).total_seconds()
                print(f"Successfully exported {count} systems to {output_file} in {duration:.1f} seconds")
    
    finally:
        conn.close()
        print("Database connection closed")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Export power statistics from materialized view to JSONL file')
    parser.add_argument('--db', required=True, help='Database URL')
    parser.add_argument('--output', default='json/powerstats.jsonl', help='Output JSONL file path')
    parser.add_argument('--debug', action='store_true', help='Debug mode: limit to 10 systems')
    
    args = parser.parse_args()
    dump_power_stats_from_view(args.db, args.output, args.debug)