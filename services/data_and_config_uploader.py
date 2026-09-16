"""Sync data, config, and system state with the online repository."""

from utils.project import *


SYNC_PATHS = ['data/', 'config/', 'system/state.json']
COMMIT_MESSAGE = 'Automatic data and config push.'


success = False
try:
    check_index_lock()
    success = sync_paths_with_repo(SYNC_PATHS, COMMIT_MESSAGE, 30)
    if not success:
        report("Data or config paths remained locked for 30 seconds; Git sync skipped.")
except ModuleException as error:
    report(f"Data and config Git sync failed: {error}")
    ServiceException(
        "Module error while trying to sync data and config with repo",
        original_exception=error,
        severity=2,
    )
except Exception as error:
    report(f"Unexpected data and config Git sync failure: {error!r}")
    ServiceException(
        "Unexpected error while trying to sync data and config with repo",
        severity=2,
    )

log({"success": success, "push_confirmed": success})

if not success:
    raise SystemExit(1)
