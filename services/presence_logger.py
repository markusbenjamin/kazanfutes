"""
Logs state of presence sensor.
"""

from utils.project import *

success = False
try:
    # Log presence
    log_data(get_presence(),'presence/presence.json')
    report("Presence acquired and logged.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to acquire presence state", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while trying to acquire presence state", severity = 2)

# Log execution
log({"success":success})