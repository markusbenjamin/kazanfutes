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

#region Init
from utils.project import *
import glob

ERROR_REGISTRY_PATH = f"{get_project_root()}/data/error_management/error_registry.json"
ERROR_BUFFER_PATH = f"{get_project_root()}/data/error_management/error_buffer.json"
ERROR_ARCHIVE_PATH = f"{get_project_root()}/data/error_management/error_archive.json"
#endregion

#region Buffer management
def manage_buffered_errors():
    report("\nERROR BUFFER MANAGEMENT",verbose=True)
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
                        success = error_registrar(error)
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

#region Report unreported errors based on severity
def report_unreported_errors():
    report("\nERROR REPORTING",verbose=True)
    if os.path.exists(ERROR_REGISTRY_PATH):
        try:
            with filelock.FileLock(ERROR_REGISTRY_PATH + ".lock", timeout = 1):
                with open(ERROR_REGISTRY_PATH, 'r') as error_registry:
                    errors = json.load(error_registry)
                    report("Error registry loaded.", verbose = True)

                if errors != []:
                    report("Cycling through registered errors for reporting.", verbose = True)
                    modification = False
                    for error in errors:
                        if error['reported'] == False:
                            modification = True
                            success = False
                            error_report_contents = {
                                                    'message': error['message'],
                                                    'severity': error['severity'],
                                                    'origin': error['origin'],
                                                    'origin_timestamp': error['origin_timestamp'],
                                                    'registration_timestamp': error['registration_timestamp']
                                                    }
                            try:
                                log_data(error_report_contents,'errors/error_log.json')
                                if error['severity'] == 1: # For low severity errors logging itself is considered as checking.
                                    error['checked'] = True
                                    error['checked_timestamp'] = timestamp()
                                success = True
                            except:
                                log({'message':'Could not log attached error.','error':error_report_contents})
                            if 1 < error['severity']:
                                success = False
                                try:
                                    log_data(error_report_contents,'errors/daily_report.json')
                                    success = True
                                except:
                                    log({'message':'Could not append attached error to daily report.','error':error_report_contents})
                                if 2 < error['severity']:
                                    success = False
                                    try:
                                        send_email(to = settings['admin_email'],subject='Severe error detected.',body = error_report_contents)
                                        success = True
                                    except:
                                        log({'message':'Could not notify admin about attached error.','error':error_report_contents})

                            if success: # Meaning highest level of reporting required is successful.
                                error['reported'] = True
                                error['reported_timestamp'] = timestamp()
                                report("Error successfully reported.", verbose = True)
                            else:
                                report("Couldn't report error.",verbose=True)
                        else:
                            report("Error already reported, skipping.", verbose=True)
                    
                    if modification:
                        with open(ERROR_REGISTRY_PATH, 'w') as f:
                            json.dump(errors, f, indent=4)
                            report("Error registry updated.",verbose=True)
                    else:
                        report("No unreported errors found.",verbose=True)
                    
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
def send_daily_error_report():
    report("\nSEND DAILY REPORT",verbose=True)
    if rotate_log_file('errors/daily_report.json'):
        report("Daily report log file rotated.",verbose=True)
    else:
        report("No unrotated daily reports.",verbose=True)
    unsent_daily_reports = [file for file in glob.glob(os.path.join(get_project_root(),'data','logs','errors','daily_report.json.*')) if not file.endswith('.sent')]
    if 0<len(unsent_daily_reports):
        for daily_report_filepath in unsent_daily_reports:
            daystamp = os.path.basename(daily_report_filepath).split('.')[-1]
            try:
                with open(daily_report_filepath, 'r') as file:
                    lines = file.readlines()
                if 0<len(lines):
                    error_list = [json.loads(line) for line in lines]
                    error_report_contents = '\n'.join([json.dumps(
                        {
                            'message': error['message'],
                            'severity': error['severity'],
                            'origin':error['origin'],
                            'origin_timestamp': error['origin_timestamp'],
                            'registration_timestamp': error['registration_timestamp']
                        }
                        , indent=4) for error in error_list])
                    if send_email(to = settings['admin_email'],subject=f'Daily error report for {daystamp}',body = error_report_contents):
                        os.rename(daily_report_filepath, daily_report_filepath + '.sent')
                        report(f"Sent out daily report for {daystamp}.",verbose=True)
                        log({'success_daily_report':True})
                    else:                        
                        report(f"Could not send out daily report for {daystamp} due to an error with sending the email.")
                        log({'success_daily_report':False})
                else:
                    os.remove(daily_report_filepath)
                    report(f"No reported medium severity errors for {daystamp}.",verbose=True)
                    log({'success_daily_report':True})
            except Exception:
                ServiceException(f"Could not send out daily report for {daystamp}",severity=1) # Do not generate a new reportable error (severity == 2) if there is an issue with error reporting, just log it (severity == 1)
                log({'success_daily_report':False})
    else:
        report("No unsent daily reports.",verbose=True)
        log({'success_daily_report':True})

#endregion

#region Archive checked errors
def archive_checked_errors():
    report("\nARCHIVING CHECKED ERRORS",verbose=True)
    if os.path.exists(ERROR_REGISTRY_PATH):
        try:
            with filelock.FileLock(ERROR_REGISTRY_PATH + ".lock", timeout = 1):
                with open(ERROR_REGISTRY_PATH, 'r') as error_registry:
                    errors = json.load(error_registry)
                    report("Error registry loaded.", verbose = True)

                if errors != []:
                    report("Cycling through registered errors to archive checked ones.", verbose = True)
                    modification = False
                    unchecked_errors = []
                    checked_errors = []
                    for error in errors:
                        if error['checked']:
                            modification = True
                            checked_errors.append(error)
                            report("Archiving error.", verbose = True)
                        else:
                            unchecked_errors.append(error)
                    
                    if modification:
                        with open(ERROR_REGISTRY_PATH, 'w') as error_registry_path:
                            json.dump(unchecked_errors, error_registry_path, indent=4)
                            report("Error registry updated.",verbose=True)
                        if not os.path.exists(ERROR_ARCHIVE_PATH):
                            with open(ERROR_ARCHIVE_PATH, 'w') as error_archive_path:
                                json.dump([], error_archive_path)
                                report("Created new error archive file.", verbose = True)
                        with open(ERROR_ARCHIVE_PATH, 'r') as error_archive_path:
                            archived_errors = json.load(error_archive_path)
                        with open(ERROR_ARCHIVE_PATH, 'w') as error_archive_path:
                            json.dump(archived_errors + checked_errors, error_archive_path, indent=4)
                            report("Checked errors pushed to archive.",verbose=True)
                    else:
                        report("No unarchived errors found.",verbose=True)
                    
                    log({'success_error_archiving':True})
                else:
                    report("No registered errors.", verbose=True)
                    log({'success_error_archiving':True})

        except filelock.Timeout:
            report("Error registry locked, skipping.", verbose=True)
            log({'success_error_archiving':False})
    else:
        report("Error registry not even initialized.", verbose=True)
        log({'success_error_archiving':True})

#endregion

if __name__ == "__main__":
    try:
        manage_buffered_errors()
        report_unreported_errors()
        send_daily_error_report()
        archive_checked_errors()
    except Exception as e: # Send notification email right away if error management can't run.
        email_body = '\n'.join([json.dumps(extract_exception_details())])
        report(f'Error management error: {email_body}')
        send_email(settings['admin_email'],'Error management error.',email_body)