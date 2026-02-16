"""
Logs state of presence in rooms.
"""

from utils.project import *

success = False
try:
    # Log presence
    log_data({"timestamp": timestamp(), "states":get_presence_rooms()},'presence/presence_all.json')
    report("Presence acquired and logged.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to acquire presence states", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while trying to acquire presence states", severity = 2)

# Log execution
log({"success":success})