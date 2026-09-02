#!/usr/bin/env python3
"""
Non-destructive physical device probe for the kazanfutes installation.

The script checks the physical device categories currently supported by the
repository, one unit at a time, and writes a JSON report. It does not change
switch, valve, thermostat, or light states.

Intentionally skipped:
- Nous sensors
- Aqara sensors

Run from the project environment, for example:
    python dev/dev_scripts/physical_device_tester.py

Optional:
    python dev/dev_scripts/physical_device_tester.py --output dev/device_probe_report.json
    python dev/dev_scripts/physical_device_tester.py --stale-hours 24 --strict
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import time
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from utils.project import *  # noqa: F401,F403 - project helpers are the probe API


settings["log"] = False
settings["verbosity"] = False


DEFAULT_OUTPUT = "dev/device_probe_report.json"

HEATMETER_IDS = [1, 2, 3, 4]
HEATMETER_FIELDS = [
    "flow_temperature_c",
    "return_temperature_c",
    "volume_flow_m3h",
    "power_w",
    "energy_kwh",
    "volume_m3",
]

# Mirrors services/radiator_temps_logger.py.
RADIATOR_SHELLIES = {
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

# Mirrors services/electric_submeters_logger.py.
SUBMETER_SHELLIES = {
    "192.168.101.85": {
        0: "keramia",
        1: "hm division",
        2: "ovi",
        3: "merce",
    },
    "192.168.101.76": {
        0: "studio",
        1: "szgk",
        2: "golya",
        3: "edzoterem",
    },
}

# Mirrors services/weather_station_logger.py.
WEATHER_STATION = {
    "shelly_ip": "192.168.101.26",
    "ws90_bt_addr": "fc:4d:6a:24:64:c7",
}

# Mirrors services/electric_meter_logger.py.
HOMEWIZARD_P1_URL = "http://192.168.29.88/api/v1/data"

SONOFF_MANUFACTURERS = {"sonoff", "ewelink"}
SONOFF_TEMP_HUM_MODELS = {"th01", "snzb-02d"}
SONOFF_MOTION_MODELS = {"ms01", "snzb-03", "snzb-03p"}
SONOFF_PRESENCE_MODEL_PREFIXES = ("snzb-06",)

CATEGORY_META = {
    "tuya_smart_plugs": {
        "label": "Tuya smart plugs",
        "probe": "get_pump_state() + get_pump_powers()",
    },
    "modbus_heatmeters": {
        "label": "Heat meters over Modbus",
        "probe": "get_heatmeter_data()",
    },
    "smart_bulbs": {
        "label": "Smart bulbs",
        "probe": "deCONZ light snapshot via read_deconz_state()",
    },
    "sonoff_temperature_humidity": {
        "label": "Sonoff temperature/humidity sensors",
        "probe": "deCONZ sensor snapshot, physical-device grouping",
    },
    "sonoff_motion_presence": {
        "label": "Sonoff motion/presence sensors",
        "probe": "deCONZ ZHAPresence snapshot, physical-device grouping",
    },
    "danfoss_ally_valves": {
        "label": "Danfoss Ally smart valves",
        "probe": "deCONZ ZHAThermostat snapshot",
    },
    "ikea_parasoll": {
        "label": "IKEA Parasoll opening sensors",
        "probe": "deCONZ open/close sensor snapshot",
    },
    "shelly_radiator_temperature": {
        "label": "Shelly radiator-temperature readers",
        "probe": "get_radiator_temps(..., detailed=True)",
    },
    "shelly_electric_submeters": {
        "label": "Shelly electric submeter readers",
        "probe": "Shelly.GetDeviceInfo + Shelly.GetStatus",
    },
    "ws90_weather_probe": {
        "label": "WS90 external weather probe",
        "probe": "get_weather_station_state()",
    },
    "homewizard_p1": {
        "label": "HomeWizard P1 main electricity meter reader",
        "probe": "HTTP GET /api/v1/data",
    },
}


def _json_safe(value: Any) -> Any:
    """Recursively convert values to JSON-safe forms."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return str(value)


def _exception_text(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _timed_call(func: Callable[[], Any]) -> dict[str, Any]:
    started = time.monotonic()
    try:
        data = func()
        return {
            "ok": True,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "data": _json_safe(data),
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_ms": round((time.monotonic() - started) * 1000, 1),
            "error": _exception_text(exc),
        }


def _status_from_checks(checks: dict[str, dict[str, Any]]) -> tuple[str, bool]:
    if not checks:
        return "not_tested", False

    oks = [check.get("ok") is True for check in checks.values()]
    if all(oks):
        return "ok", True
    if any(oks):
        return "degraded", True
    return "unreachable", False


def _new_category(name: str) -> dict[str, Any]:
    return {
        **CATEGORY_META[name],
        "category_error": None,
        "units": [],
    }


def _parse_deconz_time(value: Any) -> datetime | None:
    if not value or str(value).lower() == "none":
        return None

    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def _latest_timestamp(values: list[Any]) -> str | None:
    parsed = [(_parse_deconz_time(value), value) for value in values]
    parsed = [(dt, value) for dt, value in parsed if dt is not None]
    if not parsed:
        return None
    return str(max(parsed, key=lambda pair: pair[0])[1])


def _age_hours(value: Any) -> float | None:
    dt = _parse_deconz_time(value)
    if dt is None:
        return None
    return round((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 2)


def _physical_zigbee_key(raw: dict[str, Any], fallback: str) -> str:
    uniqueid = raw.get("uniqueid")
    if uniqueid:
        # deCONZ endpoint IDs are usually MAC-ENDPOINT-CLUSTER. The MAC is the
        # physical-device identity and lets us combine temp/humidity endpoints.
        return str(uniqueid).split("-", 1)[0].lower()
    return fallback


def _group_zigbee_source(source: Any, kind: str) -> dict[str, dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}

    for endpoint_id, device in source.items():
        raw = device.raw
        key = _physical_zigbee_key(raw, f"{kind}_{endpoint_id}")
        group = groups.setdefault(
            key,
            {
                "physical_id": key,
                "kind": kind,
                "endpoints": [],
            },
        )
        group["endpoints"].append(
            {
                "endpoint_id": str(endpoint_id),
                "name": raw.get("name"),
                "type": raw.get("type"),
                "manufacturer": raw.get("manufacturername"),
                "model": raw.get("modelid"),
                "uniqueid": raw.get("uniqueid"),
                "last_seen": raw.get("lastseen"),
                "last_announced": raw.get("lastannounced"),
                "state": _json_safe(raw.get("state", {})),
                "config": _json_safe(raw.get("config", {})),
            }
        )

    return groups


def _group_values(group: dict[str, Any], key: str) -> list[Any]:
    vals = []
    for endpoint in group["endpoints"]:
        value = endpoint.get(key)
        if value is not None and value not in vals:
            vals.append(value)
    return vals


def _group_types(group: dict[str, Any]) -> set[str]:
    return {str(v) for v in _group_values(group, "type") if v}


def _group_models(group: dict[str, Any]) -> set[str]:
    return {str(v) for v in _group_values(group, "model") if v}


def _group_manufacturers(group: dict[str, Any]) -> set[str]:
    return {str(v) for v in _group_values(group, "manufacturer") if v}


def _zigbee_measurement_present(group: dict[str, Any]) -> bool:
    housekeeping = {
        "lastupdated",
        "lowbattery",
        "reachable",
        "pending",
        "alert",
    }
    for endpoint in group["endpoints"]:
        state = endpoint.get("state") or {}
        if any(key not in housekeeping for key in state):
            return True
    return False


def _zigbee_record(
    group: dict[str, Any],
    stale_hours: float,
    subtype: str | None = None,
) -> dict[str, Any]:
    endpoints = group["endpoints"]

    reachable_values = []
    battery_values = []
    last_seen_values = []
    last_updated_values = []

    for endpoint in endpoints:
        config = endpoint.get("config") or {}
        state = endpoint.get("state") or {}

        reachable = config.get("reachable", state.get("reachable"))
        if isinstance(reachable, bool):
            reachable_values.append(reachable)

        battery = config.get("battery")
        if battery is None:
            battery = state.get("battery")
        if battery is not None:
            battery_values.append(battery)

        if endpoint.get("last_seen"):
            last_seen_values.append(endpoint["last_seen"])
        if state.get("lastupdated"):
            last_updated_values.append(state.get("lastupdated"))

    if any(reachable_values):
        accessible: bool | None = True
    elif reachable_values and all(value is False for value in reachable_values):
        accessible = False
    else:
        accessible = None

    last_seen = _latest_timestamp(last_seen_values)
    last_seen_age_hours = _age_hours(last_seen)
    can_report_data = _zigbee_measurement_present(group)

    problems = []
    if accessible is False:
        problems.append("deCONZ reports unreachable")
    if last_seen_age_hours is not None and last_seen_age_hours > stale_hours:
        problems.append(
            f"last seen {last_seen_age_hours} h ago (threshold {stale_hours} h)"
        )
    if not can_report_data:
        problems.append("no measurement/state payload currently exposed")

    if accessible is False:
        status = "unreachable"
    elif problems:
        status = "degraded"
    else:
        status = "ok"

    names = _group_values(group, "name")
    record = {
        "unit": names[0] if names else group["physical_id"],
        "physical_id": group["physical_id"],
        "status": status,
        "accessible": accessible,
        "can_report_data": can_report_data,
        "manufacturer": sorted(_group_manufacturers(group)),
        "model": sorted(_group_models(group)),
        "deconz_types": sorted(_group_types(group)),
        "names": names,
        "battery_percent": sorted(set(battery_values)) if battery_values else None,
        "last_seen": last_seen,
        "last_seen_age_hours": last_seen_age_hours,
        "last_updated": _latest_timestamp(last_updated_values),
        "problems": problems,
        "endpoints": endpoints,
    }
    if subtype:
        record["subtype"] = subtype
    return record


def _is_sonoff(group: dict[str, Any]) -> bool:
    manufacturers = {value.lower() for value in _group_manufacturers(group)}
    models = {value.lower() for value in _group_models(group)}
    names = {str(value).lower() for value in _group_values(group, "name")}

    return bool(
        manufacturers & SONOFF_MANUFACTURERS
        or any(model.startswith("snzb-") for model in models)
        or any(name.startswith("sonoff") for name in names)
    )


def _is_sonoff_temp_hum(group: dict[str, Any]) -> bool:
    if not _is_sonoff(group):
        return False

    models = {value.lower() for value in _group_models(group)}
    types = _group_types(group)
    return bool(
        models & SONOFF_TEMP_HUM_MODELS
        or {"ZHATemperature", "ZHAHumidity"} <= types
    )


def _sonoff_presence_subtype(group: dict[str, Any]) -> str:
    models = {value.lower() for value in _group_models(group)}
    if models & SONOFF_MOTION_MODELS:
        return "motion"
    if any(
        model.startswith(prefix)
        for model in models
        for prefix in SONOFF_PRESENCE_MODEL_PREFIXES
    ):
        return "presence"
    return "motion_or_presence"


def probe_tuya_smart_plugs() -> dict[str, Any]:
    category = _new_category("tuya_smart_plugs")

    try:
        pumps = get_pumps_info()
    except Exception as exc:
        category["category_error"] = _exception_text(exc)
        return category

    for pump, info in sorted(pumps.items(), key=lambda item: str(item[0])):
        pump = str(pump)
        checks = {
            "state": _timed_call(lambda pump=pump: get_pump_state(pump)),
            "electrical": _timed_call(
                lambda pump=pump: get_pump_powers([pump]).get(pump)
            ),
        }
        status, accessible = _status_from_checks(checks)

        category["units"].append(
            {
                "unit": pump,
                "status": status,
                "accessible": accessible,
                "can_report_data": checks["state"]["ok"] or checks["electrical"]["ok"],
                # Do not include Tuya device ID/local key in a diagnostic report.
                "configured_ip": info.get("ip") if isinstance(info, dict) else None,
                "checks": checks,
            }
        )

    return category


def probe_heatmeters() -> dict[str, Any]:
    category = _new_category("modbus_heatmeters")

    for meter_id in HEATMETER_IDS:
        check = _timed_call(
            lambda meter_id=meter_id: get_heatmeter_data(
                meter_id,
                fields=HEATMETER_FIELDS,
            )
        )
        status = "ok" if check["ok"] else "unreachable"
        category["units"].append(
            {
                "unit": str(meter_id),
                "status": status,
                "accessible": check["ok"],
                "can_report_data": check["ok"],
                "fields_requested": HEATMETER_FIELDS,
                "check": check,
            }
        )

    return category


def probe_deconz_categories(stale_hours: float) -> dict[str, dict[str, Any]]:
    category_names = [
        "smart_bulbs",
        "sonoff_temperature_humidity",
        "sonoff_motion_presence",
        "danfoss_ally_valves",
        "ikea_parasoll",
    ]
    categories = {name: _new_category(name) for name in category_names}

    started = time.monotonic()
    try:
        deconz_state = read_deconz_state()
        snapshot_elapsed_ms = round((time.monotonic() - started) * 1000, 1)
    except Exception as exc:
        error = _exception_text(exc)
        for category in categories.values():
            category["category_error"] = error
        return categories

    sensor_groups = _group_zigbee_source(deconz_state.sensors, "sensor")
    light_groups = _group_zigbee_source(deconz_state.lights, "light")

    for group in light_groups.values():
        types = {value.lower() for value in _group_types(group)}
        if not any("light" in value for value in types):
            continue
        categories["smart_bulbs"]["units"].append(
            _zigbee_record(group, stale_hours=stale_hours)
        )

    for group in sensor_groups.values():
        manufacturers = {value.lower() for value in _group_manufacturers(group)}
        models = {value.lower() for value in _group_models(group)}
        types = _group_types(group)

        if _is_sonoff_temp_hum(group):
            categories["sonoff_temperature_humidity"]["units"].append(
                _zigbee_record(group, stale_hours=stale_hours)
            )

        if _is_sonoff(group) and "ZHAPresence" in types:
            categories["sonoff_motion_presence"]["units"].append(
                _zigbee_record(
                    group,
                    stale_hours=stale_hours,
                    subtype=_sonoff_presence_subtype(group),
                )
            )

        if (
            "danfoss" in manufacturers
            and (
                "ZHAThermostat" in types
                or any(model.startswith("etrv") for model in models)
            )
        ):
            categories["danfoss_ally_valves"]["units"].append(
                _zigbee_record(group, stale_hours=stale_hours)
            )

        if (
            "ikea of sweden" in manufacturers
            and any("parasoll" in model for model in models)
        ):
            categories["ikea_parasoll"]["units"].append(
                _zigbee_record(group, stale_hours=stale_hours)
            )

    for category in categories.values():
        category["units"].sort(key=lambda unit: str(unit.get("unit", "")).lower())
        category["deconz_snapshot_elapsed_ms"] = snapshot_elapsed_ms

    return categories


def probe_radiator_shelly_readers() -> dict[str, Any]:
    category = _new_category("shelly_radiator_temperature")

    for name, ip in RADIATOR_SHELLIES.items():
        check = _timed_call(
            lambda name=name, ip=ip: get_radiator_temps(
                {name: ip},
                detailed=True,
            )
        )
        status = "ok" if check["ok"] else "unreachable"
        category["units"].append(
            {
                "unit": name,
                "ip": ip,
                "status": status,
                "accessible": check["ok"],
                "can_report_data": check["ok"],
                "check": check,
            }
        )

    return category


def probe_submeter_shelly_readers() -> dict[str, Any]:
    category = _new_category("shelly_electric_submeters")

    for ip, channels in SUBMETER_SHELLIES.items():
        checks = {
            "device_info": _timed_call(
                lambda ip=ip: shelly_rpc(ip, "Shelly.GetDeviceInfo")
            ),
            "status": _timed_call(
                lambda ip=ip: shelly_rpc(ip, "Shelly.GetStatus")
            ),
        }
        status, accessible = _status_from_checks(checks)

        category["units"].append(
            {
                "unit": ip,
                "ip": ip,
                "status": status,
                "accessible": accessible,
                "can_report_data": accessible,
                "channels": {str(k): v for k, v in channels.items()},
                "pulse_reporting": {
                    "method": "WebSocket single_push events",
                    "repo_helper": "listen_shelly_single_pushes()",
                    "actively_waited_for_pulse": False,
                    "note": (
                        "The production submeter service counts edge events. "
                        "This non-blocking tester confirms Shelly RPC access/status "
                        "but does not wait indefinitely for a real meter pulse."
                    ),
                },
                "checks": checks,
            }
        )

    return category


def probe_ws90() -> dict[str, Any]:
    category = _new_category("ws90_weather_probe")
    check = _timed_call(
        lambda: get_weather_station_state(**WEATHER_STATION)
    )
    status = "ok" if check["ok"] else "unreachable"

    category["units"].append(
        {
            "unit": WEATHER_STATION["ws90_bt_addr"],
            "gateway_shelly_ip": WEATHER_STATION["shelly_ip"],
            "ws90_bt_addr": WEATHER_STATION["ws90_bt_addr"],
            "status": status,
            "accessible": check["ok"],
            "can_report_data": check["ok"],
            "check": check,
        }
    )
    return category


def probe_homewizard_p1() -> dict[str, Any]:
    category = _new_category("homewizard_p1")

    def read_p1():
        response = requests.get(HOMEWIZARD_P1_URL, timeout=5)
        response.raise_for_status()
        return response.json()

    check = _timed_call(read_p1)
    status = "ok" if check["ok"] else "unreachable"

    category["units"].append(
        {
            "unit": HOMEWIZARD_P1_URL,
            "url": HOMEWIZARD_P1_URL,
            "status": status,
            "accessible": check["ok"],
            "can_report_data": check["ok"],
            "check": check,
        }
    )
    return category


def _summarize_category(category: dict[str, Any]) -> dict[str, Any]:
    counts = {
        "total": len(category.get("units", [])),
        "ok": 0,
        "degraded": 0,
        "unreachable": 0,
        "error": 0,
        "not_tested": 0,
    }

    for unit in category.get("units", []):
        status = unit.get("status", "error")
        if status not in counts:
            status = "error"
        counts[status] += 1

    counts["category_error"] = category.get("category_error")
    return counts


def _build_summary(categories: dict[str, dict[str, Any]]) -> dict[str, Any]:
    by_category = {
        name: _summarize_category(category)
        for name, category in categories.items()
    }

    totals = {
        "total": sum(item["total"] for item in by_category.values()),
        "ok": sum(item["ok"] for item in by_category.values()),
        "degraded": sum(item["degraded"] for item in by_category.values()),
        "unreachable": sum(item["unreachable"] for item in by_category.values()),
        "error": sum(item["error"] for item in by_category.values()),
        "not_tested": sum(item["not_tested"] for item in by_category.values()),
        "category_errors": sum(
            1 for item in by_category.values() if item["category_error"]
        ),
    }

    return {
        "totals": totals,
        "by_category": by_category,
    }


def build_report(stale_hours: float) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}

    categories["tuya_smart_plugs"] = probe_tuya_smart_plugs()
    categories["modbus_heatmeters"] = probe_heatmeters()
    categories.update(probe_deconz_categories(stale_hours=stale_hours))
    categories["shelly_radiator_temperature"] = probe_radiator_shelly_readers()
    categories["shelly_electric_submeters"] = probe_submeter_shelly_readers()
    categories["ws90_weather_probe"] = probe_ws90()
    categories["homewizard_p1"] = probe_homewizard_p1()

    return {
        "generated_at": timestamp(),
        "host": socket.gethostname(),
        "mode": "read_only",
        "stale_after_hours": stale_hours,
        "skipped_categories": {
            "nous_sensors": "explicitly skipped: known unavailable",
            "aqara_sensors": "explicitly skipped: known unavailable",
        },
        "summary": _build_summary(categories),
        "categories": categories,
    }


def write_report(report: dict[str, Any], output: str) -> str:
    root = get_project_root()
    path = output if os.path.isabs(output) else os.path.join(root, output)
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(
            _json_safe(report),
            handle,
            indent=2,
            ensure_ascii=False,
            sort_keys=False,
        )
        handle.write("\n")

    return path


def print_report(report: dict[str, Any], path: str) -> None:
    summary = report["summary"]

    print("=" * 78)
    print("PHYSICAL DEVICE PROBE REPORT")
    print("=" * 78)
    print(f"Generated: {report['generated_at']}")
    print(f"Host:      {report['host']}")
    print(f"Mode:      {report['mode']}")
    print(f"Stale:     > {report['stale_after_hours']} h since deCONZ lastseen")
    print()

    for name, category in report["categories"].items():
        counts = summary["by_category"][name]
        print(
            f"[{category['label']}] "
            f"total={counts['total']} ok={counts['ok']} "
            f"degraded={counts['degraded']} "
            f"unreachable={counts['unreachable']} error={counts['error']}"
        )

        if category.get("category_error"):
            print(f"  CATEGORY ERROR: {category['category_error']}")
            continue

        if not category["units"]:
            print("  No matching/configured units found.")
            continue

        for unit in category["units"]:
            details = []
            if unit.get("subtype"):
                details.append(str(unit["subtype"]))
            if unit.get("ip"):
                details.append(str(unit["ip"]))
            if unit.get("last_seen_age_hours") is not None:
                details.append(f"lastseen={unit['last_seen_age_hours']}h")
            suffix = f" ({', '.join(details)})" if details else ""
            print(f"  {unit['status'].upper():11} {unit['unit']}{suffix}")
            for problem in unit.get("problems", []):
                print(f"      - {problem}")

            for check_name, check in unit.get("checks", {}).items():
                if not check.get("ok"):
                    print(f"      - {check_name}: {check.get('error')}")
            check = unit.get("check")
            if check and not check.get("ok"):
                print(f"      - {check.get('error')}")

        print()

    totals = summary["totals"]
    print("-" * 78)
    print(
        "TOTAL "
        f"units={totals['total']} ok={totals['ok']} "
        f"degraded={totals['degraded']} "
        f"unreachable={totals['unreachable']} "
        f"errors={totals['error']} "
        f"category_errors={totals['category_errors']}"
    )
    print("Skipped: Nous sensors, Aqara sensors")
    print(f"JSON report: {path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only comprehensive physical device probe."
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"JSON report path, relative to project root by default ({DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--stale-hours",
        type=float,
        default=24.0,
        help="Flag deCONZ devices as degraded after this many hours without lastseen.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero if any unit/category is degraded, unreachable, or errored.",
    )
    args = parser.parse_args()

    report = build_report(stale_hours=args.stale_hours)
    path = write_report(report, args.output)
    print_report(report, path)

    if args.strict:
        totals = report["summary"]["totals"]
        unhealthy = (
            totals["degraded"]
            + totals["unreachable"]
            + totals["error"]
            + totals["category_errors"]
        )
        return 1 if unhealthy else 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
