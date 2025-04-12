#!/usr/bin/env python3

import os
import sys
import json
import zlib
import time
import signal
import argparse
import socket
from datetime import datetime, timezone
import zmq
from urllib.parse import urlparse
import psycopg2
from psycopg2.extras import DictCursor
import logging
import atexit
import tornado.ioloop
import tornado.web
import tornado.websocket
import tornado.httpserver
import asyncio
import threading
from queue import Queue
from uuid import uuid4

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    stream=sys.stdout  # Ensure output goes to stdout
)
logger = logging.getLogger('zmq_broadcast')

# Constants
EDDN_RELAY = "tcp://eddn.edcd.io:9500"
ZMQ_PORT = int(os.getenv('ZMQ_PORT', '5559'))
WEBSOCKET_PORT = int(os.getenv('WEBSOCKET_PORT', '5560'))  # Changed from 5557 to 5560
ZMQ_TIMEOUT = 10000  # 10 seconds

# Global variables
running = True
DATABASE_URL = None
active_connections = set()
message_queue = Queue()

def get_timestamp():
    """Get current timestamp in ISO format with timezone"""
    return datetime.now(timezone.utc).isoformat()

def generate_uuid():
    """Generate a unique identifier for messages"""
    return str(uuid4())

def publish_message(publisher, event_type, data):
    """Publish a message to the ZMQ publisher and queue for WebSocket clients"""
    try:
        # Create a message with event type, timestamp, and data
        message = {
            "event": {
                "type": event_type,
                "timestamp": get_timestamp(),
                "uuid": generate_uuid()
            },
            "data": data
        }
        
        # Convert to JSON and send via ZMQ
        message_json = json.dumps(message)
        logger.debug(f"Publishing {event_type} message: {message_json[:100]}...")
        publisher.send_string(message_json)
        
        # Also queue for WebSocket clients
        message_queue.put(message_json)
        
        return True
    except Exception as e:
        logger.error(f"Error publishing message: {e}")
        return False

def get_system_data(conn, system_id64):
    """Get system data from the database"""
    try:
        cursor = conn.cursor(cursor_factory=DictCursor)
        cursor.execute("""
            SELECT id64, name, x, y, z, system_state, controlling_power, power_state, powers_acquiring
            FROM systems
            WHERE id64 = %s
        """, (system_id64,))
        
        system = cursor.fetchone()
        cursor.close()
        
        if not system:
            return None
            
        # Convert to dict if it's not already
        if not isinstance(system, dict):
            system = dict(system)
            
        # Convert any JSON fields
        if 'powers_acquiring' in system and system['powers_acquiring']:
            if isinstance(system['powers_acquiring'], str):
                system['powers_acquiring'] = json.loads(system['powers_acquiring'])
        
        return system
    except Exception as e:
        logger.error(f"Database error getting system data: {e}")
        return None

def process_journal_message(data, conn, publisher):
    """Process journal messages and create appropriate broadcast events"""
    try:
        # Get message data
        msg_data = data.get("message", {})
        event = msg_data.get("event")
        
        if not event:
            return False
            
        # FSDJump events may contain power data
        if event == "FSDJump":
            system_id64 = msg_data.get("SystemAddress")
            system_name = msg_data.get("StarSystem")
            
            if not system_id64 or not system_name:
                return False
                
            # Create power update if relevant fields are present
            if "ControllingPower" in msg_data or "PowerplayState" in msg_data or "Powers" in msg_data:
                # Get complete system data from database
                system_data = get_system_data(conn, system_id64)
                
                if system_data:
                    # Create power event with relevant data
                    power_data = {
                        "system_id64": system_id64,
                        "system_name": system_name,  # Use consistent naming
                        "name": system_name,
                        "x": system_data.get("x"),
                        "y": system_data.get("y"),
                        "z": system_data.get("z"),
                        "controlling_power": msg_data.get("ControllingPower", system_data.get("controlling_power")),
                        "power_state": msg_data.get("PowerplayState", system_data.get("power_state")),
                        "powers_acquiring": msg_data.get("Powers", system_data.get("powers_acquiring", []))
                    }
                    
                    # Publish power update
                    logger.info(f"Publishing power update for {system_name}")
                    publish_message(publisher, "power", power_data)
                    
            # Create system state update if relevant field is present
            if "SystemFaction" in msg_data and "Factions" in msg_data:
                system_faction = msg_data.get("SystemFaction", {}).get("Name")
                if system_faction:
                    current_state = None
                    
                    # Find the controlling faction's state
                    for faction in msg_data.get("Factions", []):
                        if faction.get("Name") == system_faction and "ActiveStates" in faction and faction["ActiveStates"]:
                            current_state = faction["ActiveStates"][0].get("State")
                            break
                    
                    if current_state:
                        # Get system data
                        system_data = get_system_data(conn, system_id64)
                        
                        if system_data:
                            # Create system event with relevant data
                            system_data = {
                                "system_id64": system_id64,
                                "system_name": system_name,  # Use consistent naming
                                "name": system_name,
                                "x": system_data.get("x"),
                                "y": system_data.get("y"),
                                "z": system_data.get("z"),
                                "system_state": current_state
                            }
                            
                            # Publish system update
                            logger.info(f"Publishing system state update for {system_name}: {current_state}")
                            publish_message(publisher, "system", system_data)
                
        # Handle colony ship events
        elif event in ["Docked", "FSSSignalDiscovered"]:
            # Check if this is a colony ship
            is_colony_ship = False
            
            if event == "Docked":
                station_name = msg_data.get("StationName", "")
                is_colony_ship = station_name == "System Colonisation Ship"
            elif event == "FSSSignalDiscovered":
                signal_name = msg_data.get("SignalName", "")
                is_colony_ship = signal_name == "System Colonisation Ship"
            
            if is_colony_ship:
                system_id64 = msg_data.get("SystemAddress")
                if system_id64:
                    # Get system data
                    system_data = get_system_data(conn, system_id64)
                    
                    if system_data:
                        # Create colony event with relevant data
                        colony_data = {
                            "system_id64": system_id64,
                            "system_name": system_data.get("name"),
                            "name": system_data.get("name"),
                            "x": system_data.get("x"),
                            "y": system_data.get("y"),
                            "z": system_data.get("z"),
                            "event_type": event,
                            "detected_at": get_timestamp()
                        }
                        
                        # Add event-specific data
                        if event == "Docked":
                            colony_data["station_name"] = msg_data.get("StationName")
                            colony_data["station_type"] = msg_data.get("StationType")
                            colony_data["station_id"] = msg_data.get("MarketID")
                        elif event == "FSSSignalDiscovered":
                            colony_data["signal_name"] = msg_data.get("SignalName")
                            colony_data["signal_type"] = msg_data.get("SignalType")
                        
                        # Publish colony update
                        logger.info(f"Publishing colony ship update for {system_data.get('name')}")
                        publish_message(publisher, "colony", colony_data)
        
        # Handle SAASignalsFound for haematite
        elif event == "SAASignalsFound":
            body_name = msg_data.get("BodyName")
            system_id64 = msg_data.get("SystemAddress")
            signals = msg_data.get("Signals", [])
            
            if body_name and system_id64 and signals:
                # Look for haematite signals
                hematite_signals = []
                for signal in signals:
                    signal_type = signal.get("Type", "")
                    if signal_type.lower() in ["haematite", "hematite", "hamaetite", "hemaetite"]:
                        hematite_signals.append(signal)
                
                if hematite_signals:
                    # Get system data
                    system_data = get_system_data(conn, system_id64)
                    
                    if system_data:
                        # Create haematite event with relevant data
                        haematite_data = {
                            "system_id64": system_id64,
                            "system_name": system_data.get("name"),
                            "name": system_data.get("name"),
                            "x": system_data.get("x"),
                            "y": system_data.get("y"),
                            "z": system_data.get("z"),
                            "body_name": body_name,
                            "signals": hematite_signals,
                            "haematite_count": sum([signal.get("Count", 0) for signal in hematite_signals]),
                            "detected_at": get_timestamp()
                        }
                        
                        # Publish haematite update
                        logger.info(f"Publishing haematite signals for {body_name} in {system_data.get('name')}")
                        publish_message(publisher, "haematite", haematite_data)
        
        # Forward original journal message
        journal_data = {
            "schema": data.get("$schemaRef"),
            "event_type": event,  # Add event type for proper display
            "data": msg_data      # Include the full message
        }
        logger.debug(f"Publishing journal event: {event}")
        publish_message(publisher, "journal", journal_data)
        
        return True
        
    except Exception as e:
        logger.error(f"Error processing journal message: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return False

def process_commodity_message(data, conn, publisher):
    """Process commodity messages and create appropriate broadcast events"""
    try:
        # Get message data
        msg_data = data.get("message", {})
        
        # Skip Fleet Carrier data
        if msg_data.get("stationType") == "FleetCarrier" or \
           (msg_data.get("economies") and msg_data["economies"][0].get("name") == "Carrier"):
            return False
            
        # Extract basic info
        station_name = msg_data.get("stationName")
        system_name = msg_data.get("systemName")
        
        if not station_name or not system_name:
            return False
        
        # Get system data from database
        try:
            cursor = conn.cursor(cursor_factory=DictCursor)
            cursor.execute("""
                SELECT id64, name, x, y, z
                FROM systems
                WHERE name = %s
            """, (system_name,))
            system = cursor.fetchone()
            cursor.close()
            
            if not system:
                return False
                
            # Create a filtered list of mining commodities
            commodities = []
            for commodity in msg_data.get("commodities", []):
                name = commodity.get("name", "").lower()
                sell_price = commodity.get("sellPrice", 0)
                demand = commodity.get("demand", 0)
                
                # Only include commodities with sell price
                if name and sell_price > 0:
                    commodities.append({
                        "name": name,
                        "sell_price": sell_price,
                        "demand": demand
                    })
            
            if commodities:
                # Create mining commodity event with relevant data
                mining_data = {
                    "system_id64": system["id64"],
                    "system_name": system_name,
                    "x": system["x"],
                    "y": system["y"],
                    "z": system["z"],
                    "station_name": station_name,
                    "updated_at": get_timestamp(),
                    "commodities": commodities
                }
                
                # Publish mining update
                logger.info(f"Publishing mining commodity update for {station_name} in {system_name}")
                publish_message(publisher, "mining", mining_data)
            
            # Forward original commodity message
            commodity_data = {
                "schema": data.get("$schemaRef"),
                "system_name": system_name,
                "station_name": station_name,
                "summary": {
                    "updated": len(msg_data.get("commodities", [])),
                    "added": 0,  # We don't track additions right now
                    "removed": 0  # We don't track removals right now
                }
            }
            logger.debug(f"Publishing commodity update for {station_name}")
            publish_message(publisher, "commodity", commodity_data)
            
            return True
                
        except Exception as e:
            logger.error(f"Database error in process_commodity_message: {e}")
            return False
            
    except Exception as e:
        logger.error(f"Error processing commodity message: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return False

def router_process_message(data, conn, publisher):
    """Central router function for all EDDN messages"""
    try:
        # Extract schema and message data
        schema_ref = data.get("$schemaRef", "").lower()
        
        if not schema_ref:
            return "unknown", False
            
        # Route based on schema
        if "journal" in schema_ref:
            result = process_journal_message(data, conn, publisher)
            return "journal", result
            
        elif "commodity" in schema_ref:
            result = process_commodity_message(data, conn, publisher)
            return "commodity", result
            
        else:
            # Unknown schema
            return "unknown", False
            
    except Exception as e:
        logger.error(f"Error in message router: {e}")
        import traceback
        logger.debug(f"Traceback: {traceback.format_exc()}")
        return "error", False

def cleanup():
    """Cleanup function to be called on exit"""
    logger.info("Cleaning up resources...")
    try:
        # Will close ZMQ resources that were registered during cleanup
        pass
    except:
        pass

def signal_handler(signum, frame):
    """Handle shutdown signals"""
    global running
    logger.info("Received shutdown signal, stopping...")
    running = False
    tornado.ioloop.IOLoop.current().add_callback(shutdown_tornado)

def shutdown_tornado():
    """Shutdown the Tornado IOLoop"""
    logger.info("Shutting down Tornado IOLoop...")
    tornado.ioloop.IOLoop.current().stop()

# WebSocket handler class
class WebSocketHandler(tornado.websocket.WebSocketHandler):
    def check_origin(self, origin):
        """Allow connections from any origin"""
        return True
        
    def open(self):
        """Handle new WebSocket connection"""
        global active_connections
        active_connections.add(self)
        logger.info(f"New WebSocket connection opened (total: {len(active_connections)})")
        
        # Send welcome message in the format expected by eddn-stream.html
        welcome_msg = {
            "type": "status",
            "timestamp": get_timestamp(),
            "data": {
                "status": "connected",
                "message": "Connected to EDDN Stream",
                "timestamp": get_timestamp()
            }
        }
        self.write_message(json.dumps(welcome_msg))
        
    def on_close(self):
        """Handle WebSocket disconnection"""
        global active_connections
        active_connections.remove(self)
        logger.info(f"WebSocket connection closed (remaining: {len(active_connections)})")
        
    def on_message(self, message):
        """Handle incoming WebSocket message"""
        try:
            # Parse the message as JSON
            data = json.loads(message)
            
            # Currently we don't expect or handle any client messages
            # But we could add command handling here in the future
            logger.debug(f"Received WebSocket message: {data}")
            
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {e}")

# Simple handler that returns a status message for HTTP requests
class MainHandler(tornado.web.RequestHandler):
    def get(self):
        """Handle GET requests to root paths that aren't WebSocket"""
        self.set_header("Content-Type", "text/plain")
        self.write("EDDN WebSocket Server Running\n")
        self.write("To connect with a WebSocket client, use this same URL with the ws:// protocol")

# Function to broadcast messages to all WebSocket clients
async def broadcast_messages():
    """Broadcast queued messages to all WebSocket clients"""
    global active_connections, message_queue, running
    
    while running:
        try:
            # Check if there are messages to send
            if not message_queue.empty():
                message = message_queue.get()
                
                try:
                    # Parse the message to properly format for the HTML client
                    data = json.loads(message)
                    event_data = data.get("event", {})
                    event_type = event_data.get("type", "unknown")
                    event_timestamp = event_data.get("timestamp", get_timestamp())
                    
                    # Format the message in the structure expected by eddn-stream.html
                    # The HTML expects a specific format with "type", "timestamp", and "data" fields
                    formatted_message = {
                        "type": event_type,  # This is the key field for tab categorization
                        "timestamp": event_timestamp,
                        "data": data.get("data", {})
                    }
                    
                    # Debug logging
                    logger.debug(f"Broadcasting message of type: {event_type}")
                    
                    # Convert to JSON for transmission
                    formatted_json = json.dumps(formatted_message)
                    
                    # Broadcast to all connected clients
                    for client in list(active_connections):
                        try:
                            await client.write_message(formatted_json)
                        except Exception as e:
                            logger.error(f"Error sending message to client: {e}")
                            # Client might be disconnected
                            if client in active_connections:
                                active_connections.remove(client)
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in message queue: {message}")
                except Exception as e:
                    logger.error(f"Error formatting message: {e}")
            
            # Prevent CPU hogging - small delay
            await asyncio.sleep(0.01)
            
        except Exception as e:
            logger.error(f"Error in broadcast_messages: {e}")
            await asyncio.sleep(1)  # Longer delay on error

# Function to run the tornado web server
def run_tornado_server(port):
    """Run Tornado WebSocket server"""
    try:
        # Create Tornado application
        logger.info(f"Starting WebSocket server on port {port}")
        logger.info(f"WebSocket clients should connect to: ws://hostname:{port} or ws://hostname/zmq in production with nginx")
        
        # Create application with port in settings
        tornado_app = tornado.web.Application([
            (r"/", WebSocketHandler),  # Serve WebSocket on root path for direct connection
            (r"/zmq", WebSocketHandler),  # Also serve on /zmq path for production
            (r"/status", MainHandler),  # Add status handler
        ], ws_port=port)
        
        # Create HTTP server
        http_server = tornado.httpserver.HTTPServer(tornado_app)
        http_server.listen(port)
        
        # Start the broadcast_messages task in the event loop
        loop = tornado.ioloop.IOLoop.current()
        loop.add_callback(broadcast_messages)
        
        # Start tornado in a separate thread
        tornado_thread = threading.Thread(target=loop.start)
        tornado_thread.daemon = True
        tornado_thread.start()
        
        logger.info(f"WebSocket server running at ws://localhost:{port} and ws://localhost:{port}/zmq")
        logger.info(f"For eddn-stream.html compatibility, connections are accepted on both paths")
        
    except Exception as e:
        logger.error(f"Error starting WebSocket server: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

def main():
    """Main function"""
    global running, DATABASE_URL
    
    # Register cleanup
    atexit.register(cleanup)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='EDDN Message Broadcaster')
    parser.add_argument('--debug', action='store_true', help='Enable debug output')
    parser.add_argument('--local', action='store_true', help='Run in local mode (bind only to localhost)')
    parser.add_argument('--db', help='Database URL (e.g. postgresql://user:pass@host:port/dbname)')
    parser.add_argument('--ws-port', type=int, default=WEBSOCKET_PORT, help=f'WebSocket server port (default: {WEBSOCKET_PORT})')
    args = parser.parse_args()
    
    # Set log level
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Set DATABASE_URL from argument or environment variable
    DATABASE_URL = args.db or os.getenv('DATABASE_URL')
    if not DATABASE_URL:
        logger.error("Database URL must be provided via --db argument or DATABASE_URL environment variable")
        return 1
    
    # Determine mode (local or web)
    is_local_mode = args.local
    mode = "local" if is_local_mode else "web"
    logger.info(f"Starting ZMQ Broadcaster in {mode.upper()} mode")
    
    try:
        # Setup database connection
        logger.info("Connecting to database...")
        db_url = urlparse(DATABASE_URL)
        logger.info(f"Database: {db_url.hostname}:{db_url.port}/{db_url.path[1:]}")
        
        conn = psycopg2.connect(DATABASE_URL)
        conn.autocommit = True
        
        # Test database connection
        cursor = conn.cursor()
        cursor.execute("SELECT version()")
        version = cursor.fetchone()[0]
        logger.info(f"Connected to PostgreSQL: {version}")
        cursor.close()
        
        # Setup ZMQ context and publisher
        zmq_context = zmq.Context()
        publisher = zmq_context.socket(zmq.PUB)
        
        # Binding address depends on mode - where we publish to
        if is_local_mode:
            bind_address = f"tcp://127.0.0.1:{ZMQ_PORT}"
            logger.info(f"LOCAL MODE: Binding ZMQ publisher to {bind_address}")
        else:
            bind_address = f"tcp://0.0.0.0:{ZMQ_PORT}"
            logger.info(f"WEB MODE: Binding ZMQ publisher to {bind_address}")
            
        publisher.bind(bind_address)
        logger.info(f"ZMQ publisher bound to {bind_address}")
        
        # Setup ZMQ subscriber for EDDN
        subscriber = zmq_context.socket(zmq.SUB)
        subscriber.setsockopt(zmq.SUBSCRIBE, b"")
        subscriber.setsockopt(zmq.RCVTIMEO, ZMQ_TIMEOUT)
        
        # Create a list of addresses to try connecting to for the bridge
        # This is where ZMQ clients would connect to receive our published messages
        if is_local_mode:
            # Local mode - only try localhost addresses
            client_addresses = [
                f"tcp://localhost:{ZMQ_PORT}",
                f"tcp://127.0.0.1:{ZMQ_PORT}",
                f"tcp://0.0.0.0:{ZMQ_PORT}"
            ]
            logger.info("Running in LOCAL mode - clients should connect to localhost")
        else:
            # Server mode - try container names first, then localhost as fallback
            client_addresses = [
                f"tcp://powermining-zmq_bridge-1:{ZMQ_PORT}",  # Container name first
                f"tcp://localhost:{ZMQ_PORT}",                # Then localhost
                f"tcp://127.0.0.1:{ZMQ_PORT}",                # Another localhost option
                f"tcp://0.0.0.0:{ZMQ_PORT}"                   # Bind to all interfaces
            ]
            logger.info("Running in WEB mode - clients should try container name first")
        
        # Log the recommended client connection addresses
        logger.info("Client connection addresses (in recommended order):")
        for i, addr in enumerate(client_addresses):
            logger.info(f"  {i+1}. {addr}")
            
        # Start WebSocket server in a separate thread
        websocket_port = args.ws_port
        logger.info(f"Starting WebSocket server on port {websocket_port}")
        
        # Start Tornado in a separate thread
        tornado_thread = threading.Thread(
            target=run_tornado_server,
            args=(websocket_port,),
            daemon=True
        )
        tornado_thread.start()
        
        # Connect to EDDN
        logger.info(f"Connecting to EDDN relay: {EDDN_RELAY}")
        subscriber.connect(EDDN_RELAY)
        logger.info("Connected to EDDN relay")
        
        # Log network interfaces
        hostname = socket.gethostname()
        try:
            local_ip = socket.gethostbyname(hostname)
            logger.info(f"Running on: {hostname} ({local_ip})")
        except Exception as e:
            logger.error(f"Could not get local IP: {e}")
        
        # Publish startup message
        startup_data = {
            "status": "started",
            "mode": mode,
            "client_addresses": client_addresses,
            "websocket_port": websocket_port,
            "timestamp": get_timestamp()
        }
        publish_message(publisher, "status", startup_data)
        
        # Counter for stats
        total_messages = 0
        processed_messages = 0
        last_status_time = time.time()
        
        # Main processing loop
        logger.info("Starting main processing loop, press Ctrl+C to stop")
        while running:
            try:
                # Receive message from EDDN with timeout
                raw_message = subscriber.recv()
                
                # Decompress message
                message = zlib.decompress(raw_message)
                
                # Parse as JSON
                data = json.loads(message)
                
                # Route message based on schema
                message_type, result = router_process_message(data, conn, publisher)
                
                # Update counters
                total_messages += 1
                if result:
                    processed_messages += 1
                
                # Log periodic status
                current_time = time.time()
                if current_time - last_status_time >= 60:  # Every minute
                    logger.info(f"Stats: processed {processed_messages}/{total_messages} messages")
                    
                    # Publish status update
                    status_data = {
                        "status": "running",
                        "mode": mode,
                        "total_messages": total_messages,
                        "processed_messages": processed_messages,
                        "active_websocket_clients": len(active_connections),
                        "timestamp": get_timestamp()
                    }
                    publish_message(publisher, "status", status_data)
                    
                    last_status_time = current_time
                    
            except zmq.error.Again:
                # Timeout on receive, just continue
                continue
                
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received, stopping...")
                running = False
                break
                
            except Exception as e:
                logger.error(f"Error processing message: {e}")
                import traceback
                logger.debug(f"Traceback: {traceback.format_exc()}")
                continue
        
        # Publish shutdown message
        shutdown_data = {
            "status": "stopping",
            "mode": mode,
            "total_messages": total_messages,
            "processed_messages": processed_messages,
            "timestamp": get_timestamp()
        }
        publish_message(publisher, "status", shutdown_data)
        
        # Wait for tornado thread to finish
        logger.info("Waiting for WebSocket server to shut down...")
        tornado_thread.join(timeout=5)
        
        # Cleanup connections
        logger.info("Cleaning up connections...")
        subscriber.disconnect(EDDN_RELAY)
        subscriber.close()
        publisher.close()
        zmq_context.term()
        conn.close()
        
        logger.info("ZMQ Broadcaster stopped")
        
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1
        
    return 0

if __name__ == "__main__":
    sys.exit(main())
