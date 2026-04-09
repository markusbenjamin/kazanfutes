"""
Reads and logs radiator temperatures.
"""

from utils.project import *

SHELLY_IPS = {
    "golya_radiatorok_shelly": "192.168.101.26",
    "szgk_radiator_shelly": "192.168.101.28",
    "pk_radiatorok_shelly": "192.168.101.29",
    "oktopusz_1_radiator_shelly": "192.168.101.21",
    "oktopusz_2_radiator_shelly": "192.168.101.83",
    "gep_radiator_shelly": "192.168.101.42",
    "merce_radiatorok_1_shelly": "192.168.101.37",
    "merce_radiatorok_2_shelly": "192.168.101.94",
    "ovi_radiatorok_shelly": "192.168.101.47",
    "studio_radiator_shelly": "192.168.101.74",
}

success = False
try:
    radiator_temps_detailed = get_radiator_temps(SHELLY_IPS, detailed=True)

    radiator_temps = {}
    for device_name, device_data in radiator_temps_detailed["devices"].items():
        radiator_temps[device_name] = {}
        for peripheral_name, peripheral_data in device_data.get("peripherals", {}).items():
            radiator_temps[device_name][peripheral_name] = peripheral_data.get("temp")

    system_node = JSONNodeAtURL(node_relative_path='system')
    system_node.write({"radiator_temps": radiator_temps}, "state")

    log_data(radiator_temps, "radiator_temps/radiator_temps.json")

    success = True

except ModuleException as e:
    ServiceException(
        "Module error while trying to read and log radiator temperatures",
        original_exception=e,
        severity=2
    )

except Exception:
    ServiceException(
        "Unexpected error while trying to read and log radiator temperatures",
        severity=2
    )

log({"success": success})