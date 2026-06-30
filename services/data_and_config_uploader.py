"""
Syncs the contents of the data folder to the online repo.
"""

from utils.project import *

success = False
try:
    check_index_lock()
    if not sync_paths_with_repo(['data/', 'config/', 'system/state.json'], 'Automatic data and config push.', 30):
        report("Data and config paths locked, couldn't push.")
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to sync data and config with repo", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to sync data and config with repo", severity = 2)

log({"success":success})
