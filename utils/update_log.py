import os
from datetime import datetime

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
    "STATION": "🏠"
}

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
    
    formatted_tag = format_tag(tag)
    print(f"{color}[{timestamp}] [{os.getpid()}] {formatted_tag} {message}{RESET}", flush=True)

def set_debug_level(level):
    """Set the global debug level
    
    Args:
        level (int): Debug level (0=none, 1=critical, 2=normal, 3=verbose)
    """
    global DEBUG_LEVEL
    DEBUG_LEVEL = level
