"""
Logs temperature and humidity values from the rooms as specified in rooms.json.
"""

from utils.project import *

success = False
try:
    # Log measurements
    log_data(get_room_temps_and_humidity(just_controlled=False),'temperature_and_humidity/temperature_and_humidity.json')
    report("Temperature and humidity values acquired and logged.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error while trying to acquire temperature and humidity data", original_exception=e, severity = 3)
except Exception:
    ServiceException("Module error while trying to acquire temperature and humidity data", severity = 3)

# Log execution
log({"success":success})