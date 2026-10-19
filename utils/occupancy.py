"""Pure presence/motion normalization and occupancy evaluation.

Presence is a level; motion is evidence accumulated over a window. A recent
poll is neither a new motion event nor evidence that a device is alive.
Versioned observations carry source identity so changing a room's sensor does
not splice two devices' histories together. No devices or files are mutated.
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone
from typing import Any

SCHEMA_VERSION = 2
SAMPLE_MAX_AGE_MINUTES = 5
CONTACT_MAX_AGE_MINUTES = 120
RECENT_CONTACT_OVERRIDE_MINUTES = 5
PROJECT_TIME_FORMAT = "%Y-%m-%d-%H-%M-%S"


def sensor_kind(manufacturer: str, model: str) -> str:
    """Classify deployed hardware, never a friendly name or ZHAPresence type."""
    manufacturer, model = manufacturer.casefold(), model.casefold()
    if manufacturer == "aqara" and model == "lumi.sensor_occupy.agl8":
        return "presence"
    if manufacturer == "ewelink" and model in {"ms01", "mso1", "66666", "snzb-03", "snzb-03p"}:
        return "motion"
    return "unknown"


def parse_timestamp(value: Any, local_tz, *, source_utc: bool = False) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        try:
            result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            result = datetime.strptime(value, PROJECT_TIME_FORMAT)
        if result.tzinfo is None:
            result = result.replace(tzinfo=timezone.utc if source_utc else local_tz)
        return result
    except (ValueError, TypeError, OverflowError):
        return None


def observation_health(row: dict, at: datetime) -> tuple[bool, str | None]:
    """Check receipt freshness and radio health separately from state-change age.

    Two hours is a conservative communication deadline for the deployed sensor
    set. It changes occupancy confidence only, not watchdog alert thresholds.
    A genuinely recent radio reception outweighs a cached false reachable flag.
    """
    if row.get("signal_type") not in {"motion", "presence"}:
        return False, "unsupported_sensor_model"
    if row.get("enabled") is False:
        return False, "sensor_disabled"
    if not row.get("source_id") or not row.get("source_name"):
        return False, "missing_source_identity"
    observed = parse_timestamp(row.get("observed_at"), at.tzinfo)
    updated = parse_timestamp(row.get("source_updated_at"), at.tzinfo)
    contact = parse_timestamp(row.get("last_seen_at"), at.tzinfo) or updated
    announced = parse_timestamp(row.get("last_announced_at"), at.tzinfo)
    if not observed or not updated or not contact or not isinstance(row.get("state"), bool):
        return False, "missing_or_invalid_evidence"
    for stamp in (observed, updated, contact, announced):
        if stamp and stamp > at + timedelta(seconds=5):
            return False, "future_timestamp"
    if observed > at:
        return False, "not_yet_observed"
    if (at - observed).total_seconds() > SAMPLE_MAX_AGE_MINUTES * 60:
        return False, "logger_stale"
    if announced and updated < announced:
        return False, "awaiting_post_join_state"
    contact_age = max(0, (at - contact).total_seconds() / 60)
    if contact_age > CONTACT_MAX_AGE_MINUTES:
        return False, "device_contact_stale"
    if row.get("reachable") is not True and contact_age > RECENT_CONTACT_OVERRIDE_MINUTES:
        return False, "device_unreachable"
    return True, None


def normalize_presence(raw: dict, now: datetime, *, local_tz=None) -> dict:
    """Preserve real device timestamps, plus a distinct poll/receipt timestamp."""
    local_tz = local_tz or now.tzinfo
    state, config = raw.get("state") or {}, raw.get("config") or {}
    manufacturer, model = str(raw.get("manufacturername") or ""), str(raw.get("modelid") or "")
    updated = parse_timestamp(state.get("lastupdated"), local_tz, source_utc=True)
    contact = parse_timestamp(raw.get("lastseen"), local_tz, source_utc=True)
    announced = parse_timestamp(raw.get("lastannounced"), local_tz, source_utc=True)
    row = {
        "schema_version": SCHEMA_VERSION,
        "source_name": str(raw.get("name") or ""),
        "source_id": str(raw.get("uniqueid") or "").split("-")[0],
        "manufacturer": manufacturer,
        "model": model,
        "signal_type": sensor_kind(manufacturer, model),
        "enabled": config.get("on", True),
        "reachable": config.get("reachable") if isinstance(config.get("reachable"), bool) else None,
        "state": state.get("presence") if isinstance(state.get("presence"), bool) else None,
        "last_updated": updated.astimezone(local_tz).strftime(PROJECT_TIME_FORMAT) if updated else None,
        "source_updated_at": updated.isoformat() if updated else None,
        "last_seen_at": contact.isoformat() if contact else None,
        "last_announced_at": announced.isoformat() if announced else None,
        "observed_at": now.isoformat(timespec="seconds"),
    }
    row["usable"], row["unavailable_reason"] = observation_health(row, now)
    return row


def known_presence_fraction(values) -> float | None:
    """Missing observations must not silently become negative training samples."""
    known = [value for value in values if isinstance(value, bool)]
    return sum(known) / len(known) if known else None


def calculate_occupancy(
    logs: list[dict], rooms: dict, targets: list[datetime], *,
    presence_window: float, minimum_separation: float, allow_legacy: bool = False,
) -> list[dict[str, bool | None]]:
    """Evaluate causally, returning one tri-state room mapping per target.

    Live evaluation ignores unidentified legacy observations: they cannot prove
    which sensor produced a room's data, and Pres1's old records used synthetic
    timestamps. Historical analysis keeps their old motion-window semantics.
    Motion evidence naturally warms up over the existing separation interval
    after deployment. Presence-level sensors need just one valid observation.
    """
    if not targets:
        return []
    local_tz = targets[0].tzinfo
    observations: dict[str, list[tuple[datetime, int, dict]]] = {str(room): [] for room in rooms}
    for order, entry in enumerate(logs):
        stamp = parse_timestamp(entry.get("timestamp"), local_tz)
        if stamp is None or not isinstance(entry.get("states"), dict):
            continue
        for room, row in entry["states"].items():
            room = str(room)
            if room not in observations or not isinstance(row, dict):
                continue
            typed = row.get("schema_version") == SCHEMA_VERSION
            if not typed and not allow_legacy:
                continue
            if typed and not allow_legacy and row.get("source_name") != rooms[room].get("pres"):
                continue
            received = parse_timestamp(row.get("observed_at"), local_tz) if typed else stamp
            # Never apply information before it was actually observed.
            if received is None:
                continue
            observations[room].append((max(stamp, received), order, row))
    for values in observations.values():
        values.sort(key=lambda item: (item[0], item[1]))
    times = {room: [item[0] for item in values] for room, values in observations.items()}
    results = []
    for target in targets:
        result = {}
        window_start = target - timedelta(minutes=presence_window)
        for room, values in observations.items():
            end = bisect_right(times[room], target)
            if not end:
                result[room] = None
                continue
            latest = values[end - 1][2]
            typed = latest.get("schema_version") == SCHEMA_VERSION
            if typed:
                healthy, _ = observation_health(latest, target)
                if not healthy:
                    result[room] = None
                    continue
                if latest.get("signal_type") == "presence":
                    result[room] = latest["state"]
                    continue
                updated = parse_timestamp(latest.get("source_updated_at"), local_tz)
                if latest.get("state") is True and updated and updated < window_start:
                    # A stuck positive PIR level isn't a fresh motion event or
                    # trustworthy confirmation of vacancy.
                    result[room] = None
                    continue
                identity = (latest.get("source_name"), latest.get("source_id"))
            else:
                identity = None
            # Only the window's observations matter for collecting new events.
            start = bisect_right(times[room], window_start - timedelta(microseconds=1))
            events = set()
            for _, _, row in values[start:end]:
                if typed:
                    if row.get("schema_version") != SCHEMA_VERSION or row.get("signal_type") != "motion":
                        continue
                    if (row.get("source_name"), row.get("source_id")) != identity:
                        continue
                    if not row.get("usable"):
                        continue
                    event = parse_timestamp(row.get("source_updated_at"), local_tz)
                else:
                    if not row.get("reachable"):
                        continue
                    event = parse_timestamp(row.get("last_updated"), local_tz)
                if row.get("state") is True and event and window_start <= event <= target:
                    events.add(event)
            ordered = sorted(events)
            result[room] = bool(len(ordered) >= 2 and (ordered[-1] - ordered[0]).total_seconds() >= minimum_separation * 60)
        results.append(result)
    return results
