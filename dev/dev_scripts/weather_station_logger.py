"""
Reads and logs weather station state.
"""

from utils.project import *

WEATHER_STATION = {
    "shelly_ip": "192.168.101.26",
    "ws90_bt_addr": "fc:4d:6a:24:64:c7",
}

success = False
try:
    weather_station_state = get_weather_station_state(**WEATHER_STATION)

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