"""
Logs occupancy state of rooms.
"""

from utils.project import *

success = False
try:
    # Log presence
    log_data({"timestamp": timestamp(), "states":get_rooms_occupancy()},'occupancy/occupancy.json')
    report("Occupancy acquired and logged.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to acquire occupancy states", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while trying to acquire occupancy states", severity = 2)

# Log execution
log({"success":success})