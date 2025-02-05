"""
Logs Oktopusz presence.
"""

from utils.project import *

success = False
try:
    # Log presence
    log_data(get_oktopusz_presence(),'presence/oktopusz_presence.json')
    report("Oktopusz presence acquired and logged.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to acquire Oktopusz presence state", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while trying to acquire Oktopusz presence state", severity = 2)

# Log execution
log({"success":success})