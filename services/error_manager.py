"""
Manages project-wide error reporting.

Tasks:
    - attempt re-registration of unregistered errors in buffer
    - reports unreported errors from registry according to severity
        low - 1: write to error log
        moderate - 2: write to error log, append to daily report
        high - 3: write to error log, append to daily report, notify admin
    - sends out daily reports
    - archives checked errors.
"""

import filelock
from utils.project import *

ERROR_REGISTRY_PATH = f"{get_project_root()}/data/errors/error_registry.json"
ERROR_BUFFER_PATH = f"{get_project_root()}/data/errors/error_buffer.json"
ERROR_ARCHIVE_PATH = f"{get_project_root()}/data/errors/error_buffer.json"

report("Trying to re-register buffered errors.", verbose=True)
if os.path.exists(ERROR_BUFFER_PATH):
    try:
        with filelock.FileLock(ERROR_BUFFER_PATH + ".lock", timeout = 1):
            with open(ERROR_BUFFER_PATH, 'r') as f:
                error_buffer = json.load(f)
                report("Error buffer loaded.", verbose = True)

            report("Cycling through buffered errors to re-register.", verbose = True)
            remaining_error_buffer = []
            for error in error_buffer:
                success = error_registrar(
                    exception_type=error["exception_type"],
                    severity=error["severity"],
                    origin=error["origin"],
                    origin_timestamp=error["origin_timestamp"]
                    )
                if success:
                    report("Buffered error registered, removed from buffer.", verbose = True)
                else:
                    remaining_error_buffer.append(error)
                    report("Buffered error couldn't be re-registered, kept in buffer.",verbose=True)
            
            with open(ERROR_BUFFER_PATH, 'w') as f:
                    json.dump(remaining_error_buffer, f, indent=4)
                    report("Pushed remaining errors back to buffer.")

    except filelock.Timeout:
        report("Error buffer locked, skipping.", verbose=True)
else:
    report("No buffered errors.", verbose=True)
