"""
Run-once deCONZ device manager.

- maintains root/system/deconz_state.json
- logs battery snapshots into that same JSON
- emails admin once per low-battery drainage event
- emails admin once per unreachable event
- re-arms low-battery alerts after clear battery recovery
- re-arms unreachable alerts after the sensor becomes reachable again
"""

from utils.project import *


#region Hardcoded settings

SEND_NOW = False
PRINT_REPORT_ONLY = Tue

BATTERY_LOW_THRESHOLD = 10
BATTERY_REWATCH_THRESHOLD = 30

BATTERY_HISTORY_LIMIT = 1000

REPORT_HOUR = 0

STATE_RELATIVE_PATH = os.path.join("system", "deconz_state.json")

#endregion


#region State IO

def _state_path():
    return os.path.join(get_project_root(), STATE_RELATIVE_PATH)


def _today():
    return datetime.now().strftime("%Y-%m-%d")


def _empty_state():
    return {
        "updated": None,
        "last_report_day": None,
        "last_report_at": None,
        "sensors": {},
        "battery_history": []
    }


def _load_state():
    path = _state_path()

    if not os.path.exists(path):
        return _empty_state()

    with open(path, "r", encoding="utf-8") as f:
        state = json.load(f)

    state.setdefault("updated", None)
    state.setdefault("last_report_day", None)
    state.setdefault("last_report_at", None)
    state.setdefault("sensors", {})
    state.setdefault("battery_history", [])

    return state


def _save_state(state):
    path = _state_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4, ensure_ascii=False)

#endregion


#region deCONZ raw readout

def _read_deconz_sensors_raw():
    deconz = get_deconz_access_params()
    base_url = f"{deconz['api_url'].strip().rstrip('/')}/{deconz['api_key'].strip()}"

    response = requests.get(f"{base_url}/sensors", timeout=5)
    response.raise_for_status()

    return response.json()


def _sensor_key(sensor_id, sensor):
    uniqueid = sensor.get("uniqueid")

    if uniqueid:
        return uniqueid.split("-")[0]

    return f"sensor_id:{sensor_id}"


def _sensor_signature(sensor):
    manufacturer = sensor.get("manufacturername")
    model = sensor.get("modelid")

    if not manufacturer and not model:
        return None

    return f"{manufacturer or ''}::{model or ''}"

#endregion


#region Time parsing

def _parse_deconz_time(ts):
    if not ts or ts == "none":
        return None

    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        return dt.astimezone(timezone.utc)

    except Exception:
        return None


def _not_seen_since_days(ts):
    dt = _parse_deconz_time(ts)

    if dt is None:
        return None

    return round(
        (datetime.now(timezone.utc) - dt).total_seconds() / 86400,
        1
    )

#endregion


#region Battery interpretation

def _raw_battery_value(value):
    if value is None:
        return None

    try:
        value = float(value)
    except Exception:
        return None

    if value < 0 or value > 200:
        return None

    return value


def _battery_scale_evidence(raw_sensors):
    """
    Evidence is taken only from currently present deCONZ sensors.

    A device has direct 0-200 evidence if any of its current battery
    fields are above 100.

    A device has model-level 0-200 evidence if another current device
    with the same manufacturer/model signature has a battery value above 100.
    """
    device_evidence = set()
    signature_evidence = set()

    for sensor_id, sensor in raw_sensors.items():
        raw = _raw_battery_value(sensor.get("config", {}).get("battery"))

        if raw is None or raw <= 100:
            continue

        key = _sensor_key(sensor_id, sensor)
        signature = _sensor_signature(sensor)

        device_evidence.add(key)

        if signature:
            signature_evidence.add(signature)

    return device_evidence, signature_evidence


def _battery_status(raw, *, has_half_percent_evidence, evidence_source):
    """
    Returns a conservative interpretation of deCONZ battery values.

    Important cases
    ---------------
    raw < 10:
        definitely below 10%, with or without 0-200 scaling

    raw 10..19:
        low only if there is current 0-200 evidence;
        otherwise ambiguous

    raw >= 20:
        not below 10%, with or without 0-200 scaling
    """
    raw = _raw_battery_value(raw)

    if raw is None:
        return {
            "battery_raw": None,
            "battery_percent": None,
            "battery_scale": "unknown",
            "battery_scale_evidence": "none",
            "battery_low_state": "unknown",
            "battery_recovered": False,
        }

    if has_half_percent_evidence:
        battery_percent = round(raw / 2, 1)
        battery_scale = "0-200"

        if battery_percent < BATTERY_LOW_THRESHOLD:
            low_state = "low"
        else:
            low_state = "not_low"

        recovered = battery_percent >= BATTERY_REWATCH_THRESHOLD

    else:
        battery_percent = None
        battery_scale = "unknown"

        if raw < BATTERY_LOW_THRESHOLD:
            low_state = "low"
        elif raw < BATTERY_LOW_THRESHOLD * 2:
            low_state = "ambiguous"
        else:
            low_state = "not_low"

        # only reset a drainage event if recovery is guaranteed
        # under both possible scales
        recovered = raw >= BATTERY_REWATCH_THRESHOLD * 2

    return {
        "battery_raw": raw,
        "battery_percent": battery_percent,
        "battery_scale": battery_scale,
        "battery_scale_evidence": evidence_source,
        "battery_low_state": low_state,
        "battery_recovered": recovered,
    }


def _merge_battery_status(existing, new):
    priority = {
        "low": 0,
        "ambiguous": 1,
        "not_low": 2,
        "unknown": 3,
    }

    if existing is None:
        return new

    existing_rank = priority.get(existing["battery_low_state"], 99)
    new_rank = priority.get(new["battery_low_state"], 99)

    if new_rank < existing_rank:
        return new

    if new_rank > existing_rank:
        return existing

    existing_raw = existing.get("battery_raw")
    new_raw = new.get("battery_raw")

    if existing_raw is None:
        return new

    if new_raw is None:
        return existing

    return new if new_raw < existing_raw else existing

#endregion


#region Sensor aggregation

def _merge_sensor_devices(raw_sensors):
    device_evidence, signature_evidence = _battery_scale_evidence(raw_sensors)
    devices = {}

    for sensor_id, sensor in raw_sensors.items():
        key = _sensor_key(sensor_id, sensor)
        signature = _sensor_signature(sensor)

        config = sensor.get("config", {})
        state = sensor.get("state", {})

        name = sensor.get("name")
        sensor_type = sensor.get("type")
        manufacturer = sensor.get("manufacturername")
        model = sensor.get("modelid")
        reachable = config.get("reachable", state.get("reachable", True))
        lastseen = sensor.get("lastseen")

        has_half_percent_evidence = (
            key in device_evidence
            or signature in signature_evidence
        )

        if key in device_evidence:
            evidence_source = "same_device_current"
        elif signature in signature_evidence:
            evidence_source = "same_model_current"
        else:
            evidence_source = "none_current"

        battery = _battery_status(
            config.get("battery"),
            has_half_percent_evidence=has_half_percent_evidence,
            evidence_source=evidence_source
        )

        if key not in devices:
            devices[key] = {
                "sensor_key": key,
                "sensor_name": name,
                "types": set(),
                "manufacturers": set(),
                "models": set(),
                "battery": None,
                "reachable": True,
                "lastseen": None,
                "_lastseen_dt": None,
                "not_seen_since": None,
            }

        device = devices[key]

        if name and not device["sensor_name"]:
            device["sensor_name"] = name

        if sensor_type:
            device["types"].add(sensor_type)

        if manufacturer:
            device["manufacturers"].add(manufacturer)

        if model:
            device["models"].add(model)

        device["battery"] = _merge_battery_status(device["battery"], battery)

        if reachable is False:
            device["reachable"] = False

        lastseen_dt = _parse_deconz_time(lastseen)

        if lastseen_dt is not None:
            if device["_lastseen_dt"] is None or lastseen_dt > device["_lastseen_dt"]:
                device["_lastseen_dt"] = lastseen_dt
                device["lastseen"] = lastseen

    out = []

    for device in devices.values():
        battery = device["battery"] or _battery_status(
            None,
            has_half_percent_evidence=False,
            evidence_source="none_current"
        )

        device["types"] = sorted(device["types"])
        device["manufacturers"] = sorted(device["manufacturers"])
        device["models"] = sorted(device["models"])
        device["not_seen_since"] = _not_seen_since_days(device["lastseen"])

        device.update(battery)

        del device["battery"]
        del device["_lastseen_dt"]

        out.append(device)

    return sorted(
        out,
        key=lambda item: (item["sensor_name"] or item["sensor_key"]).lower()
    )

#endregion


#region Persistent state update

def _update_persistent_state(state, sensor_devices):
    for sensor in state["sensors"].values():
        sensor["present"] = False

    for sensor in sensor_devices:
        key = sensor["sensor_key"]

        previous = state["sensors"].setdefault(
            key,
            {
                "present": True,
                "sensor_name": sensor["sensor_name"],
                "types": sensor["types"],
                "manufacturers": sensor["manufacturers"],
                "models": sensor["models"],
                "battery_raw": None,
                "battery_percent": None,
                "battery_scale": "unknown",
                "battery_scale_evidence": "none",
                "battery_low_state": "unknown",
                "battery_recovered": False,
                "reachable": True,
                "lastseen": None,
                "not_seen_since": None,
                "low_battery_reported": False,
                "last_low_battery_reported_at": None,
                "unreachable_reported": False,
                "last_unreachable_reported_at": None,
            }
        )

        previous["present"] = True
        previous["sensor_name"] = sensor["sensor_name"]
        previous["types"] = sensor["types"]
        previous["manufacturers"] = sensor["manufacturers"]
        previous["models"] = sensor["models"]

        previous["battery_raw"] = sensor["battery_raw"]
        previous["battery_percent"] = sensor["battery_percent"]
        previous["battery_scale"] = sensor["battery_scale"]
        previous["battery_scale_evidence"] = sensor["battery_scale_evidence"]
        previous["battery_low_state"] = sensor["battery_low_state"]
        previous["battery_recovered"] = sensor["battery_recovered"]

        previous["reachable"] = sensor["reachable"]
        previous["lastseen"] = sensor["lastseen"]
        previous["not_seen_since"] = sensor["not_seen_since"]

        if sensor["battery_recovered"]:
            previous["low_battery_reported"] = False

        if sensor["reachable"] is not False:
            previous["unreachable_reported"] = False

    state["updated"] = timestamp()


def _append_battery_history(state, sensor_devices):
    state["battery_history"].append({
        "timestamp": timestamp(),
        "sensors": [
            {
                "sensor_key": sensor["sensor_key"],
                "sensor_name": sensor["sensor_name"],
                "battery_raw": sensor["battery_raw"],
                "battery_percent": sensor["battery_percent"],
                "battery_scale": sensor["battery_scale"],
                "battery_scale_evidence": sensor["battery_scale_evidence"],
                "battery_low_state": sensor["battery_low_state"],
            }
            for sensor in sensor_devices
        ]
    })

    state["battery_history"] = state["battery_history"][-BATTERY_HISTORY_LIMIT:]

#endregion


#region Reporting

def _collect_alerts(state):
    low_battery = []
    ambiguous_battery = []
    unreachable = []

    for key, sensor in state["sensors"].items():
        if not sensor.get("present", False):
            continue

        battery_low_state = sensor.get("battery_low_state")
        reachable = sensor.get("reachable")

        if (
            battery_low_state == "low"
            and not sensor.get("low_battery_reported", False)
        ):
            low_battery.append({
                "sensor_key": key,
                "sensor_name": sensor.get("sensor_name"),
                "battery_raw": sensor.get("battery_raw"),
                "battery_percent": sensor.get("battery_percent"),
                "battery_scale": sensor.get("battery_scale"),
                "battery_scale_evidence": sensor.get("battery_scale_evidence"),
            })

        if battery_low_state == "ambiguous":
            ambiguous_battery.append({
                "sensor_key": key,
                "sensor_name": sensor.get("sensor_name"),
                "battery_raw": sensor.get("battery_raw"),
                "battery_scale_evidence": sensor.get("battery_scale_evidence"),
            })

        if (
            reachable is False
            and not sensor.get("unreachable_reported", False)
        ):
            unreachable.append({
                "sensor_key": key,
                "sensor_name": sensor.get("sensor_name"),
                "not_seen_since": sensor.get("not_seen_since"),
            })

    low_battery = sorted(
        low_battery,
        key=lambda item: (
            item["battery_percent"] is None,
            item["battery_percent"] if item["battery_percent"] is not None else item["battery_raw"],
            item["sensor_name"] or item["sensor_key"]
        )
    )

    ambiguous_battery = sorted(
        ambiguous_battery,
        key=lambda item: (
            item["battery_raw"] if item["battery_raw"] is not None else 999,
            item["sensor_name"] or item["sensor_key"]
        )
    )

    unreachable = sorted(
        unreachable,
        key=lambda item: (
            item["not_seen_since"] is None,
            -(item["not_seen_since"] or 0),
            item["sensor_name"] or item["sensor_key"]
        )
    )

    return low_battery, ambiguous_battery, unreachable


def _report_due(state):
    if SEND_NOW or PRINT_REPORT_ONLY:
        return True

    if state.get("last_report_day") == _today():
        return False

    return datetime.now().hour == REPORT_HOUR


def _fmt_raw(value):
    if value is None:
        return "unknown"

    return f"{value:g}"


def _fmt_percent(value):
    if value is None:
        return "unknown"

    return f"{value:g}%"


def _fmt_days(value):
    if value is None:
        return "unknown"

    return f"{value:.1f} days"


def _build_report(low_battery, ambiguous_battery, unreachable):
    lines = [
        "deCONZ device manager report",
        f"timestamp: {timestamp()}",
        "",
        f"low battery sensors below {BATTERY_LOW_THRESHOLD}%",
    ]

    if low_battery:
        for sensor in low_battery:
            if sensor["battery_percent"] is None:
                battery_text = f"raw {sensor['battery_raw']:g}, definitely below threshold"
            else:
                battery_text = (
                    f"{_fmt_percent(sensor['battery_percent'])} "
                    f"(raw {sensor['battery_raw']:g}, {sensor['battery_scale']})"
                )

            lines.append(
                f"- {sensor['sensor_name'] or sensor['sensor_key']}: "
                f"{battery_text}; evidence: {sensor['battery_scale_evidence']}"
            )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "ambiguous low-battery readings",
    ])

    if ambiguous_battery:
        for sensor in ambiguous_battery:
            lines.append(
                f"- {sensor['sensor_name'] or sensor['sensor_key']}: "
                f"raw {sensor['battery_raw']:g}; could be normal percent or 0-200 half-percent"
            )
    else:
        lines.append("- none")

    lines.extend([
        "",
        "unreachable sensors",
    ])

    if unreachable:
        for sensor in unreachable:
            lines.append(
                f"- {sensor['sensor_name'] or sensor['sensor_key']}: "
                f"not seen since {_fmt_days(sensor['not_seen_since'])}"
            )
    else:
        lines.append("- none")

    return "\n".join(lines)


def _mark_reported(state, low_battery, unreachable):
    sent_at = timestamp()

    for sensor in low_battery:
        state["sensors"][sensor["sensor_key"]]["low_battery_reported"] = True
        state["sensors"][sensor["sensor_key"]]["last_low_battery_reported_at"] = sent_at

    for sensor in unreachable:
        state["sensors"][sensor["sensor_key"]]["unreachable_reported"] = True
        state["sensors"][sensor["sensor_key"]]["last_unreachable_reported_at"] = sent_at

    state["last_report_day"] = _today()
    state["last_report_at"] = sent_at
    state["updated"] = sent_at

#endregion


#region Main

if __name__ == "__main__":
    try:
        persistent_state = _load_state()

        raw_sensors = _read_deconz_sensors_raw()
        sensor_devices = _merge_sensor_devices(raw_sensors)

        _update_persistent_state(persistent_state, sensor_devices)
        _append_battery_history(persistent_state, sensor_devices)

        low_battery_alerts, ambiguous_battery_readings, unreachable_alerts = _collect_alerts(
            persistent_state
        )

        _save_state(persistent_state)

        has_report_content = bool(
            low_battery_alerts
            or ambiguous_battery_readings
            or unreachable_alerts
            or SEND_NOW
            or PRINT_REPORT_ONLY
        )

        if _report_due(persistent_state) and has_report_content:
            body = _build_report(
                low_battery_alerts,
                ambiguous_battery_readings,
                unreachable_alerts
            )

            if PRINT_REPORT_ONLY:
                print(body)

            else:
                email_sent = send_email(
                    to=settings["admin_email"],
                    subject="deCONZ device manager report",
                    body=body
                )

                if email_sent:
                    _mark_reported(
                        persistent_state,
                        low_battery_alerts,
                        unreachable_alerts
                    )
                    _save_state(persistent_state)

    except KeyboardInterrupt:
        exit()

    except Exception as e:
        ServiceException(
            "Error while trying to manage deCONZ devices",
            original_exception=e,
            severity=1
        )
        exit()

#endregion