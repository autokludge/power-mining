import os
from datetime import datetime
import psycopg2
import json
import threading
from datetime import datetime, timezone

# ANSI color codes
YELLOW = '\033[93m'  # Default color
BLUE = '\033[94m'
MAGENTA = '\033[92m'
RED = '\033[91m'
CYAN = '\033[96m' 
ORANGE = '\033[38;5;208m'
GREEN = '\033[95m'  
RESET = '\033[0m'

# Debug levels
DEBUG_LEVEL = 2  # 1 = critical/important, 2 = normal, 3 = verbose/detailed

# Icon Mapping
ICONS = {
    "COLONY": "🚩",
    "DOCKED": "🚢",
    "UNDOCKED": "🚤",
    "UNKNOWN": "❓",
    "POWER": "🔻",
    "HEMATITE": "💎",
    "STATE": "🏛️",
    "DATABASE": "💾",
    "STATUS": "📊",
    "ERROR": "❌",
    "COMMODITY": "📦",
    "INIT": "🚀",
    "STOPPING": "🛑",
    "CONNECTED": "🔌",
    "MODE": "⚙️",
    "TERMINATED": "🏁",
    "DEBUG": "🔍",
    "JOURNAL": "📓",
    "ROUTER": "🔀",
    "SYSTEM": "🌐",
    "STATION": "🏠",
    "TRACK": "📋"
}



class MessageTracker:
    """Clean interface for tracking EDDN message processing"""
    
    def __init__(self, database_url, enabled=True):
        """Initialize tracker with database connection
        
        Args:
            database_url (str): Database connection string
            enabled (bool): Whether tracking is enabled
        """
        self.database_url = database_url
        self.enabled = enabled
        
        # Event type mapping
        self.event_types = {
            'FSDJump': 1,
            'Docked': 2,
            'Location': 3,
            'Commodity': 4
        }
        
        # Category mapping
        self.categories = {
            'systems': 1,
            'stations': 2
        }
    
    def add(self, raw_data, event_type, category, name, id64):
        """Track an incoming EDDN message
        
        Args:
            raw_data (dict): Complete EDDN message with header and message
            event_type (str): Event type (FSDJump, Docked, Location, Commodity)
            category (str): "systems" or "stations"
            name (str): System name or station name
            id64 (int): System ID64 or Station ID64
            
        Returns:
            int: Message ID for tracking, or None if tracking disabled/failed
        """
        if not self.enabled or not self.database_url:
            return None
            
        try:
            # Extract required data
            header = raw_data.get("header", {})
            message_data = raw_data.get("message", {})
            
            gateway_timestamp = header.get("gatewayTimestamp")
            timestamp = message_data.get("timestamp")
            uploader_id = header.get("uploaderID")
            
            # Validate required fields
            if not gateway_timestamp or not timestamp or event_type not in self.event_types or category not in self.categories:
                log_message("TRACK", f"Missing required fields for tracking", level=2)
                return None
            
            # Parse gateway timestamp for TIMESTAMPTZ column
            gateway_dt = self._parse_gateway_timestamp(gateway_timestamp)
            if not gateway_dt:
                return None
                
            # Insert tracking record
            return self._insert_tracking_record(
                gateway_dt, timestamp, self.event_types[event_type], 
                self.categories[category], name, id64, uploader_id
            )
            
        except Exception as e:
            log_message("ERROR", f"Error tracking message: {str(e)}", level=1)
            import traceback
            log_message("ERROR", f"Tracker traceback: {traceback.format_exc()}", level=1)
            return None
    
    def write(self, message_id):
        """Mark message processing as completed
        
        Args:
            message_id (int): Message ID from add()
        """
        if not self.enabled or not message_id:
            return
            
        self._update_field_async(message_id, "write_time", datetime.now(timezone.utc))
    
    def verify(self, message_timestamp, db_timestamp):
        """Verify that message processing was successful by comparing timestamps
        
        Args:
            message_timestamp (str): Original EDDN message timestamp
            db_timestamp (str or datetime): Database timestamp from timestamp column
            
        Returns:
            bool: True if timestamps match (indicating successful processing)
        """
        try:
            if isinstance(db_timestamp, str):
                # String comparison
                result = message_timestamp == db_timestamp
            else:
                # Convert datetime to EDDN string format for comparison
                db_timestamp_str = db_timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
                result = message_timestamp == db_timestamp_str
                
            log_message("TRACK", f"Timestamp verification: match={result}", level=3)
            return result
        except Exception as e:
            log_message("ERROR", f"Error verifying processing: {str(e)}", level=1)
            return False
    
    def success(self, message_id, succeeded, message_timestamp=None, db_timestamp=None, category=None):
        """Mark final processing success/failure with optional verification
        
        Args:
            message_id (int): Message ID from add()
            succeeded (bool): True if processing succeeded
            message_timestamp (str, optional): Original message timestamp for verification
            db_timestamp (str, optional): Database timestamp for verification
            category (str, optional): Category for logging
        """
        if not message_id:
            return
            
        try:
            # If we have timestamps, verify they match
            if succeeded and message_timestamp and db_timestamp:
                timestamp_match = self.verify(message_timestamp, db_timestamp)
                final_result = succeeded and timestamp_match
                
                if not timestamp_match:
                    log_message("TRACK", f"Message {message_id} processing failed - timestamp mismatch in {category}", level=2)
                else:
                    log_message("TRACK", f"Message {message_id} processing verified successful in {category}", level=3)
            else:
                final_result = succeeded
                
            self._update_field_async(message_id, "check_result", final_result)
            
        except Exception as e:
            log_message("ERROR", f"Error tracking success: {str(e)}", level=1)
            self._update_field_async(message_id, "check_result", False)
    
    def _parse_gateway_timestamp(self, gateway_timestamp):
        """Parse gateway timestamp to datetime object"""
        try:
            if 'T' in gateway_timestamp and gateway_timestamp.endswith('Z'):
                return datetime.strptime(gateway_timestamp, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
            else:
                log_message("TRACK", f"Invalid gateway timestamp format: {gateway_timestamp}", level=2)
                return None
        except ValueError as e:
            log_message("TRACK", f"Failed to parse gateway timestamp: {str(e)}", level=2)
            return None
    
    def _insert_tracking_record(self, gateway_dt, timestamp, event_int, category, name, id64, uploader_id):
        """Insert new tracking record and return message ID"""
        try:
            with psycopg2.connect(self.database_url) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO messages (
                        gateway_timestamp, timestamp, event, category, 
                        name, id64, uploader_id, read_time
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s
                    ) RETURNING id
                """, (
                    gateway_dt, timestamp, event_int, category,
                    name, id64, uploader_id, datetime.now(timezone.utc)
                ))
                message_id = cursor.fetchone()[0]
                log_message("TRACK", f"Tracked message for {category} {name} (ID: {message_id})", level=3)
                return message_id
        except Exception as e:
            log_message("ERROR", f"Failed to insert tracking record: {str(e)}", level=1)
            return None
    
    def _update_field_async(self, message_id, field_name, value):
        """Update a field in the messages table asynchronously"""
        def update_field():
            try:
                with psycopg2.connect(self.database_url) as conn:
                    cursor = conn.cursor()
                    cursor.execute(f"""
                        UPDATE messages 
                        SET {field_name} = %s 
                        WHERE id = %s
                    """, (value, message_id))
                    log_message("TRACK", f"Updated {field_name} for message {message_id}", level=3)
            except Exception as e:
                log_message("ERROR", f"Failed to update {field_name} for message {message_id}: {str(e)}", level=1)
        
        # Run in background thread for non-blocking operation
        thread = threading.Thread(target=update_field)
        thread.daemon = True
        thread.start()


# Global tracker instance (set by main process)
tracker = None

def set_tracker(database_url, enabled=True):
    """Initialize global tracker instance"""
    global tracker
    tracker = MessageTracker(database_url, enabled)

def format_tag(tag):
    """Format a tag with its icon if available - returns [ICON TAG]"""
    icon = ICONS.get(tag, "")
    return f"[{icon} {tag}]" if icon else f"[{tag}]"

def log_message(tag, message, level=2):
    """Log a message with timestamp and PID
    
    Args:
        tag (str): Message category
        message (str): The message to log
        level (int): Debug level (1=important, 2=normal, 3=verbose)
    """
    # Skip messages with level higher than DEBUG_LEVEL
    if DEBUG_LEVEL == 0 or level > DEBUG_LEVEL:
        return
        
    timestamp = datetime.now().strftime("%Y:%m:%d-%H:%M:%S")
    color = YELLOW  # Default color
    
    if tag == "STATUS":
        color = RED
    elif tag == "DATABASE":
        color = CYAN
    elif tag == "COLONY":
        color = YELLOW
    elif tag == "POWER":
        color = MAGENTA        
    elif tag == "ERROR":
        color = RED
    elif tag == "TRACK":
        color = BLUE
    
    formatted_tag = format_tag(tag)
    print(f"{color}[{timestamp}] [{os.getpid()}] {formatted_tag} {message}{RESET}", flush=True)

def set_debug_level(level):
    """Set the global debug level
    
    Args:
        level (int): Debug level (0=none, 1=critical, 2=normal, 3=verbose)
    """
    global DEBUG_LEVEL
    DEBUG_LEVEL = level

def convert_eddn_timestamp_to_db(eddn_timestamp):
    """Convert EDDN timestamp to database format
    
    Args:
        eddn_timestamp (str): EDDN format "2025-06-26T22:30:28Z"
        
    Returns:
        str: Database format "2025-06-26 22:30:28" or None if parsing fails
    """
    if not eddn_timestamp:
        return None
        
    try:
        # Parse EDDN format and convert to database format
        if 'T' in eddn_timestamp and eddn_timestamp.endswith('Z'):
            dt = datetime.strptime(eddn_timestamp, "%Y-%m-%dT%H:%M:%SZ")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        else:
            log_message("ERROR", f"Invalid EDDN timestamp format: {eddn_timestamp}", level=1)
            return None
    except ValueError as e:
        log_message("ERROR", f"Failed to convert EDDN timestamp '{eddn_timestamp}': {str(e)}", level=1)
        return None




