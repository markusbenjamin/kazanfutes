"""
Syncs the contents of the services, system and utils folders with the online repo.
"""

from utils.project import *

settings['verbose'] = True
settings['log'] = False

success = False
try:
    check_index_lock()
    if not sync_dir_with_repo('services/', 'Sync services.', 30):
        report("Services dir locked, couldn't push.")
    if not sync_dir_with_repo('system/', 'Sync system def.', 30):
        report("System dir locked, couldn't push.")
    if not sync_dir_with_repo('utils/', 'Sync utils.', 30):
        report("Utils dir locked, couldn't push.")
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to sync services, system def and utils with repo", original_exception=e, severity = 2)
except Exception:
    ServiceException("Unexpected error while trying to sync services, system def and utils with repo", severity = 2)

log({"success":success})