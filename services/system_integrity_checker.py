"""

INCOMPLETE

Checks the accessibility of various physical peripheries and virtual interfaces:
    > Deconz:
        - ZigBee mesh components
        - ConBee II
    > Tuya smart plugs
    > webcam
    > GPIO
        - Albatros
        - gas metering
    > router
    > email server
    > Docs
    > Firebase
    > GitHub

Invokes error registration if something is not accessible.
"""

from utils.project import *

#region Deconz checks
success = False
try:
    read_deconz_state()
    report("Accessed Deconz API successfully.")
    success = True
except ModuleException as e:
    report("Couldn't access Deconz API.")
    ServiceException("Deconz access error",original_exception=e,severity=0)
except Exception as e:
    report(f"Couldn't access Deconz API due to {e}.")
    ServiceException("Unexpected error while checking Deconz access",severity=0)

log({'success_deconz_access':success})

#DEV
if success:
    try:
        # Look for inaccessible sensors.
        pass
    except ModuleException as e:
        success = False
        report("Couldn't access sensors due to:", add_error_details = True)
    except Exception as e:
        success = False
        report(f"Couldn't access sensors due to unexpected error: {e}.")
else:
    report("Couldn't access Deconz API, won't even try sensors.")

log({'success_deconz_sensors_access':success})

#endregion