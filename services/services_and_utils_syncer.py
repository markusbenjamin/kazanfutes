"""
Syncs the contents of the services and utils folders with the online repo.
"""

from utils.project import *

settings['dev'] = True
settings['verbosity'] = True

success = False
try:
    check_index_lock()
    sync_dir_with_repo('services/', 'Sync services.')
    sync_dir_with_repo('utils/', 'Sync utils.')
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to sync services and utils with repo", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to sync services and utils with repo", severity = 2)

log({"success":success})