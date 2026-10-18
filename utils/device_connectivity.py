"""Evidence-based physical connectivity episodes; no device/network writes.

The caller persists these trackers under the watchdog's existing shared lock.
Wall-clock holds survive restarts and are not advanced by boiler-only runs.
"""
from __future__ import annotations

import copy
from datetime import datetime

KINDS = {"unreachable", "stale", "missing", "connectivity"}


def minutes(value, now):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            from datetime import timezone
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, (now - parsed).total_seconds() / 60)
    except (TypeError, ValueError):
        return None


def stamp(now):
    return now.isoformat(timespec="seconds")


def migrate(state, devices, now):
    """Fold old conditions/alias IDs without fabricating transitions or emails."""
    known = state.setdefault("known_devices", {})
    for item in known.values():
        if item.get("category") == "incomplete_zigbee_device":
            item["dependencies"] = sorted(set(item.get("dependencies") or []) | {"collector:deconz_device_inventory"})
    canonical = {}
    for device in list(known.values()) + devices:
        identifier = device.get("device_id", "")
        if identifier.startswith("shelly:") and identifier.count(":") >= 6:
            canonical[device.get("name")] = identifier
    aliases = {
        identifier: canonical[item.get("name")]
        for identifier, item in known.items()
        if identifier.startswith("shelly:") and identifier.count(":") < 6
        and item.get("name") in canonical
    }

    def converted(entry):
        result = copy.deepcopy(entry)
        old_device = result.get("device_id", "")
        result["device_id"] = aliases.get(old_device, old_device)
        if result.get("kind") in KINDS:
            if result.get("kind") != "connectivity":
                result.setdefault("legacy_conditions", []).append(result["kind"])
            result["kind"] = "connectivity"
        result["incident_id"] = f"{result['device_id']}:{result.get('kind', '')}"
        return result

    for key in ("active", "pending_resolution_notifications"):
        merged = {}
        for entry in state.get(key, {}).values():
            item = converted(entry)
            previous = merged.get(item["incident_id"])
            if previous:
                # Preserve any successful delivery marker and the oldest opening.
                for field in ("opened_at", "first_seen_at", "immediate_notification_sent_at"):
                    values = [v for v in (previous.get(field), item.get(field)) if v]
                    if values:
                        item[field] = min(values)
                item["legacy_conditions"] = sorted(set(previous.get("legacy_conditions", []) + item.get("legacy_conditions", [])))
            merged[item["incident_id"]] = item
        state[key] = merged
    pending = {}
    for tracker in state.get("pending", {}).values():
        item = copy.deepcopy(tracker)
        item["candidate"] = converted(item.get("candidate", {}))
        pending[item["candidate"]["incident_id"]] = item
    state["pending"] = pending
    inventory = state.get("digest_last_incident_inventory")
    if inventory is not None:
        state["digest_last_incident_inventory"] = list({item["incident_id"]: item for item in map(converted, inventory)}.values())
    for old_id, new_id in aliases.items():
        entry = known.pop(old_id)
        entry["device_id"] = new_id
        known.setdefault(new_id, entry)
    state["connectivity_schema_version"] = 2


def evaluate(state, device, policy, now, *, absent=False, blocked=False):
    """Return (candidate details or None, may resolve). Also expose CLI facts."""
    device_id = device["device_id"]
    facts = device.setdefault("facts", {})
    tracker = state.setdefault("connectivity_tracking", {}).setdefault(device_id, {})
    tracker.setdefault("observing_since", stamp(now))
    active = state.get("active", {}).get(f"{device_id}:connectivity")
    last = facts.get("last_seen_at")
    age = minutes(last, now)
    silence_age = age if age is not None else minutes(tracker["observing_since"], now)
    zigbee = device_id.startswith("zigbee:")
    trv = device.get("profile") == "critical_danfoss_valve"
    silence = policy.get("connectivity_silence_minutes", policy.get("stale_after_minutes"))
    # Quiet mains lights/routers have no guaranteed reporting cadence.
    quiet = zigbee and facts.get("quiet_mains") is True
    if quiet:
        silence = None
    error = facts.get("collection_error")
    negative = absent or bool(error) or facts.get("reachable") is False
    recent = age is not None and age <= 5
    # A radio reception outweighs a stale deCONZ flag, but not a failed HTTP read.
    if zigbee and recent and not absent and not error:
        negative = False
    if negative:
        tracker.setdefault("negative_since", stamp(now))
    else:
        tracker.pop("negative_since", None)
    negative_age = minutes(tracker.get("negative_since"), now) or 0
    reasons = []
    confirmed = False
    if blocked:
        facts["connectivity_status"] = "unknown (dependency unavailable)"
        tracker.pop("recovering_since", None)
        tracker.pop("recovery_reports", None)
        return None, False
    if absent:
        reasons.append("Absent from a successful inventory")
        confirmed = negative_age >= float(policy.get("missing_confirm_minutes", 15))
    elif error:
        reasons.append(f"Read failed: {error}")
        confirmed = negative_age >= float(policy.get("connectivity_confirm_minutes", 10))
    elif zigbee:
        if facts.get("reachable") is False:
            reasons.append("deCONZ reachability flag is false")
        if silence is not None and silence_age is not None and silence_age >= float(silence):
            reasons.append(f"No radio contact for {silence_age:.0f} minutes (limit {silence})")
            confirmed = True
        if trv and negative and silence_age is not None and silence_age >= float(policy.get("unreachable_min_silence_minutes", 45)):
            confirmed = confirmed or negative_age >= float(policy.get("connectivity_confirm_minutes", 15))
        # Other sleepy devices' flags are advisory until their silence deadline.
        # A quiet mains node needs an actual failed read/probe, not this flag alone.
    else:
        if negative:
            reasons.append("Device reports unreachable")
            confirmed = negative_age >= float(policy.get("connectivity_confirm_minutes", 10))
        if silence is not None and silence_age is not None and silence_age >= float(silence):
            reasons.append(f"No fresh data for {silence_age:.0f} minutes (limit {silence})")
            confirmed = True

    if confirmed:
        tracker["last_fault_contact"] = last or tracker.get("last_contact")
        tracker["last_fault_at"] = stamp(now)
        tracker.pop("recovering_since", None)
        tracker.pop("recovery_reports", None)
        facts["connectivity_status"] = "failed"
        return {"message": "; ".join(reasons), "evidence": {"reasons": reasons, "last_seen_at": last, "age_minutes": age}}, False

    if active:
        # Never turn a cached true flag into a recovery. Zigbee must receive a
        # packet after the last failed observation. Successful direct reads are
        # fresh evidence even when that device supplies no last-seen timestamp.
        fault_at = tracker.get("last_fault_at") or active.get("opened_at")
        contact_after_fault = last and minutes(last, now) is not None and minutes(fault_at, now) is not None and minutes(last, now) < minutes(fault_at, now)
        healthy = not absent and not error and (bool(contact_after_fault) if zigbee else facts.get("reachable") is True)
        if not healthy or negative:
            tracker.pop("recovering_since", None)
            tracker.pop("recovery_reports", None)
            facts["connectivity_status"] = "suspected" if reasons else "awaiting fresh contact"
            return None, False
        tracker.setdefault("recovering_since", stamp(now))
        reports = tracker.setdefault("recovery_reports", [])
        evidence_time = last if zigbee else stamp(now)
        if evidence_time not in reports:
            reports.append(evidence_time)
            del reports[:-3]
        held = (minutes(tracker["recovering_since"], now) or 0) >= float(policy.get("recovery_confirm_minutes", 10))
        enough = len(reports) >= (2 if trv else 1)
        facts["connectivity_status"] = "recovering"
        if held and enough:
            tracker.pop("recovering_since", None)
            tracker.pop("recovery_reports", None)
            facts["connectivity_status"] = "ok"
            return None, True
        return None, False
    tracker["last_contact"] = last
    facts["connectivity_status"] = "suspected" if reasons else "ok"
    return None, True
