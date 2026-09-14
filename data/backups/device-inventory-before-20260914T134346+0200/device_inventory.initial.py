"""Forward-only physical-device inventory maintained by the watchdog."""

from __future__ import annotations

import copy
import json
from typing import Any, Iterable


INVENTORY_RELATIVE_PATH = "system/device_inventory.json"
SCHEMA_VERSION = 1


def normalize_mac(value: Any) -> str | None:
    """Return a normalized 48-bit or 64-bit colon-separated MAC/IEEE address."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    compact = "".join(character for character in text if character in "0123456789abcdef")
    if len(compact) not in {12, 16}:
        return None
    return ":".join(compact[index:index + 2] for index in range(0, len(compact), 2))


def initial_device_inventory() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": None,
        "devices": {},
    }


def _unique_strings(values: Iterable[Any]) -> list[str]:
    return sorted({str(value) for value in values if value is not None and str(value).strip()})


def _stable_endpoints(values: Iterable[Any]) -> list[dict[str, Any]]:
    endpoints: dict[str, dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            continue
        endpoint = {str(key): item for key, item in value.items() if item is not None}
        endpoints[json.dumps(endpoint, sort_keys=True, separators=(",", ":"))] = endpoint
    return [endpoints[key] for key in sorted(endpoints)]


def _current_from_device(device: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    inventory = device.get("inventory")
    if not isinstance(inventory, dict):
        return None
    mac = normalize_mac(inventory.get("mac"))
    if mac is None:
        return None
    facts = device.get("facts") or {}
    display_name = str(device.get("name") or f"Device {mac}")
    names = _unique_strings(list(inventory.get("names") or []) + [display_name])
    current = {
        "display_name": display_name,
        "names": names,
        "sources": _unique_strings(inventory.get("sources") or [inventory.get("source")]),
        "manufacturer_names": _unique_strings(inventory.get("manufacturer_names") or []),
        "model_ids": _unique_strings(inventory.get("model_ids") or []),
        "product_ids": _unique_strings(inventory.get("product_ids") or []),
        "software_versions": _unique_strings(inventory.get("software_versions") or []),
        "device_types": _unique_strings(inventory.get("device_types") or []),
        "roles": _unique_strings(inventory.get("roles") or [inventory.get("role")]),
        "endpoints": _stable_endpoints(inventory.get("endpoints") or []),
        "watchdog_device_ids": _unique_strings([device.get("device_id")]),
        "reachable": facts.get("reachable"),
        "last_seen_at": facts.get("last_seen_at"),
    }
    return mac, current


def _merge_current(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(left)
    for field in (
        "names", "sources", "manufacturer_names", "model_ids", "product_ids",
        "software_versions", "device_types", "roles", "watchdog_device_ids",
    ):
        merged[field] = _unique_strings(list(left.get(field) or []) + list(right.get(field) or []))
    merged["endpoints"] = _stable_endpoints(list(left.get("endpoints") or []) + list(right.get("endpoints") or []))
    if str(left.get("display_name", "")).startswith("Unidentified "):
        merged["display_name"] = right.get("display_name")
    reachability = [value for value in (left.get("reachable"), right.get("reachable")) if isinstance(value, bool)]
    merged["reachable"] = True if any(reachability) else (False if reachability else None)
    last_seen = [str(value) for value in (left.get("last_seen_at"), right.get("last_seen_at")) if value]
    merged["last_seen_at"] = max(last_seen) if last_seen else None
    return merged


def _observations_by_mac(devices: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    observations: dict[str, dict[str, Any]] = {}
    for device in devices:
        normalized = _current_from_device(device)
        if normalized is None:
            continue
        mac, current = normalized
        observations[mac] = _merge_current(observations[mac], current) if mac in observations else current
    return observations


def _event(timestamp: str, event_type: str, **details: Any) -> dict[str, Any]:
    event = {"timestamp": timestamp, "type": event_type}
    if details:
        event["details"] = details
    return event


def _incident_summary(incident: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(incident.get(key))
        for key in (
            "incident_id", "kind", "class", "message", "status", "opened_at",
            "solved_at", "first_seen_at", "last_seen_at", "evidence",
        )
        if incident.get(key) is not None
    }


def _device_id_index(records: dict[str, dict[str, Any]]) -> dict[str, str]:
    index: dict[str, str] = {}
    for mac, record in records.items():
        for device_id in (record.get("current") or {}).get("watchdog_device_ids", []):
            index[str(device_id)] = mac
    return index


def _record_incident_opened(record: dict[str, Any], incident: dict[str, Any], timestamp: str) -> None:
    summary = _incident_summary(incident)
    summary["status"] = "active"
    summary.setdefault("opened_at", timestamp)
    record.setdefault("incidents", []).append(summary)
    record.setdefault("events", []).append(_event(
        summary["opened_at"], "incident_opened",
        incident_id=summary.get("incident_id"), kind=summary.get("kind"),
        severity=summary.get("class"), message=summary.get("message"),
    ))


def _record_incident_solved(record: dict[str, Any], incident: dict[str, Any], timestamp: str) -> None:
    incident_id = incident.get("incident_id")
    lifecycle = next((
        item for item in reversed(record.setdefault("incidents", []))
        if item.get("incident_id") == incident_id and item.get("status") == "active"
    ), None)
    if lifecycle is None:
        lifecycle = _incident_summary(incident)
        record["incidents"].append(lifecycle)
    lifecycle.update(_incident_summary(incident))
    lifecycle["status"] = "solved"
    lifecycle.setdefault("solved_at", timestamp)
    record.setdefault("events", []).append(_event(
        lifecycle["solved_at"], "incident_solved",
        incident_id=incident_id, kind=lifecycle.get("kind"), message=lifecycle.get("message"),
    ))


def evolve_device_inventory(
    previous: dict[str, Any] | None,
    devices: Iterable[dict[str, Any]],
    active_incidents: Iterable[dict[str, Any]],
    opened_incidents: Iterable[dict[str, Any]],
    solved_incidents: Iterable[dict[str, Any]],
    timestamp: str,
    *,
    successful_sources: set[str],
) -> dict[str, Any]:
    """Advance the durable inventory by one watchdog observation cycle."""
    state = copy.deepcopy(previous) if isinstance(previous, dict) else initial_device_inventory()
    if not isinstance(state.get("devices"), dict):
        state = initial_device_inventory()
    state["schema_version"] = SCHEMA_VERSION
    records: dict[str, dict[str, Any]] = state["devices"]
    observations = _observations_by_mac(devices)

    for mac, current in observations.items():
        record = records.get(mac)
        if record is None:
            record = {
                "mac": mac,
                "first_observed_at": timestamp,
                "last_observed_at": timestamp,
                "present": True,
                "current": current,
                "name_history": [{
                    "display_name": current["display_name"],
                    "names": current["names"],
                    "first_observed_at": timestamp,
                    "last_observed_at": timestamp,
                }],
                "incidents": [],
                "events": [_event(
                    timestamp, "discovered", display_name=current["display_name"],
                    sources=current["sources"],
                )],
            }
            records[mac] = record
            continue

        old_current = record.get("current") or {}
        if record.get("present") is False:
            record.setdefault("events", []).append(_event(timestamp, "reappeared"))
        old_names = {
            "display_name": old_current.get("display_name"),
            "names": old_current.get("names") or [],
        }
        new_names = {"display_name": current["display_name"], "names": current["names"]}
        if old_names != new_names:
            record.setdefault("events", []).append(_event(
                timestamp, "name_changed", before=old_names, after=new_names,
            ))
            if record.setdefault("name_history", []):
                record["name_history"][-1]["last_observed_at"] = timestamp
            record["name_history"].append({
                **new_names,
                "first_observed_at": timestamp,
                "last_observed_at": timestamp,
            })
        elif record.setdefault("name_history", []):
            record["name_history"][-1]["last_observed_at"] = timestamp

        identity_fields = (
            "sources", "manufacturer_names", "model_ids", "product_ids",
            "software_versions", "device_types", "roles",
        )
        identity_changes = {
            field: {"before": old_current.get(field) or [], "after": current.get(field) or []}
            for field in identity_fields
            if (old_current.get(field) or []) != (current.get(field) or [])
        }
        if identity_changes:
            record.setdefault("events", []).append(_event(timestamp, "identity_changed", changes=identity_changes))
        if (old_current.get("endpoints") or []) != current["endpoints"]:
            record.setdefault("events", []).append(_event(
                timestamp, "endpoints_changed",
                before=old_current.get("endpoints") or [], after=current["endpoints"],
            ))
        record["current"] = current
        record["present"] = True
        record["last_observed_at"] = timestamp

    for mac, record in records.items():
        if mac in observations or record.get("present") is False:
            continue
        record_sources = set((record.get("current") or {}).get("sources") or [])
        if record_sources.intersection(successful_sources):
            record["present"] = False
            record.setdefault("events", []).append(_event(timestamp, "disappeared"))

    id_to_mac = _device_id_index(records)
    active_by_mac: dict[str, list[dict[str, Any]]] = {}
    for incident in active_incidents:
        mac = id_to_mac.get(str(incident.get("device_id")))
        if mac:
            active_by_mac.setdefault(mac, []).append(_incident_summary(incident))
    for mac, record in records.items():
        record.setdefault("current", {})["active_incidents"] = sorted(
            active_by_mac.get(mac, []), key=lambda item: str(item.get("incident_id", "")),
        )

    for incident in opened_incidents:
        mac = id_to_mac.get(str(incident.get("device_id")))
        if mac:
            _record_incident_opened(records[mac], incident, timestamp)
    for incident in solved_incidents:
        mac = id_to_mac.get(str(incident.get("device_id")))
        if mac:
            _record_incident_solved(records[mac], incident, timestamp)

    state["generated_at"] = timestamp
    state["devices"] = {mac: records[mac] for mac in sorted(records)}
    return state
