"""
Syncs the contents of the data folder to the online repo.
"""

from utils.project import *

try:
    sync_dir_with_repo('data/', 'Automatic data push.')
    success = True
except Exception as e:
    success = False
    raise GitOperationError(f"An unexpected error occured while trying to sync data with repo:{e}", original_exception=e, severity = 2) from e
finally:
    # Log execution
    log({"success":success})