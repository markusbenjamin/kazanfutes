"""
Syncs the contents of the data folder to the online repo.
"""

from utils.project import *

success = False
try:
    check_index_lock()
    if not sync_dir_with_repo('data/', 'Automatic data push.', 30):
        report("Data dir locked, couldn't push.")
    if not sync_dir_with_repo('config/', 'Automatic config push.', 30):
        report("Config dir locked, couldn't push.")
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to sync data and config with repo", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to sync data and config with repo", severity = 2)

log({"success":success})