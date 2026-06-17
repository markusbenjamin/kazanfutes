"""
Logs Aqara and Nous device states in a flat structure.

Output shape:
{
    "timestamp": "...",
    "states": {
        "nous": {
            "Nous1": {"name": "Nous1", "temp": ..., "hum": ..., "co2": ...}
        },
        "aqara": {
            "Aqara1": {"name": "Aqara1", "presence": ..., "temp": ..., "hum": ..., "lux": ...}
        }
    }
}
"""

from utils.project import *
import re


# region settings

REQUEST_TIMEOUT = 5.0
LOG_RELATIVE_PATH = "aqara_and_nous/aqara_and_nous.json"

DEVICE_RE = re.compile(r"\b(aqara|nous)\s*0*(\d+)\b", re.IGNORECASE)

# endregion


# region deCONZ readout

def read_deconz_sensors_raw():
    deconz = get_deconz_access_params()
    base_url = f"{deconz['api_url'].strip().rstrip('/')}/{deconz['api_key'].strip()}"

    response = requests.get(f"{base_url}/sensors", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()

    return response.json()

# endregion


# region device naming

def get_device_name(sensor):
    text = " ".join(
        str(part)
        for part in [
            sensor.get("name"),
            sensor.get("manufacturername"),
            sensor.get("modelid"),
            sensor.get("type"),
        ]
        if part is not None
    )

    match = DEVICE_RE.search(text)

    if not match:
        return None, None

    group = match.group(1).lower()
    number = match.group(2)

    if group == "aqara":
        return "aqara", f"Aqara{number}"

    if group == "nous":
        return "nous", f"Nous{number}"

    return None, None

# endregion


# region value conversion

def as_float(value):
    if value is None:
        return None

    try:
        return float(value)
    except Exception:
        return None


def as_int(value):
    if value is None:
        return None

    try:
        return int(round(float(value)))
    except Exception:
        return None


def convert_temp(value):
    value = as_float(value)

    if value is None:
        return None

    if abs(value) > 100:
        value = value / 100

    return round(value, 2)


def convert_hum(value):
    value = as_float(value)

    if value is None:
        return None

    if value > 100:
        value = value / 100

    return round(value, 2)


def convert_lux(value):
    value = as_float(value)

    if value is None:
        return None

    return int(round(value))


def convert_bool(value):
    if value is None:
        return None

    return bool(value)

# endregion


# region state extraction

def empty_nous_state(name):
    return {
        "name": name,
        "temp": None,
        "hum": None,
        "co2": None,
    }


def empty_aqara_state(name):
    return {
        "name": name,
        "presence": None,
        "temp": None,
        "hum": None,
        "lux": None,
    }


def update_device_state(device, state):
    if "temperature" in state:
        device["temp"] = convert_temp(state.get("temperature"))

    if "humidity" in state:
        device["hum"] = convert_hum(state.get("humidity"))

    if "presence" in state:
        device["presence"] = convert_bool(state.get("presence"))

    if "lux" in state:
        device["lux"] = convert_lux(state.get("lux"))

    if "co2" in state:
        device["co2"] = as_int(state.get("co2"))

    if "co2ppm" in state:
        device["co2"] = as_int(state.get("co2ppm"))

    if "carbon_dioxide" in state:
        device["co2"] = as_int(state.get("carbon_dioxide"))

    if "carbon_dioxide_ppm" in state:
        device["co2"] = as_int(state.get("carbon_dioxide_ppm"))

    if "airqualityppb" in state:
        device["co2"] = as_int(state.get("airqualityppb"))


def collect_states(raw_sensors):
    states = {
        "nous": {},
        "aqara": {},
    }

    for _, sensor in raw_sensors.items():
        group, name = get_device_name(sensor)

        if group is None:
            continue

        if group == "nous":
            states["nous"].setdefault(name, empty_nous_state(name))

        if group == "aqara":
            states["aqara"].setdefault(name, empty_aqara_state(name))

        update_device_state(states[group][name], sensor.get("state", {}))

    states["nous"] = dict(sorted(states["nous"].items()))
    states["aqara"] = dict(sorted(states["aqara"].items()))

    return states

# endregion


# region main

def main():
    success = False
    states = None

    try:
        raw_sensors = read_deconz_sensors_raw()
        states = collect_states(raw_sensors)

        log_entry = {
            "timestamp": timestamp(),
            "states": states,
        }

        log_data(log_entry, LOG_RELATIVE_PATH)

        success = True

    except ModuleException as e:
        ServiceException(
            "Module error while trying to log Aqara and Nous states",
            original_exception=e,
            severity=2
        )

    except Exception as e:
        ServiceException(
            f"Unexpected error while trying to log Aqara and Nous states: {e}",
            severity=2
        )

    finally:
        log({
            "success": success,
            "nous_count": len(states["nous"]) if states else None,
            "aqara_count": len(states["aqara"]) if states else None,
            "log_relative_path": LOG_RELATIVE_PATH,
        })


if __name__ == "__main__":
    main()

# endregion
