"""
Logs temperature and humidity values from the rooms as specified in rooms.json.
"""

from utils.project import *

settings.set("detailed_error_reporting",False)

try:
    # Log measurements
    log_data(get_room_temps_and_humidity(),'temperature_and_humidity/temperature_and_humidity.json')
    report("Temperature and humidity values acquired and logged.",verbose=True)
    success = True
except Exception as e:
    success = False
    report("Temperature and humidity values couldn't be acquired.",verbose=True)
    raise DeconzError(f"An unexpected error occured while trying to read sensors:{e}", original_exception=e, severity = 3) from e
finally:
    # Log execution
    log({"success":success})