"""
Reads and logs weather station state.
"""

from utils.project import *
from utils.shelly_discovery import (
    build_shelly_resolver,
    load_shelly_config,
)

PROJECT_ROOT = get_project_root()
SHELLY_CONFIG = load_shelly_config(PROJECT_ROOT)
SHELLY_RESOLVER = build_shelly_resolver(PROJECT_ROOT, SHELLY_CONFIG)
WEATHER_STATION = SHELLY_CONFIG["weather_station"]

success = False
try:
    gateway_name = WEATHER_STATION["gateway_device"]
    gateway = SHELLY_RESOLVER.resolve_one(
        gateway_name,
        SHELLY_CONFIG["devices"][gateway_name],
    )
    weather_station_state = get_weather_station_state(
        shelly_ip=gateway["ip"],
        ws90_bt_addr=WEATHER_STATION["ws90_bt_addr"],
    )

    #system_node = JSONNodeAtURL(node_relative_path='system')
    #system_node.write({"weather_station": weather_station_state}, "state")

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
