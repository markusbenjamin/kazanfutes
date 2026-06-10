"""
List current ZigBee device states.
"""

from utils.project import *

if True:
    settings["log"] = False
    settings["verbosity"] = True


#region Load persistence
DEVICES_STATE_RELATIVE_PATH = "system/devices_state.json"

try:
    previous_devices_state = load_json_to_dict(DEVICES_STATE_RELATIVE_PATH)
except Exception:
    previous_devices_state = {}
#endregion


#region Get devices state
def get_devices_state(): #DEV: szűrjön típusra
    deconz_state = read_deconz_state()
    devices_state = {}

    for device_kind, source in {
        "sensor": deconz_state.sensors,
        "light": deconz_state.lights,
    }.items():
        for device_id, device in source.items():
            raw = device.raw
            state = raw.get("state", {})
            config = raw.get("config", {})

            devices_state[f"{device_kind}_{device_id}"] = {
                "name": raw.get("name"),
                "type": raw.get("type"),
                "reachability": config.get("reachable", state.get("reachable")),
                "last_seen": deconz_timestamp_to_project_timestamp(raw.get("lastseen")),
                "last_updated": deconz_timestamp_to_project_timestamp(state.get("lastupdated")),
                "battery_level": config.get("battery"),
                "battery_low_state": state.get("lowbattery"),
            }

    return devices_state
#endregion#endregion

#region Identify problem devices
PROBLEM_CONDITIONS = {
    "flag_unreachable": True,
    "last_seen_max_age_min": 60 * 24,
    "last_updated_max_age_min": 60 * 24,
    "battery_low_threshold": 20,
    "flag_missing_last_seen": False,
    "flag_missing_last_updated": False,
    "flag_missing_battery": False,
}


def get_problem_devices(devices_state, problem_conditions=PROBLEM_CONDITIONS):
    problem_devices = {}

    now = datetime.now()

    for device_id, vals in devices_state.items():
        problems = []

        if (
            problem_conditions["flag_unreachable"]
            and vals["reachability"] is False
        ):
            problems.append("unreachable")

        if vals["last_seen"]:
            last_seen_age_min = (now - datetime.strptime(vals["last_seen"], settings["timestamp_format"])).total_seconds() / 60
            if last_seen_age_min > problem_conditions["last_seen_max_age_min"]:
                problems.append(f"last_seen_old_{round(last_seen_age_min)}min")
        elif problem_conditions["flag_missing_last_seen"]:
            problems.append("missing_last_seen")

        if vals["last_updated"]:
            last_updated_age_min = (now - datetime.strptime(vals["last_updated"], settings["timestamp_format"])).total_seconds() / 60
            if last_updated_age_min > problem_conditions["last_updated_max_age_min"]:
                problems.append(f"last_updated_old_{round(last_updated_age_min)}min")
        elif problem_conditions["flag_missing_last_updated"]:
            problems.append("missing_last_updated")

        if vals["battery_level"] is not None:
            if vals["battery_level"] <= problem_conditions["battery_low_threshold"]:
                problems.append(f"battery_low_{vals['battery_level']}")
        elif problem_conditions["flag_missing_battery"]:
            problems.append("missing_battery")

        if problems:
            problem_devices[device_id] = vals | {"problems": problems}

    return problem_devices
#endregion

#region Export devices state
def export_devices_state(devices_state):
    export_dict_as_json(devices_state, DEVICES_STATE_RELATIVE_PATH)
#endregion


if __name__ == "__main__":
    devices_state = get_devices_state()
    problem_devices = get_problem_devices(devices_state)

    export_devices_state(devices_state)

    for device_id, vals in devices_state.items():
        print(f"{device_id}: {vals}")

    print("\nPROBLEM DEVICES")
    for device_id, vals in problem_devices.items():
        print(f"{device_id}: {vals}")