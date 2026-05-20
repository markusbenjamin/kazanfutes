"""
Logs and manages state of thermostats.
"""

from utils.project import *

if False:
    settings["dev"] = False
    settings["log"] = False
    settings["verbosity"] = True

success = False
states = {}

try:
    if (
        datetime.now().weekday() == 0
        and datetime.now().hour == 4
        and datetime.now().minute in [0, 1]
    ):
        calibrate_all_thermostats()

    for tid, sensor in read_thermostats():
        states[tid] = get_thermostat_state_by_id(
            tid,
            ["name", "valve", "heatsetpoint", "temperature", "externalsensortemp", "battery", "lastseen", "lastupdated"]
        )

    log_data(
        {"timestamp": timestamp(), "states": states},
        "thermostats/thermostats_state.json"
    )

    low_level = 20
    low_batt = [
        data.get("name", tid)
        for tid, data in states.items()
        if (batt := data.get("battery")) is not None and batt < low_level
    ]

    if low_batt:
        ServiceException(
            f"thermostat battery below {low_level}%: {', '.join(low_batt)}",
            severity=3
        )

    report("Thermostat states acquired and logged.", verbose=True)
    success = True

except ModuleException as e:
    ServiceException("Module error during thermostats management", original_exception=e, severity=2)

except Exception:
    ServiceException("Unexpected error during thermostats management", severity=2)

log({"success": success})