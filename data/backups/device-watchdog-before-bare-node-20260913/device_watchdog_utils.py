"""Read-only physical-infrastructure watchdog primitives.

This module deliberately does not use ServiceException or the project's
software-error registry.  Device conditions have their own persistent
open/solved lifecycle and are suitable for a human-maintenance inventory.
"""

from __future__ import annotations

import copy
import json
import math
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import requests


STATE_RELATIVE_PATH = "system/device_watchdog_state.json"
INCIDENTS_RELATIVE_PATH = "system/device_watchdog_incidents.json"
MANUAL_STATE_RELATIVE_PATH = "system/device_watchdog_manual_state.json"
SOLVED_RELATIVE_PATH = "data/logs/device_watchdog/solved_incidents.jsonl"
DIGEST_RELATIVE_PATH = "data/logs/device_watchdog/digest.jsonl"


def now_iso(now: datetime | None = None) -> str:
    """Return a timezone-aware local ISO timestamp."""
    return (now or datetime.now().astimezone()).isoformat(timespec="seconds")


def parse_time(value: Any) -> datetime | None:
    if value is None or str(value).strip().lower() in {"", "none", "null"}:
        return None
    text = str(value).strip()
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d-%H-%M-%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                parsed = datetime.strptime(text.split(".")[0], fmt)
                break
            except ValueError:
                parsed = None
        if parsed is None:
            return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def age_minutes(value: Any, now: datetime) -> float | None:
    parsed = parse_time(value)
    if parsed is None:
        return None
    return max(0.0, (now.astimezone() - parsed).total_seconds() / 60.0)


def read_json(path: str, default: Any) -> Any:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return copy.deepcopy(default)


def atomic_write_json(path: str, data: Any) -> None:
    """Persist a complete JSON document without exposing partial writes."""
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".device-watchdog-", suffix=".json", dir=directory, text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.unlink(temporary_path)
        except OSError:
            pass
        raise


def append_ndjson(path: str, record: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def last_ndjson_record(path: str) -> dict[str, Any] | None:
    """Read the final valid NDJSON record without loading a full log."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            end = handle.tell()
            block_size = 8192
            remainder = b""
            while end > 0:
                size = min(block_size, end)
                end -= size
                handle.seek(end)
                remainder = handle.read(size) + remainder
                lines = remainder.splitlines()
                if end > 0:
                    remainder = lines.pop(0) if lines else b""
                for line in reversed(lines):
                    try:
                        value = json.loads(line.decode("utf-8"))
                        return value if isinstance(value, dict) else None
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
    except OSError:
        return None
    return None


def battery_observation(
    raw: Any,
    low_battery: Any,
    *,
    configured_scale: str = "unknown",
) -> dict[str, Any]:
    """Preserve raw battery units and normalize only when the scale is known.

    Values above 100 establish the common 0..200 half-percent convention. A
    value at or below 100 is intrinsically ambiguous and must not be guessed.
    """
    numeric: float | None
    try:
        numeric = float(raw) if raw is not None else None
    except (TypeError, ValueError):
        numeric = None

    scale = configured_scale
    if numeric is not None and configured_scale == "unknown" and numeric > 100:
        scale = "half_percent_200"

    normalized: float | None = None
    invalid = False
    if numeric is not None:
        if scale == "percent_100":
            invalid = not 0 <= numeric <= 100
            normalized = numeric if not invalid else None
        elif scale in {"half_percent_200", "conservative_half_percent_200"}:
            invalid = not 0 <= numeric <= 200
            normalized = numeric / 2 if not invalid else None
        elif numeric < 0 or numeric > 200:
            invalid = True

    return {
        "battery_raw": numeric,
        "battery_scale": scale,
        "battery_percent": normalized,
        "low_battery": low_battery is True,
        "battery_invalid": invalid,
    }


def apply_battery_scale_learning(
    devices: list[dict[str, Any]],
    incidents: dict[str, Any],
    config: dict[str, Any],
    now: datetime,
) -> None:
    """Refine ambiguous 0..100/0..200 battery readings without human setup.

    Values above 100 prove a half-percent scale. Otherwise, after the learning
    window, use a conservative half-percent conversion: it can alert early for
    a 0..100 device but cannot mistake a low 0..200 reading for a safe value.
    """
    battery_config = config.get("battery_scales", {})
    learning_days = int(battery_config.get("learning_days", 7))
    minimum_samples = int(battery_config.get("learning_min_samples", 12))
    learning = incidents.setdefault("battery_scale_learning", {})
    for device in devices:
        facts = device.get("facts", {})
        battery = facts.get("battery")
        if not isinstance(battery, dict) or battery.get("battery_raw") is None:
            continue
        device_id = device["device_id"]
        raw = battery["battery_raw"]
        record = learning.setdefault(device_id, {
            "first_observed_at": now_iso(now), "samples": 0,
            "max_raw": raw, "min_raw": raw,
        })
        record["samples"] += 1
        record["last_observed_at"] = now_iso(now)
        record["max_raw"] = max(float(record["max_raw"]), raw)
        record["min_raw"] = min(float(record["min_raw"]), raw)

        scale = battery.get("battery_scale", "unknown")
        confidence = "configured" if scale in {"percent_100", "half_percent_200"} else "learning"
        if raw > 100 or record["max_raw"] > 100:
            scale = "half_percent_200"
            confidence = "confirmed_from_raw_above_100"
        elif scale == "unknown":
            first_seen = parse_time(record["first_observed_at"])
            elapsed_days = (now.astimezone() - first_seen).total_seconds() / 86400 if first_seen else 0
            if record["samples"] >= minimum_samples and elapsed_days >= learning_days:
                scale = "conservative_half_percent_200"
                confidence = "conservative_after_learning_window"

        learned = battery_observation(raw, battery.get("low_battery"), configured_scale=scale)
        learned["battery_scale_confidence"] = confidence
        learned["battery_scale_learning"] = {
            "samples": record["samples"], "max_raw": record["max_raw"],
            "min_raw": record["min_raw"], "first_observed_at": record["first_observed_at"],
        }
        facts["battery"] = learned


def classify_zigbee(raws: Iterable[dict[str, Any]]) -> tuple[str, str]:
    """Return profile and display category for a physical deCONZ device."""
    manufacturers = {
        str(raw.get("manufacturername", "")).casefold() for raw in raws
    }
    models = {str(raw.get("modelid", "")).casefold() for raw in raws}
    types = {str(raw.get("type", "")) for raw in raws}
    if any("danfoss" in manufacturer for manufacturer in manufacturers) or any(model.startswith("etrv") for model in models):
        return "critical_danfoss_valve", "danfoss_valve"
    if "ikea of sweden" in manufacturers and any("parasoll" in model for model in models):
        return "parasoll", "parasoll"
    if "ZHAPresence" in types:
        return "zigbee", "presence_sensor"
    if any("aqara" in manufacturer for manufacturer in manufacturers):
        return "zigbee", "aqara_sensor"
    if "_tze284_xpvamyfz" in manufacturers:
        return "zigbee", "nous_sensor"
    return "zigbee", "zigbee_device"


def validate_measurements(values: dict[str, Any]) -> list[dict[str, str]]:
    """Flag only impossible values; operational ranges remain device-specific."""
    issues: list[dict[str, str]] = []
    ranges = {
        "temperature_c": (-40.0, 100.0),
        "humidity_percent": (0.0, 100.0),
        "battery_percent": (0.0, 100.0),
        "voltage_v": (180.0, 260.0),
        "frequency_hz": (45.0, 55.0),
    }
    for field, value in values.items():
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            issues.append({"field": field, "message": f"{field} is not numeric"})
            continue
        if not math.isfinite(numeric):
            issues.append({"field": field, "message": f"{field} is not finite"})
            continue
        if field in ranges:
            low, high = ranges[field]
            if not low <= numeric <= high:
                issues.append({"field": field, "message": f"{field}={numeric:g} outside {low:g}..{high:g}"})
    return issues


def policy_for(device: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    profile_name = device.get("profile", "infrastructure")
    profile = copy.deepcopy(config.get("profiles", {}).get(profile_name, {}))
    override = config.get("overrides", {}).get(device["device_id"], {})
    profile.update(override.get("policy", {}))
    if "class" in override:
        profile["class"] = override["class"]
    if profile.get("critical_when_heating_on") and (device.get("facts", {}) or {}).get("heating_on") is not True:
        profile["class"] = "revision"
    return profile


def hardware_type_for(device: dict[str, Any]) -> str:
    """Return a short user-facing hardware descriptor for tables and email."""
    explicit = device.get("hardware_type") or (device.get("facts", {}) or {}).get("hardware_type")
    if explicit:
        return str(explicit)
    categories = {
        "tuya_pump": "Tuya smart plug",
        "zigbee_gateway": "deCONZ Zigbee gateway",
        "heatmeter": "Modbus heat meter",
        "shelly": "Shelly device",
        "radiator_temperature": "DS18B20 via Shelly",
        "weather_station": "WS90 weather station",
        "electricity_meter": "HomeWizard Energy P1",
        "gas_meter": "Gas pulse meter",
        "presence_sensor": "Zigbee presence sensor",
        "aqara_sensor": "Aqara Zigbee sensor",
        "nous_sensor": "Nous Zigbee sensor",
        "collector": "Infrastructure collector",
        "log_backed_infrastructure": "Physical-infrastructure reporter",
    }
    return categories.get(str(device.get("category", "")), str(device.get("category", "unknown")).replace("_", " "))


def issue(
    device: dict[str, Any],
    kind: str,
    message: str,
    policy: dict[str, Any],
    *,
    severity: str | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "incident_id": f"{device['device_id']}:{kind}",
        "device_id": device["device_id"],
        "device_name": device.get("name", device["device_id"]),
        "category": device.get("category", "unknown"),
        "hardware_type": hardware_type_for(device),
        "kind": kind,
        "class": severity or policy.get("class", "revision"),
        "message": message,
        "open_after_runs": int(policy.get("open_after_runs", 1)),
        "evidence": evidence or {},
        "dependencies": list(device.get("dependencies") or []),
    }


def candidates_for(device: dict[str, Any], config: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
    """Turn one normalized read-only observation into candidate conditions."""
    policy = policy_for(device, config)
    facts = device.get("facts", {})
    candidates: list[dict[str, Any]] = []
    temporary_battery = facts.get("temporary_nonrechargeable_battery")
    if temporary_battery:
        candidate = issue(
            device,
            "temporary_battery",
            "Temporary non-rechargeable battery installed; restore the rechargeable battery after charging",
            policy,
            severity="revision",
            evidence=temporary_battery if isinstance(temporary_battery, dict) else {},
        )
        candidate["open_after_runs"] = 1
        candidate["dependencies"] = []
        candidates.append(candidate)
    error = facts.get("collection_error")
    if error:
        candidates.append(issue(device, "unreachable", str(error), policy))
        return candidates

    if facts.get("reachable") is False:
        candidates.append(issue(device, "unreachable", "Device reports unreachable", policy))
    if facts.get("service_active") is False:
        candidates.append(issue(device, "service_down", "The required continuous service is not active", policy))

    stale_after = policy.get("stale_after_minutes")
    last_seen = facts.get("last_seen_at")
    if stale_after is not None and last_seen:
        age = age_minutes(last_seen, now)
        if age is not None and age > float(stale_after):
            candidates.append(issue(
                device, "stale", f"Last seen {age:.0f} minutes ago", policy,
                evidence={"last_seen_at": last_seen, "age_minutes": round(age, 1)},
            ))

    battery = facts.get("battery", {})
    if battery.get("battery_invalid"):
        candidates.append(issue(device, "invalid_battery", "Battery value is outside its configured raw range", policy, evidence=battery))
    if battery.get("low_battery"):
        candidates.append(issue(device, "low_battery", "Device reports low battery", policy, severity=("critical" if device.get("profile") == "parasoll" else None), evidence=battery))
    battery_percent = battery.get("battery_percent")
    critical_battery = policy.get("battery_critical_percent")
    warning_battery = policy.get("battery_warning_percent")
    if battery_percent is not None:
        if critical_battery is not None and battery_percent <= float(critical_battery):
            candidates.append(issue(device, "low_battery", f"Battery is {battery_percent:g}%", policy, severity="critical" if device.get("profile") == "parasoll" else None, evidence=battery))
        elif warning_battery is not None and battery_percent <= float(warning_battery):
            candidates.append(issue(device, "low_battery", f"Battery is {battery_percent:g}%", policy, evidence=battery))

    event_after = policy.get("event_after_minutes")
    last_event = facts.get("last_event_at")
    if event_after is not None:
        event_age = age_minutes(last_event, now)
        if event_age is None or event_age > float(event_after):
            description = "No expected event has ever been recorded" if event_age is None else f"No expected event for {event_age:.0f} minutes"
            candidates.append(issue(device, "event_stalled", description, policy, evidence={"last_event_at": last_event, "age_minutes": event_age}))

    for measurement_issue in validate_measurements(facts.get("measurements", {})):
        candidates.append(issue(device, f"invalid_{measurement_issue['field']}", measurement_issue["message"], policy))
    return candidates


def initial_incident_state() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "active": {},
        "pending": {},
        "known_devices": {},
        "battery_scale_learning": {},
        "digest_sent_for": None,
    }


def update_incidents(
    previous: dict[str, Any],
    devices: list[dict[str, Any]],
    config: dict[str, Any],
    now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """Advance persistent incident state and return opened/solved transitions."""
    state = copy.deepcopy(previous or initial_incident_state())
    state.setdefault("active", {})
    state.setdefault("pending", {})
    state.setdefault("known_devices", {})
    active = state["active"]
    pending = state["pending"]
    current_candidates: dict[str, dict[str, Any]] = {}
    current_device_ids = {
        device["device_id"] for device in devices
        if not (device.get("facts", {}) or {}).get("manual_only")
    }

    for device in devices:
        if not (device.get("facts", {}) or {}).get("manual_only"):
            state["known_devices"][device["device_id"]] = {
                key: copy.deepcopy(device.get(key))
                for key in ("device_id", "name", "category", "profile", "hardware_type", "dependencies")
            }
        for candidate in candidates_for(device, config, now):
            current_candidates[candidate["incident_id"]] = candidate

    # A known device absent from a successful collection is a disappearance.
    gateway_down = {
        candidate["device_id"] for candidate in current_candidates.values()
        if candidate["kind"] == "unreachable"
    }
    for device_id, known in state["known_devices"].items():
        if device_id in current_device_ids:
            continue
        if set(known.get("dependencies") or []).intersection(gateway_down):
            continue
        policy = policy_for(known, config)
        missing = issue(known, "missing", "Known device was absent from the latest inventory", policy)
        current_candidates[missing["incident_id"]] = missing

    opened: list[dict[str, Any]] = []
    for incident_id, candidate in current_candidates.items():
        if incident_id in active:
            active[incident_id].update({
                "last_seen_at": now_iso(now),
                "message": candidate["message"],
                "evidence": candidate["evidence"],
                "class": candidate["class"],
                "hardware_type": candidate["hardware_type"],
            })
            continue
        tracker = pending.get(incident_id, {"runs": 0, "first_seen_at": now_iso(now)})
        tracker["runs"] += 1
        tracker["last_seen_at"] = now_iso(now)
        tracker["candidate"] = candidate
        if tracker["runs"] >= candidate["open_after_runs"]:
            incident = {
                **candidate,
                "status": "active",
                "first_seen_at": tracker["first_seen_at"],
                "last_seen_at": now_iso(now),
                "opened_at": now_iso(now),
                "immediate_notification_sent_at": None,
            }
            active[incident_id] = incident
            pending.pop(incident_id, None)
            opened.append(copy.deepcopy(incident))
        else:
            pending[incident_id] = tracker

    solved: list[dict[str, Any]] = []
    for incident_id in list(pending):
        if incident_id not in current_candidates:
            pending.pop(incident_id, None)
    for incident_id, incident in list(active.items()):
        if incident_id in current_candidates:
            continue
        if set(incident.get("dependencies") or []).intersection(gateway_down):
            continue
        solved_incident = copy.deepcopy(incident)
        solved_incident.update({"status": "solved", "solved_at": now_iso(now)})
        solved.append(solved_incident)
        active.pop(incident_id, None)

    state["last_updated_at"] = now_iso(now)
    return state, opened, solved


def snapshot(devices: list[dict[str, Any]], incidents: dict[str, Any], now: datetime) -> dict[str, Any]:
    active_by_device: dict[str, list[dict[str, Any]]] = {}
    for incident in incidents.get("active", {}).values():
        active_by_device.setdefault(incident["device_id"], []).append(incident)
    rows = []
    for device in sorted(devices, key=lambda item: (item.get("category", ""), item.get("name", ""))):
        rows.append({
            "device_id": device["device_id"],
            "name": device.get("name", device["device_id"]),
            "category": device.get("category"),
            "hardware_type": hardware_type_for(device),
            "profile": device.get("profile"),
            "facts": device.get("facts", {}),
            "active_incidents": active_by_device.get(device["device_id"], []),
            "status": "attention" if device["device_id"] in active_by_device else "ok",
        })
    return {
        "schema_version": 1,
        "generated_at": now_iso(now),
        "summary": {
            "devices_observed": len(devices),
            "active_incidents": len(incidents.get("active", {})),
            "critical_incidents": sum(1 for incident in incidents.get("active", {}).values() if incident.get("class") == "critical"),
            "revision_incidents": sum(1 for incident in incidents.get("active", {}).values() if incident.get("class") != "critical"),
        },
        "devices": rows,
    }


def render_table(incidents: dict[str, Any], title: str = "ACTIVE DEVICE INCIDENTS") -> str:
    rows = sorted(incidents.get("active", {}).values(), key=lambda item: (item.get("class") != "critical", item.get("name", ""), item.get("kind", "")))
    lines = [title]
    if not rows:
        return title + "\nNo active incidents."
    lines.append("CLASS     DEVICE                         TYPE                           CONDITION        DETAILS")
    lines.append("--------- ------------------------------ ------------------------------ ---------------- ------------------------------")
    for entry in rows:
        lines.append(
            f"{entry.get('class', 'revision').upper():9} "
            f"{entry.get('device_name', entry['device_id'])[:30]:30} "
            f"{entry.get('hardware_type', entry.get('category', 'unknown'))[:30]:30} "
            f"{entry.get('kind', '')[:16]:16} "
            f"{entry.get('message', '')}"
        )
    return "\n".join(lines)


def render_grouped_report(incidents: dict[str, Any], title: str = "ACTIVE DEVICE INCIDENTS") -> str:
    """Render email-friendly device blocks while retaining every incident."""
    entries = list(incidents.get("active", {}).values())
    if not entries:
        return title + "\nNo active incidents."

    grouped: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        grouped.setdefault(str(entry.get("device_id", entry.get("device_name", "unknown"))), []).append(entry)

    def group_key(group: list[dict[str, Any]]) -> tuple[bool, str]:
        critical = any(entry.get("class") == "critical" for entry in group)
        name = str(group[0].get("device_name", group[0].get("device_id", "unknown")))
        return (not critical, name.casefold())

    lines = [title]
    for group in sorted(grouped.values(), key=group_key):
        ordered = sorted(group, key=lambda entry: (entry.get("class") != "critical", str(entry.get("kind", ""))))
        first = ordered[0]
        severity = "CRITICAL" if any(entry.get("class") == "critical" for entry in ordered) else "REVISION"
        name = first.get("device_name", first.get("device_id", "unknown"))
        hardware_type = first.get("hardware_type", first.get("category", "unknown"))
        lines.extend(["", f"{severity} — {name}", f"Type: {hardware_type}", "Issues:"])
        for entry in ordered:
            kind = str(entry.get("kind", "issue")).replace("_", " ").capitalize()
            lines.append(f"  - {kind}: {entry.get('message', '')}")
    return "\n".join(lines)


def digest_due(state: dict[str, Any], config: dict[str, Any], now: datetime) -> bool:
    """Return whether the configured physical-watchdog digest is due today."""
    digest = config.get("digest", config.get("weekly_digest", {}))
    frequency = digest.get("frequency", "weekly")
    if frequency not in {"daily", "weekly"}:
        return False
    if frequency == "weekly" and now.weekday() != int(digest.get("weekday", 2)):
        return False
    if now.hour != int(digest.get("hour", 8)):
        return False
    if now.minute >= int(digest.get("minute_window", 15)):
        return False
    return state.get("digest_sent_for", state.get("weekly_digest_sent_for")) != now.date().isoformat()


def build_digest(incidents: dict[str, Any], now: datetime, frequency: str) -> str:
    return f"Kazanfutes {frequency} physical-infrastructure to-do list — {now.date().isoformat()}\n\n{render_grouped_report(incidents)}"


def ping_healthchecks(project_root: str, config: dict[str, Any]) -> bool | None:
    """Ping the optional externally hosted dead-man check after a good run."""
    settings = config.get("healthchecks", {})
    relative_path = settings.get("secret_relative_path")
    if not relative_path:
        return None
    path = os.path.join(project_root, relative_path)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            url = handle.read().strip()
    except OSError:
        return None
    if not url:
        return None
    try:
        response = requests.get(url, timeout=float(settings.get("timeout_seconds", 10)))
        response.raise_for_status()
        return True
    except requests.RequestException:
        return False
