"""
Syncs the contents of the data folder to the online repo.
"""

from utils.project import *

try:
    sync_dir_with_repo('data/', 'Automatic data push.')
    success = True
except Exception as e:
    success = False
    raise GitOperationError(f"An unexpected error occured while trying to sync data with repo:{e}", original_exception=e, include_traceback=settings.get("detailed_error_reporting")) from e
finally:
    # Log execution
    init_logger(log_file=f'{get_project_root()}/data/logs/services/data_uploader.json')
    log_data({"success":success})