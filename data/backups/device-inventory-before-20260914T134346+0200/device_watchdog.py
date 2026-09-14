"""Run the physical-infrastructure watchdog once.

This service is read-only with respect to devices.  It writes only watchdog
state/history files and sends email for newly confirmed critical incidents.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from typing import Any

import requests

from utils.project import *  # noqa: F401,F403 - shared project transport helpers
from utils.shelly_discovery import build_shelly_resolver, load_shelly_config
from utils.device_watchdog import (
    INCIDENTS_RELATIVE_PATH,
    MANUAL_STATE_RELATIVE_PATH,
    SOLVED_RELATIVE_PATH,
    STATE_RELATIVE_PATH,
    DIGEST_RELATIVE_PATH,
    append_ndjson,
    apply_battery_scale_learning,
    atomic_write_json,
    battery_observation,
    build_digest,
    classify_zigbee,
    initial_incident_state,
    last_ndjson_record,
    now_iso,
    ping_healthchecks,
    read_json,
    render_grouped_report,
    render_table,
    snapshot,
    update_incidents,
    digest_due,
)


CONFIG_RELATIVE_PATH = "config/device_watchdog.json"
HEATMETER_FIELDS = [
    "flow_temperature_c", "return_temperature_c", "volume_flow_m3h",
    "power_w", "energy_kwh", "volume_m3",
]
HOMEWIZARD_P1_URL = "http://192.168.29.88/api/v1/data"


def _safe(callable_, default: Any = None) -> tuple[Any, str | None]:
    try:
        return callable_(), None
    except Exception as error:
        return default, f"{type(error).__name__}: {error}"


def read_heating_context(config: dict[str, Any]) -> dict[str, Any]:
    """Read the configured heating-system master switch."""
    settings = config.get("heating_context", {})
    relative_path = settings.get("source_relative_path", "config/heating_switch.json")
    field = settings.get("field", "system")
    payload = read_json(os.path.join(get_project_root(), relative_path), {})
    raw_switch = payload.get(field)
    return {
        "heating_on": raw_switch == 1,
        "heating_switch_value": raw_switch,
        "heating_context_status": "available" if field in payload else "unavailable",
    }


def apply_heating_context(devices: list[dict[str, Any]], config: dict[str, Any]) -> None:
    context = read_heating_context(config)
    profiles = config.get("profiles", {})
    for device in devices:
        profile = profiles.get(device.get("profile", ""), {})
        if profile.get("critical_when_heating_on"):
            device.setdefault("facts", {}).update(context)


def initial_manual_state() -> dict[str, Any]:
    return {"schema_version": 1, "parasoll_temporary_batteries": {}}


def apply_manual_state(devices: list[dict[str, Any]], manual_state: dict[str, Any], incidents: dict[str, Any]) -> None:
    """Attach persistent human-entered maintenance facts to observed devices."""
    by_id = {device["device_id"]: device for device in devices}
    by_name = {
        str(device.get("name", "")).casefold(): device
        for device in devices
        if device.get("profile") == "parasoll" and device.get("name")
    }
    known_devices = incidents.get("known_devices", {})
    for key, record in manual_state.get("parasoll_temporary_batteries", {}).items():
        record = record if isinstance(record, dict) else {}
        device = by_id.get(record.get("device_id")) or by_name.get(str(key).casefold())
        if device is None:
            known = known_devices.get(record.get("device_id"))
            if known is None:
                known = next((item for item in known_devices.values() if item.get("profile") == "parasoll" and str(item.get("name", "")).casefold() == str(key).casefold()), None)
            if known is not None:
                device = {**known, "facts": {"manual_only": True}}
                devices.append(device)
        if device and device.get("profile") == "parasoll":
            device.setdefault("facts", {})["temporary_nonrechargeable_battery"] = {
                "parasoll_name": key,
                "set_at": record.get("set_at"),
            }


def _known_parasolls(incidents: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        [device for device in incidents.get("known_devices", {}).values() if device.get("profile") == "parasoll"],
        key=lambda device: str(device.get("name", "")).casefold(),
    )


def _resolve_parasoll(incidents: dict[str, Any], requested_name: str) -> dict[str, Any]:
    matches = [
        device for device in _known_parasolls(incidents)
        if str(device.get("name", "")).casefold() == requested_name.strip().casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    available = ", ".join(str(device.get("name")) for device in _known_parasolls(incidents)) or "none"
    if not matches:
        raise ValueError(f"Unknown Parasoll name {requested_name!r}. Available names: {available}")
    raise ValueError(f"Parasoll name {requested_name!r} is not unique; use a unique configured name")


def set_parasoll_temporary_battery(project_root: str, requested_name: str) -> tuple[str, bool]:
    incidents = read_json(os.path.join(project_root, INCIDENTS_RELATIVE_PATH), initial_incident_state())
    device = _resolve_parasoll(incidents, requested_name)
    canonical_name = str(device["name"])
    path = os.path.join(project_root, MANUAL_STATE_RELATIVE_PATH)
    state = read_json(path, initial_manual_state())
    entries = state.setdefault("parasoll_temporary_batteries", {})
    existing_key = next((key for key in entries if key.casefold() == canonical_name.casefold()), None)
    if existing_key is not None:
        return existing_key, False
    entries[canonical_name] = {
        "device_id": device["device_id"],
        "set_at": now_iso(),
    }
    atomic_write_json(path, state)
    return canonical_name, True


def clear_parasoll_temporary_battery(project_root: str, requested_name: str) -> tuple[str, bool]:
    path = os.path.join(project_root, MANUAL_STATE_RELATIVE_PATH)
    state = read_json(path, initial_manual_state())
    entries = state.setdefault("parasoll_temporary_batteries", {})
    existing_key = next((key for key in entries if key.casefold() == requested_name.strip().casefold()), None)
    if existing_key is None:
        incidents = read_json(os.path.join(project_root, INCIDENTS_RELATIVE_PATH), initial_incident_state())
        canonical_name = str(_resolve_parasoll(incidents, requested_name)["name"])
        return canonical_name, False
    entries.pop(existing_key)
    atomic_write_json(path, state)
    return existing_key, True


def render_parasoll_temporary_batteries(project_root: str) -> str:
    state = read_json(os.path.join(project_root, MANUAL_STATE_RELATIVE_PATH), initial_manual_state())
    entries = state.get("parasoll_temporary_batteries", {})
    if not entries:
        return "No Parasoll devices are marked as using a temporary non-rechargeable battery."
    lines = ["PARASOLL TEMPORARY NON-RECHARGEABLE BATTERIES", "NAME                           SET AT", "------------------------------ -------------------------"]
    for name, record in sorted(entries.items(), key=lambda item: item[0].casefold()):
        record = record if isinstance(record, dict) else {}
        lines.append(f"{name[:30]:30} {record.get('set_at') or 'unknown'}")
    return "\n".join(lines)


def _deconz_time(value: Any) -> str | None:
    if not value or str(value).lower() == "none":
        return None
    return str(value)


def _physical_key(raw: dict[str, Any], fallback: str) -> str:
    unique_id = raw.get("uniqueid")
    return str(unique_id).split("-", 1)[0].lower() if unique_id else fallback


def _normalize_ieee(value: Any) -> str | None:
    """Normalize deCONZ bridge/device identifiers to colon-separated IEEE form."""
    if value is None:
        return None
    compact = "".join(character for character in str(value).lower() if character in "0123456789abcdef")
    if len(compact) != 16:
        return None
    return ":".join(compact[index:index + 2] for index in range(0, 16, 2))


def read_deconz_device_inventory() -> tuple[list[str], str]:
    """Read the raw deCONZ device list and the coordinator IEEE address."""
    deconz = get_deconz_access_params()
    base_url = f"{deconz['api_url'].strip().rstrip('/')}/{deconz['api_key'].strip()}"
    devices_response = requests.get(f"{base_url}/devices", timeout=10)
    devices_response.raise_for_status()
    config_response = requests.get(f"{base_url}/config", timeout=10)
    config_response.raise_for_status()
    device_ids = devices_response.json()
    gateway_config = config_response.json()
    if not isinstance(device_ids, list):
        raise ValueError("deCONZ /devices did not return a list")
    bridge_id = _normalize_ieee(gateway_config.get("bridgeid"))
    if bridge_id is None:
        raise ValueError("deCONZ /config did not provide a valid bridgeid")
    return device_ids, bridge_id


def incomplete_deconz_device_ids(
    device_ids: list[str],
    resource_device_ids: set[str],
    bridge_id: str,
) -> list[str]:
    """Return non-coordinator devices which expose no sensor/light resources."""
    coordinator = _normalize_ieee(bridge_id)
    known = {_normalize_ieee(value) for value in resource_device_ids}
    bare = {
        normalized
        for value in device_ids
        if (normalized := _normalize_ieee(value)) is not None
        and normalized != coordinator
        and normalized not in known
    }
    return sorted(bare)


def _scaled(value: Any) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric / 100.0 if abs(numeric) > 200 else numeric


def collect_deconz(config: dict[str, Any]) -> list[dict[str, Any]]:
    session, error = _safe(read_deconz_state)
    if error:
        return [{
            "device_id": "gateway:deconz",
            "name": "deCONZ gateway",
            "category": "zigbee_gateway",
            "hardware_type": "deCONZ Zigbee gateway",
            "profile": "critical_dependency",
            "facts": {"collection_error": error},
        }]

    groups: dict[str, list[dict[str, Any]]] = {}
    for source_name, source in (("sensor", session.sensors), ("light", session.lights)):
        for endpoint_id, device in source.items():
            raw = device.raw
            key = _physical_key(raw, f"{source_name}_{endpoint_id}")
            groups.setdefault(key, []).append(raw)

    raw_inventory, inventory_error = _safe(read_deconz_device_inventory)

    devices: list[dict[str, Any]] = [{
        "device_id": "gateway:deconz",
        "name": "deCONZ gateway",
        "category": "zigbee_gateway",
        "hardware_type": "deCONZ Zigbee gateway",
        "profile": "critical_dependency",
        "facts": {"reachable": True, "last_seen_at": now_iso()},
    }]
    if inventory_error:
        devices.append({
            "device_id": "collector:deconz_device_inventory",
            "name": "deCONZ device inventory",
            "category": "collector",
            "hardware_type": "deCONZ device inventory",
            "profile": "infrastructure",
            "dependencies": ["gateway:deconz"],
            "facts": {"collection_error": inventory_error},
        })
    else:
        raw_device_ids, bridge_id = raw_inventory
        configured_names = config.get("deconz", {}).get("incomplete_device_names", {})
        normalized_names = {
            normalized: str(name)
            for ieee, name in configured_names.items()
            if (normalized := _normalize_ieee(ieee)) is not None
        }
        for physical_id in incomplete_deconz_device_ids(raw_device_ids, set(groups), bridge_id):
            devices.append({
                "device_id": f"zigbee:{physical_id}",
                "name": normalized_names.get(physical_id, f"Unidentified Zigbee device {physical_id}"),
                "category": "incomplete_zigbee_device",
                "hardware_type": "Incomplete deCONZ Zigbee device",
                "profile": "zigbee",
                "dependencies": ["gateway:deconz"],
                "facts": {
                    "incomplete_interview": True,
                    "ieee_address": physical_id,
                    "reachable": None,
                    "last_seen_at": None,
                    "measurements": {},
                },
            })
    scale_by_model = config.get("battery_scales", {}).get("by_model", {})
    default_scale = config.get("battery_scales", {}).get("default", "unknown")
    for physical_id, raws in groups.items():
        profile, category = classify_zigbee(raws)
        names = [str(raw.get("name")) for raw in raws if raw.get("name")]
        model_key = "|".join(sorted({f"{raw.get('manufacturername', '')}|{raw.get('modelid', '')}" for raw in raws}))
        hardware_types = sorted({
            " ".join(part for part in (str(raw.get("manufacturername", "")).strip(), str(raw.get("modelid", "")).strip()) if part)
            for raw in raws
            if raw.get("manufacturername") or raw.get("modelid")
        })
        hardware_type = "; ".join(hardware_types) if hardware_types else category.replace("_", " ")
        configured_scale = config.get("battery_scales", {}).get("by_device", {}).get(
            f"zigbee:{physical_id}",
            scale_by_model.get(model_key, default_scale),
        )
        reachable_values = []
        batteries, low_batteries, last_seen_values = [], [], []
        measurements: dict[str, Any] = {}
        for raw in raws:
            state = raw.get("state") or {}
            device_config = raw.get("config") or {}
            reachable = device_config.get("reachable", state.get("reachable"))
            if isinstance(reachable, bool):
                reachable_values.append(reachable)
            battery = device_config.get("battery", state.get("battery"))
            if battery is not None:
                batteries.append(battery)
            low_batteries.append(state.get("lowbattery") is True)
            if raw.get("lastseen"):
                last_seen_values.append(_deconz_time(raw.get("lastseen")))
            if "temperature" in state:
                measurements["temperature_c"] = _scaled(state.get("temperature"))
            if "humidity" in state:
                measurements["humidity_percent"] = _scaled(state.get("humidity"))
        raw_battery = min(batteries) if batteries else None
        facts = {
            "reachable": True if any(reachable_values) else (False if reachable_values else None),
            "last_seen_at": max(last_seen_values) if last_seen_values else None,
            "battery": battery_observation(raw_battery, any(low_batteries), configured_scale=configured_scale),
            "measurements": measurements,
            "model_key": model_key,
            "hardware_type": hardware_type,
        }
        devices.append({
            "device_id": f"zigbee:{physical_id}",
            "name": names[0] if names else f"Zigbee {physical_id}",
            "category": category,
            "hardware_type": hardware_type,
            "profile": profile,
            "dependencies": ["gateway:deconz"],
            "facts": facts,
        })
    return devices


def collect_pumps() -> list[dict[str, Any]]:
    pumps, error = _safe(get_pumps_info, {})
    devices = [{
        "device_id": "collector:tuya_pumps", "name": "Tuya pump collector",
        "category": "collector", "profile": "critical_pump",
        "facts": {"reachable": error is None, "collection_error": error, "last_seen_at": now_iso() if error is None else None},
    }]
    if error:
        return devices
    for pump in sorted(pumps, key=str):
        state, state_error = _safe(lambda pump=pump: get_pump_state(str(pump)))
        power, power_error = _safe(lambda pump=pump: get_pump_powers([str(pump)]).get(str(pump)))
        errors = [item for item in (state_error, power_error) if item]
        devices.append({
            "device_id": f"tuya:pump:{pump}", "name": f"Heating pump {pump}",
            "category": "tuya_pump", "profile": "critical_pump",
            "dependencies": ["collector:tuya_pumps"],
            "facts": {
                "reachable": not errors,
                "collection_error": "; ".join(errors) if errors else None,
                "last_seen_at": now_iso(),
                "measurements": {"power_w": power, "switch_state": state},
            },
        })
    return devices


def collect_heatmeters() -> list[dict[str, Any]]:
    devices = []
    for meter_id in range(1, 5):
        data, error = _safe(lambda meter_id=meter_id: get_heatmeter_data(meter_id, fields=HEATMETER_FIELDS), {})
        devices.append({
            "device_id": f"modbus:heatmeter:{meter_id}", "name": f"Heatmeter {meter_id}",
            "category": "heatmeter", "profile": "infrastructure",
            "facts": {"reachable": error is None, "collection_error": error, "last_seen_at": now_iso() if error is None else None, "measurements": data or {}},
        })
    return devices


def collect_shelly() -> list[dict[str, Any]]:
    root = get_project_root()
    shelly_config, config_error = _safe(lambda: load_shelly_config(root))
    if config_error:
        return [{"device_id": "collector:shelly", "name": "Shelly collector", "category": "collector", "profile": "infrastructure", "facts": {"collection_error": config_error}}]
    resolver = build_shelly_resolver(root, shelly_config)
    names = list(dict.fromkeys(shelly_config.get("radiator_devices", []) + list(shelly_config.get("submeters", {}))))
    specs = {name: shelly_config["devices"][name] for name in names}
    resolved, resolution_error = _safe(lambda: resolver.resolve_many(specs), ({}, {}))
    if resolution_error:
        return [{"device_id": "collector:shelly", "name": "Shelly collector", "category": "collector", "profile": "infrastructure", "facts": {"collection_error": resolution_error}}]
    resolved, resolution_errors = resolved
    devices = []
    for name in names:
        if name not in resolved:
            devices.append({"device_id": f"shelly:{name}", "name": name, "category": "shelly", "profile": "infrastructure", "facts": {"collection_error": resolution_errors.get(name, "not found")}})
            continue
        record = resolved[name]
        devices.append({
            "device_id": f"shelly:{record['mac']}", "name": name, "category": "shelly",
            "profile": "infrastructure", "facts": {"reachable": True, "last_seen_at": record.get("seen_at") or now_iso(), "measurements": {}},
        })
    radiator_names = [name for name in shelly_config.get("radiator_devices", []) if name in resolved]
    if radiator_names:
        details, detail_error = _safe(lambda: get_radiator_temps({name: resolved[name]["ip"] for name in radiator_names}, detailed=True), {})
        for name in radiator_names:
            record = resolved[name]
            item = (details.get("devices", {}) or {}).get(name, {}) if details else {}
            for peripheral_name, peripheral in (item.get("peripherals", {}) or {}).items():
                devices.append({
                    "device_id": f"shelly:{record['mac']}:temperature:{peripheral.get('addr') or peripheral_name}",
                    "name": f"{name} / {peripheral_name}", "category": "radiator_temperature", "profile": "infrastructure",
                    "dependencies": [f"shelly:{record['mac']}"],
                    "facts": {"reachable": not peripheral.get("errors") and detail_error is None, "collection_error": detail_error or ("; ".join(peripheral.get("errors", [])) if peripheral.get("errors") else None), "last_seen_at": now_iso(), "measurements": {"temperature_c": peripheral.get("temp")}},
                })
    weather = shelly_config.get("weather_station", {})
    gateway_name = weather.get("gateway_device")
    if gateway_name and gateway_name in resolved:
        reading, error = _safe(lambda: get_weather_station_state(resolved[gateway_name]["ip"], weather["ws90_bt_addr"]))
        devices.append({"device_id": f"ws90:{weather['ws90_bt_addr']}", "name": "WS90 weather station", "category": "weather_station", "profile": "infrastructure", "dependencies": [f"shelly:{resolved[gateway_name]['mac']}"], "facts": {"reachable": error is None, "collection_error": error, "last_seen_at": (reading or {}).get("last_updated"), "battery": battery_observation((reading or {}).get("state", {}).get("battery_pct"), False), "measurements": {"temperature_c": (reading or {}).get("state", {}).get("temperature_c"), "humidity_percent": (reading or {}).get("state", {}).get("humidity_pct")}}})
    return devices


def collect_homewizard() -> list[dict[str, Any]]:
    def read_p1():
        response = requests.get(HOMEWIZARD_P1_URL, timeout=5)
        response.raise_for_status()
        return response.json()
    data, error = _safe(read_p1, {})
    return [{"device_id": "homewizard:p1", "name": "HomeWizard P1", "category": "electricity_meter", "profile": "infrastructure", "facts": {"reachable": error is None, "collection_error": error, "last_seen_at": now_iso() if error is None else None, "measurements": {"voltage_v": (data or {}).get("active_voltage_l1_v")}}}]


def _service_active(unit: str) -> bool | None:
    if os.name != "posix":
        return None
    try:
        return subprocess.run(["systemctl", "is-active", "--quiet", unit], check=False, timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return None


def collect_log_backed_infrastructure() -> list[dict[str, Any]]:
    root = get_project_root()
    sources = [
        ("pv:inverter", "PV inverter", "electricity/pv_inverter.json", "pv_logger", "infrastructure"),
        ("gas:meter", "Gas meter", "gas_consumption/gas_relay_turns.json", "gasmeter_logger", "gas_meter"),
        ("pipeline:presence", "Presence acquisition", "presence/presence_all.json", "presence_logger", "reporter"),
        ("pipeline:occupancy", "Occupancy pipeline", "occupancy/occupancy.json", "occupancy_logger", "reporter"),
        ("pipeline:room_sensors", "Room temperature/humidity acquisition", "temperature_and_humidity/temperature_and_humidity.json", "temperature_and_humidity_logger", "reporter"),
    ]
    devices = []
    for device_id, name, log_relative, service_name, profile in sources:
        record = last_ndjson_record(os.path.join(root, "data", "logs", log_relative))
        timestamp_value = (record or {}).get("timestamp")
        facts = {"reachable": True, "last_seen_at": timestamp_value, "measurements": {}}
        if device_id == "gas:meter":
            facts["last_event_at"] = timestamp_value
            facts["service_active"] = _service_active(f"{service_name}.service")
        elif record is None:
            facts["collection_error"] = f"No log record at data/logs/{log_relative}"
        if device_id == "pv:inverter" and record:
            facts["last_seen_at"] = record.get("source_timestamp") or timestamp_value
            facts["measurements"] = {"voltage_v": record.get("phase_a_voltage_v"), "frequency_hz": record.get("grid_frequency_hz")}
        devices.append({"device_id": device_id, "name": name, "category": "log_backed_infrastructure", "profile": profile, "facts": facts})
    return devices


def collect_all(config: dict[str, Any]) -> list[dict[str, Any]]:
    return collect_deconz(config) + collect_pumps() + collect_heatmeters() + collect_shelly() + collect_homewizard() + collect_log_backed_infrastructure()


def _notify_critical(incidents: dict[str, Any], now: datetime) -> None:
    """Deliver each critical opening once; retry only when delivery itself failed."""
    due = [
        entry for entry in incidents.get("active", {}).values()
        if entry.get("class") == "critical" and not entry.get("immediate_notification_sent_at")
    ]
    if not due:
        return
    due_by_id = {entry["incident_id"]: entry for entry in due}
    body = render_grouped_report({"active": due_by_id}, "CRITICAL DEVICE INCIDENTS")
    try:
        notify_admin("Critical physical-infrastructure issue", body)
    except Exception as error:
        report(f"Device watchdog could not send critical email: {error}")
        return
    for entry in due:
        incidents["active"][entry["incident_id"]]["immediate_notification_sent_at"] = now_iso(now)


def _recent_ndjson(path: str, limit: int = 50) -> list[dict[str, Any]]:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            records = [json.loads(line) for line in handle if line.strip()]
    except (OSError, json.JSONDecodeError):
        return []
    return [record for record in records[-limit:] if isinstance(record, dict)]


def run(config: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    root = get_project_root()
    now = datetime.now().astimezone()
    incidents_path = os.path.join(root, INCIDENTS_RELATIVE_PATH)
    previous = read_json(incidents_path, initial_incident_state())
    devices = collect_all(config)
    manual_state = read_json(os.path.join(root, MANUAL_STATE_RELATIVE_PATH), initial_manual_state())
    apply_manual_state(devices, manual_state, previous)
    apply_heating_context(devices, config)
    apply_battery_scale_learning(devices, previous, config, now)
    incidents, opened, solved = update_incidents(previous, devices, config, now)
    current_snapshot = snapshot(devices, incidents, now)

    if not dry_run:
        live = config.get("mode", "shadow") == "live"
        atomic_write_json(incidents_path, incidents)
        atomic_write_json(os.path.join(root, STATE_RELATIVE_PATH), current_snapshot)
        for entry in solved:
            append_ndjson(os.path.join(root, SOLVED_RELATIVE_PATH), entry)
        if live:
            _notify_critical(incidents, now)
        atomic_write_json(incidents_path, incidents)
        if live and digest_due(incidents, config, now):
            active = incidents.get("active", {})
            digest_settings = config.get("digest", config.get("weekly_digest", {}))
            frequency = digest_settings.get("frequency", "weekly")
            if active or digest_settings.get("send_when_empty", False):
                digest = build_digest(incidents, now, frequency)
                try:
                    notify_admin(f"Kazanfutes {frequency} physical-infrastructure to-do list", digest)
                except Exception as error:
                    report(f"Device watchdog could not send {frequency} digest: {error}")
                else:
                    append_ndjson(os.path.join(root, DIGEST_RELATIVE_PATH), {"timestamp": now_iso(now), "active_incident_count": len(active), "body": digest})
                    incidents["digest_sent_for"] = now.date().isoformat()
                    atomic_write_json(incidents_path, incidents)
            else:
                incidents["digest_sent_for"] = now.date().isoformat()
                atomic_write_json(incidents_path, incidents)
        if live:
            ping_healthchecks(root, config)
    return {"devices": devices, "incidents": incidents, "opened": opened, "solved": solved, "snapshot": current_snapshot}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the physical-infrastructure watchdog once.")
    parser.add_argument("--dry-run", action="store_true", help="Collect and evaluate without writes, email, or Healthchecks ping.")
    parser.add_argument("--table", action="store_true", help="Print current active incidents after the run.")
    parser.add_argument("--show-state", action="store_true", help="Print the saved active-incident table without collecting devices.")
    parser.add_argument("--show-solved", action="store_true", help="Print the 50 most recently solved incidents without collecting devices.")
    maintenance = parser.add_mutually_exclusive_group()
    maintenance.add_argument("--set-parasoll-temporary-battery", metavar="NAME", help="Mark a Parasoll as temporarily using a non-rechargeable battery.")
    maintenance.add_argument("--clear-parasoll-temporary-battery", metavar="NAME", help="Clear a Parasoll temporary-battery marker.")
    maintenance.add_argument("--list-parasoll-temporary-batteries", action="store_true", help="List active Parasoll temporary-battery markers.")
    display = parser.add_mutually_exclusive_group()
    display.add_argument("--grouped", action="store_true", help="Group conditions under each device in CLI output.")
    display.add_argument("--detailed", action="store_true", help="Show one CLI table row per condition (the default).")
    args = parser.parse_args()
    render = render_grouped_report if args.grouped else render_table
    project_root = get_project_root()
    config = read_json(os.path.join(project_root, CONFIG_RELATIVE_PATH), {})
    if args.list_parasoll_temporary_batteries:
        print(render_parasoll_temporary_batteries(project_root))
        return 0
    if args.set_parasoll_temporary_battery:
        try:
            name, changed = set_parasoll_temporary_battery(project_root, args.set_parasoll_temporary_battery)
        except ValueError as error:
            parser.error(str(error))
        if changed:
            run(config)
            print(f"Marked {name!r}; watchdog state refreshed.")
        else:
            print(f"{name!r} is already marked; no change.")
        return 0
    if args.clear_parasoll_temporary_battery:
        try:
            name, changed = clear_parasoll_temporary_battery(project_root, args.clear_parasoll_temporary_battery)
        except ValueError as error:
            parser.error(str(error))
        if changed:
            run(config)
            print(f"Cleared {name!r}; watchdog state refreshed.")
        else:
            print(f"{name!r} is not marked; no change.")
        return 0
    if args.show_state:
        incidents = read_json(os.path.join(project_root, INCIDENTS_RELATIVE_PATH), initial_incident_state())
        print(render(incidents))
        return 0
    if args.show_solved:
        solved = _recent_ndjson(os.path.join(project_root, SOLVED_RELATIVE_PATH))
        print(render({"active": {entry.get("incident_id", str(index)): entry for index, entry in enumerate(solved)}}, "RECENTLY SOLVED DEVICE INCIDENTS"))
        return 0
    result = run(config, dry_run=args.dry_run)
    if args.table or args.dry_run:
        print(render(result["incidents"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
