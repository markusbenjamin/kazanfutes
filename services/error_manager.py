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

settings.set_verbosity(True) #DEV

ERROR_REGISTRY_PATH = f"{get_project_root()}/data/errors/error_registry.json"
ERROR_BUFFER_PATH = f"{get_project_root()}/data/errors/error_buffer.json"
ERROR_ARCHIVE_PATH = f"{get_project_root()}/data/errors/error_buffer.json"

#region Buffer management
report("Trying to re-register buffered errors.", verbose=True)
if os.path.exists(ERROR_BUFFER_PATH):
    try:
        with filelock.FileLock(ERROR_BUFFER_PATH + ".lock", timeout = 1):
            with open(ERROR_BUFFER_PATH, 'r') as f:
                error_buffer = json.load(f)
                report("Error buffer loaded.", verbose = True)

            if error_buffer != []:
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
                        report("Pushed remaining errors back to buffer.", verbose=True)
            else:
                report("No buffered errors.", verbose=True)

    except filelock.Timeout:
        report("Error buffer locked, skipping.", verbose=True)
else:
    report("Buffered errors file not even initialized.", verbose=True)
#endregion

#region Report unreported errors

if os.path.exists(ERROR_REGISTRY_PATH):
    try:
        with filelock.FileLock(ERROR_REGISTRY_PATH + ".lock", timeout = 1):
            with open(ERROR_REGISTRY_PATH, 'r') as f:
                errors = json.load(f)
                report("Error registry loaded.", verbose = True)

            if errors != []:
                report("Cycling through registered errors for reporting.", verbose = True)
                for error in errors:
                    if error["severity"] == 1:
                        # append to error log
                        # if successful, set checked to true
                        pass
                    elif error["severity"] == 2:
                        # append to error log
                        # append to daily report
                        pass
                    elif error["severity"] == 3:
                        # append to error log
                        # append to daily report
                        # notify admin
                        pass

                    if success: # meaning highest level of reporting required is successful
                        # set reported fields for error entry
                        report("Error successfully reported.", verbose = True)
                    else:
                        report("Couldn't report error.",verbose=True)
                
                with open(ERROR_REGISTRY_PATH, 'w') as f:
                        json.dump(errors, f, indent=4)
                        report("Error registry updated.")
            else:
                report("No registered errors.", verbose=True)

    except filelock.Timeout:
        report("Error registry locked, skipping.", verbose=True)
else:
    report("Error registry not even initialized.", verbose=True)

#endregion

#region Send daily error report
#endregion

#region Archive checked errors
#endregion