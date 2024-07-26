import logging
from logging.handlers import RotatingFileHandler
import json

# Configure logging
logger = logging.getLogger('custom_log')
logger.setLevel(logging.INFO)

# Create a rotating file handler
handler = RotatingFileHandler('custom_log.log', maxBytes=5*1024*1024, backupCount=2)
logger.addHandler(handler)

# Custom log entry as a dictionary
log_entry = {
    "event": "UserLoginAttempt",
    "user": "johndoe",
    "outcome": "success",
    "timestamp": "2023-11-05T12:34:56"
}

# Write custom log entry
logger.info('%s', log_entry)  # Log as string representation

# Convert log entry to a JSON-formatted string
json_log_entry = json.dumps(log_entry)

# Write custom JSON log entry
logger.info('%s', json_log_entry)  # Log as JSON string
