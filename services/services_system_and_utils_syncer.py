"""
Syncs the contents of the services, system and utils folders with the online repo.
"""

from utils.project import *

settings['verbose'] = True
settings['log'] = False

success = False
try:
    check_index_lock()
    if not sync_paths_with_repo(['services/', 'system/', 'utils/'], 'Sync services, system def and utils.', 30):
        report("Services, system or utils paths locked, couldn't push.")
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to sync services, system def and utils with repo", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to sync services, system def and utils with repo", severity = 2)

log({"success":success})
