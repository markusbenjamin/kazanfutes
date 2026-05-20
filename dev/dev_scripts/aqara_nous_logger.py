"""
Logs selected Nous and Aqara sensor states.

Writes full structured state to:
data/logs/air_sensors/air_sensors_state.json
"""

from utils.project import *


NOUS_MANUFACTURER = "_TZE284_xpvamyfz"
NOUS_MODELID = "TS0601"

AQARA_MANUFACTURER = "Aqara"
AQARA_MODELID = "lumi.sensor_occupy.agl8"


def deconz_base_url():
    deconz = get_deconz_access_params()
    return f"{deconz['api_url'].strip().rstrip('/')}/{deconz['api_key'].strip()}"


def read_deconz_sensors_raw():
    try:
        response = requests.get(f"{deconz_base_url()}/sensors", timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        raise ModuleException(f"couldn't read deCONZ sensors through REST API: {e}", severity=2)


def physical_device_key(sensor):
    uniqueid = sensor.get("uniqueid")

    if uniqueid:
        return str(uniqueid).split("-")[0].strip().lower()

    return None


def clean_scaled_temp(value):
    if value is None:
        return None

    try:
        value = float(value)
        if abs(value) > 1000:
            return value / 100
        return value
    except Exception:
        return value


def clean_scaled_hum(value):
    if value is None:
        return None

    try:
        value = float(value)
        if abs(value) > 1000:
            return value / 100
        return value
    except Exception:
        return value


def pick_preferred_name(names, prefix=None):
    clean_names = sorted(
        name for name in names
        if name is not None and str(name).strip() != ""
    )

    if prefix:
        prefix_matches = [
            name for name in clean_names
            if str(name).lower().startswith(prefix.lower())
        ]

        if prefix_matches:
            return prefix_matches[0]

    if clean_names:
        return clean_names[0]

    return "unknown"


def empty_nous_record():
    return {
        "name": None,
        "temp": None,
        "hum": None,
        "co2": None,
        "_names": set(),
    }


def empty_aqara_record():
    return {
        "name": None,
        "presence": None,
        "temp": None,
        "hum": None,
        "lux": None,
        "_names": set(),
    }


def collect_air_sensor_states():
    sensors = read_deconz_sensors_raw()

    nous = {}
    aqara = {}

    for sensor_id, sensor in sensors.items():
        if not isinstance(sensor, dict):
            continue

        manufacturer = sensor.get("manufacturername")
        modelid = sensor.get("modelid")
        name = sensor.get("name")
        state = sensor.get("state", {})
        key = physical_device_key(sensor)

        if key is None:
            key = f"sensor:{sensor_id}"

        is_nous = (
            manufacturer == NOUS_MANUFACTURER
            and modelid == NOUS_MODELID
        )

        is_aqara = (
            manufacturer == AQARA_MANUFACTURER
            and modelid == AQARA_MODELID
        )

        if not is_nous and not is_aqara:
            continue

        if is_nous:
            if key not in nous:
                nous[key] = empty_nous_record()

            nous[key]["_names"].add(name)

            if "temperature" in state:
                nous[key]["temp"] = clean_scaled_temp(state.get("temperature"))

            if "humidity" in state:
                nous[key]["hum"] = clean_scaled_hum(state.get("humidity"))

            if "measured_value" in state:
                nous[key]["co2"] = state.get("measured_value")

            if "co2" in state:
                nous[key]["co2"] = state.get("co2")

        if is_aqara:
            if key not in aqara:
                aqara[key] = empty_aqara_record()

            aqara[key]["_names"].add(name)

            if "presence" in state:
                aqara[key]["presence"] = bool(state.get("presence"))

            if "temperature" in state:
                aqara[key]["temp"] = clean_scaled_temp(state.get("temperature"))

            if "humidity" in state:
                aqara[key]["hum"] = clean_scaled_hum(state.get("humidity"))

            if "lux" in state:
                aqara[key]["lux"] = state.get("lux")

    nous_out = {}
    for key, rec in nous.items():
        name = pick_preferred_name(rec["_names"], prefix="Nous")
        rec["name"] = name
        del rec["_names"]
        nous_out[name] = rec

    aqara_out = {}
    for key, rec in aqara.items():
        name = pick_preferred_name(rec["_names"], prefix="Aqara")
        rec["name"] = name
        del rec["_names"]
        aqara_out[name] = rec

    return {
        "nous": dict(sorted(nous_out.items())),
        "aqara": dict(sorted(aqara_out.items())),
    }


success = False

try:
    ts = timestamp()

    states = collect_air_sensor_states()

    air_sensors_state = {
        "last_updated": ts,
        "nous": states["nous"],
        "aqara": states["aqara"],
    }

    # system_node = JSONNodeAtURL(node_relative_path="system")
    # system_node.write(
    #     {"air_sensors": air_sensors_state},
    #     "state",
    # )

    log_data(
        {"timestamp": ts, "states": states},
        "aqara_and_nous/aqara_and_nous.json",
    )

    report("Aqara and Nous logged.", verbose=True)
    success = True
    #print({"timestamp": ts, "states": states})

except ModuleException as e:
    ServiceException(
        "Module error while trying to acquire Aqara and Nous states",
        original_exception=e,
        severity=2,
    )

except Exception:
    ServiceException(
        "Unexpected error while trying to acquire Aqara and Nous states",
        severity=2,
    )

log({"success": success})