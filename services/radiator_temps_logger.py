"""
Reads and logs radiator temperatures.
"""

from utils.project import *
from utils.shelly_discovery import (
    ShellyDiscoveryError,
    build_shelly_resolver,
    load_shelly_config,
)

PROJECT_ROOT = get_project_root()
SHELLY_CONFIG = load_shelly_config(PROJECT_ROOT)
SHELLY_RESOLVER = build_shelly_resolver(PROJECT_ROOT, SHELLY_CONFIG)
RADIATOR_DEVICE_SPECS = {
    device_name: SHELLY_CONFIG["devices"][device_name]
    for device_name in SHELLY_CONFIG["radiator_devices"]
}

success = False
try:
    resolved_devices, resolution_errors = SHELLY_RESOLVER.resolve_many(
        RADIATOR_DEVICE_SPECS
    )
    shelly_ips = {
        device_name: device["ip"]
        for device_name, device in resolved_devices.items()
    }
    radiator_temps_detailed = get_radiator_temps(shelly_ips, detailed=True)

    for device_name, error in resolution_errors.items():
        radiator_temps_detailed["devices"][device_name] = {
            "ip": None,
            "peripherals": {},
            "error": error,
        }
        report(error)

    radiator_temps = {}
    for device_name, device_data in radiator_temps_detailed["devices"].items():
        radiator_temps[device_name] = {}
        for peripheral_name, peripheral_data in device_data.get("peripherals", {}).items():
            radiator_temps[device_name][peripheral_name] = peripheral_data.get("temp")

    #system_node = JSONNodeAtURL(node_relative_path='system')
    #system_node.write({"radiator_temps": radiator_temps}, "state")

    log_data(radiator_temps, "radiator_temps/radiator_temps.json")

    required_errors = {
        name: error for name, error in resolution_errors.items()
        if RADIATOR_DEVICE_SPECS[name].get("required", True)
    }
    if required_errors:
        raise ShellyDiscoveryError("; ".join(required_errors.values()))

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
