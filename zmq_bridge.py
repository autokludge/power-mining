import asyncio
import websockets
import zmq.asyncio
import json
from datetime import datetime, timezone
import socket as socket_lib  # Rename the socket module import
import argparse  # Add argparse for command-line arguments
import logging
import hashlib  # For content hashing
import time  # For timestamp in UUID generation

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('zmq_bridge')

# Global variables
active_connections = set()
message_cache = {}  # Store message hashes to detect duplicates
MAX_CACHE_SIZE = 1000  # Maximum number of message hashes to keep
CACHE_EXPIRY = 60  # Seconds to keep messages in cache

def generate_fast_uuid():
    """Generate a fast, unique identifier based on timestamp and counter"""
    return f"{time.time_ns()}-{id(time)}"

def get_content_hash(data):
    """Generate a hash of the message content for deduplication"""
    # Remove fields that might change between identical messages
    content_copy = data.copy()
    content_copy.pop('timestamp', None)
    content_copy.pop('uuid', None)
    
    # Convert to a stable string representation and hash
    content_str = json.dumps(content_copy, sort_keys=True)
    return hashlib.md5(content_str.encode()).hexdigest()

async def zmq_to_websocket(websocket, path):
    """Handle a WebSocket connection and forward ZMQ messages to it."""
    # Declare global variables that will be modified
    global message_cache
    
    client_id = id(websocket)
    remote_address = websocket.remote_address if hasattr(websocket, 'remote_address') else 'unknown'
    
    logger.info(f"New WebSocket connection from {remote_address} (ID: {client_id})")
    
    # Add to active connections
    active_connections.add(websocket)
    
    # Print network information
    hostname = socket_lib.gethostname()
    try:
        local_ip = socket_lib.gethostbyname(hostname)
        logger.info(f"Bridge running on: {hostname} ({local_ip})")
    except Exception as e:
        logger.error(f"Could not get local IP: {e}")

    # Setup ZMQ subscriber
    logger.info(f"Setting up ZMQ Subscriber for client {client_id}")
    context = zmq.asyncio.Context()
    zmq_socket = context.socket(zmq.SUB)
    zmq_socket.setsockopt_string(zmq.SUBSCRIBE, "")
    
    # Get the local mode flag from the global context
    is_local_mode = getattr(asyncio.get_running_loop(), 'is_local_mode', False)
    
    # Choose addresses based on mode
    if is_local_mode:
        # Local mode - only try localhost addresses
        addresses = [
            "tcp://localhost:5559",
            "tcp://127.0.0.1:5559",
            "tcp://0.0.0.0:5559"
        ]
        logger.info("Running in LOCAL mode - only trying localhost connections")
    else:
        # Server mode - try container names first, then localhost as fallback
        addresses = [
            "tcp://powermining-update-1:5559",  # Container name first
            "tcp://localhost:5559",             # Then localhost
            "tcp://127.0.0.1:5559",             # Another localhost option
            "tcp://0.0.0.0:5559"                # Bind to all interfaces
        ]
        logger.info("Running in SERVER mode - prioritizing container connections")
    
    # Statistics for duplicate detection
    duplicate_count = 0
    total_messages = 0
    
    # Local message cache for this connection
    local_message_cache = {}
    
    connected = False
    for addr in addresses:
        try:
            logger.info(f"Attempting to connect to {addr}")
            zmq_socket.connect(addr)
            logger.info(f"✓ Successfully connected to {addr}")
            connected = True
            break
        except Exception as e:
            logger.warning(f"✗ Failed to connect to {addr}: {e}")
    
    if not connected:
        logger.error(f"✗ Could not connect to any ZMQ endpoint!")
        active_connections.remove(websocket)
        return

    logger.info(f"Starting message loop for client {client_id}")
    try:
        while True:
            try:
                # Set a timeout for receiving messages
                message = await asyncio.wait_for(zmq_socket.recv_string(), timeout=5.0)
                logger.debug(f"Received ZMQ message")
                total_messages += 1
                
                try:
                    data = json.loads(message)
                    
                    # Add timestamp if not present
                    if 'timestamp' not in data:
                        data['timestamp'] = datetime.now(timezone.utc).isoformat()
                    
                    # Add UUID for tracking
                    data['uuid'] = generate_fast_uuid()
                    
                    # Generate content hash for deduplication
                    content_hash = get_content_hash(data)
                    current_time = time.time()
                    
                    # Check if this is a duplicate message
                    is_duplicate = False
                    if content_hash in local_message_cache:
                        last_seen, _ = local_message_cache[content_hash]
                        if current_time - last_seen < CACHE_EXPIRY:
                            duplicate_count += 1
                            is_duplicate = True
                            logger.debug(f"Duplicate message detected (hash: {content_hash})")
                            
                            # Log duplicate statistics every 100 duplicates
                            if duplicate_count % 100 == 0:
                                dupe_percent = (duplicate_count / total_messages) * 100
                                logger.info(f"Duplicate statistics: {duplicate_count}/{total_messages} messages ({dupe_percent:.2f}%)")
                    
                    # Update cache with this message
                    local_message_cache[content_hash] = (current_time, data['uuid'])
                    
                    # Clean up old cache entries
                    if len(local_message_cache) > MAX_CACHE_SIZE:
                        # Remove expired entries
                        current_time = time.time()
                        local_message_cache = {
                            k: v for k, v in local_message_cache.items() 
                            if current_time - v[0] < CACHE_EXPIRY
                        }
                        
                        # If still too large, remove oldest entries
                        if len(local_message_cache) > MAX_CACHE_SIZE:
                            sorted_cache = sorted(local_message_cache.items(), key=lambda x: x[1][0])
                            local_message_cache = dict(sorted_cache[-MAX_CACHE_SIZE:])
                    
                    # Skip sending if it's a duplicate
                    if is_duplicate:
                        continue
                    
                    # Check if the WebSocket is still open before sending
                    if websocket.open:
                        await websocket.send(json.dumps(data))
                        logger.debug(f"✓ Forwarded message to WebSocket client {client_id}")
                    else:
                        logger.warning(f"WebSocket for client {client_id} is closed, stopping message loop")
                        break
                    
                except json.JSONDecodeError:
                    logger.warning(f"✗ Invalid JSON message: {message[:100]}...")
                    continue
                
            except asyncio.TimeoutError:
                # Send a ping to check if the connection is still alive
                try:
                    pong_waiter = await websocket.ping()
                    await asyncio.wait_for(pong_waiter, timeout=2.0)
                    logger.debug(f"No messages received in last 5 seconds, but connection is alive")
                except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
                    logger.warning(f"WebSocket ping failed for client {client_id}, closing connection")
                    break
                continue
            except websockets.exceptions.ConnectionClosed as e:
                logger.info(f"WebSocket connection closed by client {client_id}: {e}")
                break
            except Exception as e:
                logger.error(f"✗ Error processing message for client {client_id}: {e}")
                continue
                
    except websockets.exceptions.ConnectionClosed as e:
        logger.info(f"WebSocket connection closed by client {client_id}: {e}")
    except Exception as e:
        logger.error(f"Unexpected error for client {client_id}: {e}")
    finally:
        # Clean up resources
        zmq_socket.close()
        context.term()
        
        # Remove from active connections
        if websocket in active_connections:
            active_connections.remove(websocket)
        
        # Log duplicate statistics at the end
        if total_messages > 0:
            dupe_percent = (duplicate_count / total_messages) * 100
            logger.info(f"Final duplicate statistics for client {client_id}: {duplicate_count}/{total_messages} messages ({dupe_percent:.2f}%)")
            
        logger.info(f"Cleaned up ZMQ connection for client {client_id}, {len(active_connections)} active connections remaining")

async def main():
    # Parse command-line arguments
    parser = argparse.ArgumentParser(description='ZMQ to WebSocket Bridge')
    parser.add_argument('--server', help='Server hostname:ip for the bridge')
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    parser.add_argument('--local', action='store_true', help='Run in local mode (only connect to localhost)')
    args = parser.parse_args()
    
    # Set log level
    if args.debug:
        logger.setLevel(logging.DEBUG)
    
    # Store local mode flag in the event loop for access in the handler
    loop = asyncio.get_running_loop()
    loop.is_local_mode = args.local
    
    if args.local:
        logger.info("Starting WebSocket Bridge in LOCAL mode")
    else:
        logger.info("Starting WebSocket Bridge in SERVER mode")
    
    # Get server information
    hostname = socket_lib.gethostname()
    local_ip = None
    
    try:
        # If --server argument is provided, use that information
        if args.server:
            server_parts = args.server.split(':')
            if len(server_parts) == 2:
                hostname = server_parts[0]
                local_ip = server_parts[1]
                logger.info(f"Using provided server information: hostname={hostname}, IP={local_ip}")
            else:
                logger.warning(f"Invalid server format. Expected format: hostname:ip")
                logger.warning(f"Falling back to automatic detection")
        
        # If IP wasn't provided or was invalid, try to detect it
        if not local_ip:
            local_ip = socket_lib.gethostbyname(hostname)
    except Exception as e:
        logger.error(f"Could not get local IP: {e}")
        local_ip = "0.0.0.0"  # Fallback
    
    try:
        server = await websockets.serve(
            zmq_to_websocket,
            "0.0.0.0",  # Listen on all interfaces
            5560,
            ping_interval=30,  # Send ping every 30 seconds
            ping_timeout=10,   # Wait 10 seconds for pong response
            close_timeout=5    # Wait 5 seconds for close handshake
        )
        logger.info(f"✓ WebSocket server running on ws://0.0.0.0:5560")
        
        # Print network information
        logger.info(f"Server hostname: {hostname}")
        logger.info(f"Server IP: {local_ip}")
            
        await server.wait_closed()
        
    except Exception as e:
        logger.error(f"✗ Failed to start server: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Shutting down by user request...")
    except Exception as e:
        logger.error(f"Fatal error: {e}")