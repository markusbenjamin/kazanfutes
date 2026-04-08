"""
Reads and logs weather station state.
"""

from utils.project import *

success = False
try:
    weather_station_state = get_weather_station_state()

    system_node = JSONNodeAtURL(node_relative_path='system')
    system_node.write({"weather_station": weather_station_state}, "state")

    log_data(weather_station_state, "weather_station/weather_station.json")

    success = True

except ModuleException as e:
    ServiceException(
        "Module error while trying to read and log weather station state",
        original_exception=e,
        severity=2
    )

except Exception:
    ServiceException(
        "Unexpected error while trying to read and log weather station state",
        severity=2
    )

log({"success": success})