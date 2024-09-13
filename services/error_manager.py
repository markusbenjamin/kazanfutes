"""
Manages project-wide error reporting.

Tasks:
    - attempts re-registration of unregistered errors in buffer
    - reports unreported errors from registry according to severity
        low - 1: write to error log
        moderate - 2: write to error log, append to daily report
        high - 3: write to error log, append to daily report, notify admin
    - sends out daily reports
    - archives checked errors.
"""

from utils.project import *

settings.set("verbosity",True) #DEV

ERROR_REGISTRY_PATH = f"{get_project_root()}/data/errors/error_registry.json"
ERROR_BUFFER_PATH = f"{get_project_root()}/data/errors/error_buffer.json"
ERROR_ARCHIVE_PATH = f"{get_project_root()}/data/errors/error_archive.json"

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
                    log({'success_buffered_errors':success})
                
                with open(ERROR_BUFFER_PATH, 'w') as f:
                        json.dump(remaining_error_buffer, f, indent=4)
                        report("Pushed remaining errors back to buffer.", verbose=True)
            else:
                report("No buffered errors.", verbose=True)
                log({'success_buffered_errors':True})

    except filelock.Timeout:
        report("Error buffer locked, skipping.", verbose=True)
        log({'success_buffered_errors':False})
else:
    report("Buffered errors file not even initialized.", verbose=True)
    log({'success_buffered_errors':True})

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
                    success = False
                    error_report_contents = {
                                            'exception_type': error['exception_type'],
                                            'severity': error['severity'],
                                            'origin': error['origin'],
                                            'origin_timestamp': error['origin_timestamp'],
                                            'registration_timestamp': error['registration_timestamp']
                                            }
                    try:
                        log_data(error,'errors/error_log.json')
                        if error['severity'] == 1: # For low severity errors logging itself is considered as checking.
                            error['checked'] = True
                            error['checked_timestamp'] = timestamp()
                        success = True
                    except:
                        log({'message':'Could not log attached error.','error':error_report_contents})
                    if 1 < error['severity']:
                        success = False
                        try:
                            log_data(error,'errors/daily_report.json')
                            success = True
                        except:
                            log({'message':'Could not append attached error to daily report.','error':error_report_contents})
                        if 2 < error['severity']:
                            success = False
                            try:
                                send_email(to = settings.get('admin_email'),subject='Severe error detected.',body = error_report_contents)
                                success = True
                            except:
                                log({'message':'Could not notify admin about attached error.','error':error_report_contents})

                    if success: # Meaning highest level of reporting required is successful.
                        error['reported'] = True
                        error['reported_timestamp'] = timestamp()
                        report("Error successfully reported.", verbose = True)
                    else:
                        report("Couldn't report error.",verbose=True)
                
                with open(ERROR_REGISTRY_PATH, 'w') as f:
                        json.dump(errors, f, indent=4)
                        report("Error registry updated.")
                
                log({'success_error_reporting':True})
            else:
                report("No registered errors.", verbose=True)
                log({'success_error_reporting':True})

    except filelock.Timeout:
        report("Error registry locked, skipping.", verbose=True)
        log({'success_error_reporting':False})
else:
    report("Error registry not even initialized.", verbose=True)
    log({'success_error_reporting':True})

#endregion

#region Send daily error report
#endregion

#region Archive checked errors
#endregion