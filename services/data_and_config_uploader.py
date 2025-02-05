"""
Syncs the contents of the data folder to the online repo.
"""

from utils.project import *

success = False
try:
    check_index_lock()
    sync_dir_with_repo('data/', 'Automatic data push.')
    sync_dir_with_repo('config/', 'Automatic config push.')
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to sync data and config with repo", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to sync data and config with repo", severity = 2)

log({"success":success})