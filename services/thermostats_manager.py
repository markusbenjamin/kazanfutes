"""
Logs state of thermostats.
"""

from utils.project import *

if False:
    settings["dev"] = False
    settings["log"] = False
    settings["verbosity"] = True

# Log states
success = False
states = {}
try:
    for tid, sensor in read_thermostats():
        name = sensor.raw["name"]
        states[tid] = get_thermostat_state_by_id(
            tid,
            ["name","valve", "heatsetpoint", "temperature", "externalsensortemp", "battery","lastseen","lastupdated"]
        )
    log_data({"timestamp":timestamp(),"states":states},'thermostats/thermostats_state.json')
    report("Thermostat states acquired and logged.",verbose=True)
    success = True
except ModuleException as e:
    ServiceException("Module error during thermostats logging", original_exception=e, severity = 2)
except Exception:
    ServiceException("Module error while thermostats logging", severity = 2)

# Manage: just check battery states for now
try:
    low_level = 20
    low_batt = [
        name
        for name, data in states.items()
        if (batt := data.get("battery")) is not None and batt < low_level
    ]

    if low_batt:
        ServiceException(
            f"thermostat battery below {low_level}%: {', '.join(low_batt)}",
            severity=3
        )
except ModuleException as e:
    ServiceException("Module error during thermostats management",original_exception=e, severity=2)
except Exception:
    ServiceException("Module error during thermostats management", severity=2)

log({"success":success})