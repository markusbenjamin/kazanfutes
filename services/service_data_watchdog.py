"""Monitor managed services and declared data streams without recovering them."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from utils.project import get_project_root, notify_admin
from utils.device_watchdog import (
    append_ndjson, atomic_write_json, last_ndjson_record, now_iso, parse_time, ping_healthchecks, read_json,
)


CONFIG_PATH = "config/service_data_watchdog.json"
UNIT_LIST_PATH = "services/services_and_timers.list"
STATE_PATH = "system/service_data_watchdog_state.json"
INCIDENTS_PATH = "system/service_data_watchdog_incidents.json"
SOLVED_PATH = "data/logs/service_data_watchdog/solved_incidents.jsonl"


def unit_list(root: Path) -> list[str]:
    path = root / UNIT_LIST_PATH
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")]


def service_for_timer(unit: str, units: list[str]) -> str | None:
    candidate = unit.removesuffix(".timer") + ".service"
    return candidate if candidate in units else None


def timer_for_service(unit: str, units: list[str]) -> str | None:
    candidate = unit.removesuffix(".service") + ".timer"
    return candidate if candidate in units else None


def systemd_show(unit: str) -> dict[str, str]:
    properties = "LoadState,ActiveState,SubState,Result,ExecMainStatus,ExecMainExitTimestamp,LastTriggerUSec,NextElapseUSecRealtime"
    try:
        output = subprocess.run(
            ["systemctl", "show", unit, f"--property={properties}"], text=True,
            capture_output=True, check=False, timeout=8,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return {"LoadState": "error"}
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def age_minutes(value: Any, now: datetime) -> float | None:
    parsed = parse_observed_time(value)
    return None if parsed is None else max(0.0, (now.astimezone() - parsed).total_seconds() / 60.0)


def parse_observed_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    # Project log timestamps have no offset and represent the Pi's local time.
    # Parse them before the generic helper, which correctly treats offset-less
    # ISO timestamps as UTC for external sources.
    for fmt in ("%Y-%m-%d-%H-%M-%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text.split(".")[0], fmt).replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError:
            pass
    parsed = parse_time(value)
    if parsed is not None:
        return parsed
    # systemctl show emits values such as "Fri 2026-09-11 14:10:00 CEST".
    parts = text.split()
    if len(parts) >= 3:
        try:
            return datetime.strptime(" ".join(parts[1:3]), "%Y-%m-%d %H:%M:%S").replace(tzinfo=datetime.now().astimezone().tzinfo)
        except ValueError:
            pass
    return None


def timer_interval_minutes(timer: dict[str, str], fallback: float) -> float:
    last, next_ = parse_observed_time(timer.get("LastTriggerUSec")), parse_observed_time(timer.get("NextElapseUSecRealtime"))
    if last and next_ and next_ > last:
        return max(1.0, (next_ - last).total_seconds() / 60.0)
    return fallback


def failed_timer_job_is_reportable(facts: dict[str, str], override: dict[str, Any], config: dict[str, Any], now: datetime) -> bool:
    grace = float(override.get("run_failure_grace_minutes", config.get("timer_job_failure_grace_minutes", 0)))
    age = age_minutes(facts.get("ExecMainExitTimestamp"), now)
    return age is None or age >= grace


def stream_timestamp(path: Path, field: str) -> Any:
    if path.suffix == ".json":
        # NDJSON is the usual project log format.  A direct JSON artifact is
        # recognised by a valid JSON object with the configured timestamp key.
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and field in value:
                return value[field]
            if isinstance(value, dict):
                return datetime.fromtimestamp(path.stat().st_mtime).astimezone().isoformat()
        except (OSError, json.JSONDecodeError):
            pass
    record = last_ndjson_record(str(path))
    return record.get(field) if record else None


def fresh_illuminance_evidence(root: Path, policy: dict[str, Any], now: datetime) -> str:
    """Return optional WS90 evidence; it never affects PV incident detection."""
    evidence = policy.get("illumination_evidence", {})
    relative = evidence.get("stream")
    if not relative:
        return ""
    path = root / "data" / "logs" / relative
    record = last_ndjson_record(str(path))
    if not record:
        return ""
    observed_at = record.get(evidence.get("timestamp_field", "last_updated"))
    observed_age = age_minutes(observed_at, now)
    if observed_age is None or observed_age > float(evidence.get("max_age_minutes", 5)):
        return ""
    value = record
    for key in evidence.get("value_path", ["state", "illuminance_lux"]):
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    try:
        illuminance_lux = float(value)
    except (TypeError, ValueError):
        return ""
    if illuminance_lux < float(evidence.get("minimum_lux", 10000)):
        return ""
    return f"; fresh WS90 illuminance is {illuminance_lux:.0f} lux"


def pv_inverter_candidates(
    root: Path,
    relative: str,
    path: Path,
    policy: dict[str, Any],
    profile: str,
    now: datetime,
) -> list[dict[str, Any]]:
    """Classify a PV observation from direct logger and inverter evidence."""
    record = last_ndjson_record(str(path))
    status_max_age = float(policy.get("max_age_minutes", 15))
    illuminance_evidence = fresh_illuminance_evidence(root, policy, now)
    if not record:
        return [candidate(relative, profile, "pv_status_missing", "No inverter diagnostic record is available")]

    status_age = age_minutes(record.get(policy.get("timestamp_field", "timestamp")), now)
    if status_age is None or status_age > status_max_age:
        detail = "No valid diagnostic timestamp" if status_age is None else (
            f"Latest inverter diagnostic is {status_age:.0f} minutes old (limit {status_max_age:.0f})"
        )
        return [candidate(relative, profile, "pv_status_stale", detail)]

    access_state = record.get("access_state")
    if access_state != "reachable":
        stage = record.get("failure_stage", "unknown")
        return [candidate(
            relative,
            profile,
            "pv_inverter_unreachable",
            f"FusionSolar is not accessible to the logger (stage: {stage}){illuminance_evidence}",
        )]

    if record.get("telemetry_state") != "received":
        stage = record.get("failure_stage", "unknown")
        return [candidate(
            relative,
            profile,
            "pv_inverter_not_reporting",
            f"FusionSolar is reachable but returned no inverter telemetry (stage: {stage}){illuminance_evidence}",
        )]

    source_age = age_minutes(record.get(policy.get("source_timestamp_field", "source_timestamp")), now)
    source_max_age = float(policy.get("source_max_age_minutes", status_max_age))
    if source_age is None or source_age > source_max_age:
        detail = "No valid inverter source timestamp" if source_age is None else (
            f"FusionSolar is reachable, but the newest inverter telemetry is {source_age:.0f} minutes old "
            f"(limit {source_max_age:.0f})"
        )
        return [candidate(relative, profile, "pv_inverter_not_reporting", detail + illuminance_evidence)]

    minimum_fields = int(policy.get("minimum_dc_voltage_fields", 1))
    observed_fields = int(record.get("dc_voltage_field_count", 0) or 0)
    if record.get("dc_voltage_state") == "all_zero" and observed_fields >= minimum_fields:
        return [candidate(
            relative,
            profile,
            "pv_inverter_zero_dc_voltage",
            f"Fresh inverter telemetry explicitly reports 0 V on all {observed_fields} observed PV inputs{illuminance_evidence}",
        )]

    return []


def discover_streams(root: Path, config: dict[str, Any]) -> set[str]:
    excluded = set(config.get("excluded_streams", []))
    discovered: set[str] = set()
    logs = root / "data" / "logs"
    if logs.exists():
        for path in logs.rglob("*.json"):
            relative = path.relative_to(logs).as_posix()
            if not any(relative == item or relative.startswith(item + "/") for item in excluded):
                discovered.add(relative)
    return discovered


def initial_incidents() -> dict[str, Any]:
    return {"active": {}, "pending": {}, "known_units": [], "known_streams": []}


def candidate(identifier: str, profile: str, kind: str, message: str) -> dict[str, Any]:
    return {"id": f"{identifier}:{kind}", "identifier": identifier, "profile": profile,
            "kind": kind, "message": message}


def render_active_incidents(incidents: list[dict[str, Any]]) -> str:
    """Render the current open service/data incidents for terminal use."""
    if not incidents:
        return "NO ACTIVE SERVICE/DATA INCIDENTS"
    rows = ["ACTIVE SERVICE/DATA INCIDENTS", "PROFILE   TYPE             IDENTIFIER                              DETAILS"]
    rows.append("--------- ---------------- --------------------------------------- ------------------------------")
    for incident in sorted(incidents, key=lambda item: (item.get("profile", ""), item.get("identifier", ""), item.get("kind", ""))):
        rows.append(
            f"{incident.get('profile', '')[:9].upper():9} "
            f"{incident.get('kind', '')[:16]:16} "
            f"{incident.get('identifier', '')[:39]:39} "
            f"{incident.get('message', '')}"
        )
    return "\n".join(rows)


def evaluate(root: Path, config: dict[str, Any], now: datetime) -> tuple[list[dict[str, Any]], set[str], set[str]]:
    units = unit_list(root)
    candidates: list[dict[str, Any]] = []
    overrides = config.get("service_overrides", {})
    for unit in units:
        profile = overrides.get(unit, {}).get("profile", "revision")
        facts = systemd_show(unit)
        if facts.get("LoadState") != "loaded":
            candidates.append(candidate(unit, profile, "unit_missing", "Unit is not loaded"))
            continue
        if unit.endswith(".timer"):
            if facts.get("ActiveState") != "active":
                candidates.append(candidate(unit, profile, "timer_inactive", "Timer is not active"))
            else:
                last_age = age_minutes(facts.get("LastTriggerUSec"), now)
                interval = timer_interval_minutes(facts, float(config.get("default_output_max_age_minutes", 60)))
                limit = interval + float(config.get("timer_output_grace_minutes", 5))
                if last_age is not None and last_age > limit:
                    candidates.append(candidate(unit, profile, "timer_overdue", f"Timer last fired {last_age:.0f} minutes ago (limit {limit:.0f})"))
            continue
        paired_timer = timer_for_service(unit, units)
        if paired_timer:
            if (
                facts.get("Result") not in {"", "success"}
                and overrides.get(unit, {}).get("state_monitor") != "pv_inverter"
                and failed_timer_job_is_reportable(facts, overrides.get(unit, {}), config, now)
            ):
                candidates.append(candidate(unit, profile, "run_failed", f"Latest timer job result is {facts.get('Result')}"))
        elif facts.get("ActiveState") not in {"active", "activating", "reloading"}:
            candidates.append(candidate(unit, profile, "service_inactive", "Continuous service is not active"))

    streams = config.get("streams", {})
    default_age = float(config.get("default_output_max_age_minutes", 60))
    grace = float(config.get("timer_output_grace_minutes", 5))
    for relative, policy in streams.items():
        profile = overrides.get(policy.get("service", ""), {}).get("profile", "revision")
        path = root / (relative if relative.startswith("system/") or relative.startswith("config/") else "data/logs/" + relative)
        if policy.get("kind") == "pv_inverter":
            candidates.extend(pv_inverter_candidates(root, relative, path, policy, profile, now))
            continue
        if policy.get("kind") != "periodic":
            continue
        timestamp = stream_timestamp(path, policy.get("timestamp_field", "timestamp"))
        explicit_max_age = policy.get("max_age_minutes")
        allowed = float(explicit_max_age if explicit_max_age is not None else default_age)
        service = policy.get("service")
        if explicit_max_age is None and service:
            timer = timer_for_service(service, units)
            if timer:
                allowed = timer_interval_minutes(systemd_show(timer), allowed) + grace
        age = age_minutes(timestamp, now)
        if age is None or age > allowed:
            detail = "No valid timestamp" if age is None else f"Latest valid record is {age:.0f} minutes old (limit {allowed:.0f})"
            candidates.append(candidate(relative, profile, "data_stale", detail))
    return candidates, set(units), discover_streams(root, config)


def update(previous: dict[str, Any], candidates: list[dict[str, Any]], units: set[str], streams: set[str], config: dict[str, Any], now: datetime) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    state = dict(previous or initial_incidents())
    active, pending = state.setdefault("active", {}), state.setdefault("pending", {})
    known_units, known_streams = set(state.get("known_units", [])), set(state.get("known_streams", []))
    current = {item["id"]: item for item in candidates}
    for unit in sorted(units - known_units): current[f"{unit}:discovered"] = candidate(unit, "revision", "discovered", "New managed service or timer requires review")
    configured_streams = set(config.get("streams", {}))
    for stream in sorted((streams - configured_streams) - known_streams):
        current[f"{stream}:discovered"] = candidate(stream, "revision", "discovered", "New data stream requires classification")
    opened, solved = [], []
    confirmations = int(config.get("confirmation_runs", 2))
    for key, item in current.items():
        required = 1 if item["kind"] == "discovered" else confirmations
        if key in active:
            active[key]["last_seen_at"] = now_iso(now); active[key]["message"] = item["message"]
            continue
        run = pending.setdefault(key, {"runs": 0, "first_seen_at": now_iso(now), "candidate": item})
        run["runs"] += 1
        if run["runs"] >= required:
            incident = {**item, "opened_at": now_iso(now), "last_seen_at": now_iso(now), "notified_at": None}
            active[key] = incident; pending.pop(key, None); opened.append(incident)
    for key in list(pending):
        if key not in current: pending.pop(key, None)
    for key, incident in list(active.items()):
        if key in current: continue
        status = "retired" if incident["kind"] == "discovered" else "solved"
        solved.append({**incident, "status": status, "solved_at": now_iso(now)})
        active.pop(key, None)
    state["known_units"], state["known_streams"] = sorted(units), sorted(streams)
    return state, opened, solved


def notify_opened(state: dict[str, Any], opened: list[dict[str, Any]], mode: str, *, bootstrap: bool = False) -> None:
    if mode != "live": return
    # A failed mail attempt must not silently consume an incident.  Reconsider
    # every active incident until notify_admin accepts it, including ones that
    # were opened during an earlier watchdog pass.
    unnotified = [item for item in state["active"].values() if not item.get("notified_at")]
    discoveries = [item for item in unnotified if item["kind"] == "discovered"]
    if discoveries:
        details = "\n".join(f"- {item['identifier']}: {item['message']}" for item in discoveries)
        if bootstrap:
            body = (
                "This is the initial coverage inventory. Listed systemd units are now "
                "monitored automatically; no acknowledgement is required. New data files "
                "without a configured policy should be reviewed.\n\n" + details
            )
            subject = "[REVISION] Service/data watchdog: initial coverage inventory"
        else:
            body = details
            subject = "[REVISION] Service/data watchdog: new coverage requires review"
        try:
            notify_admin(subject, body)
        except Exception:
            pass
        else:
            for item in discoveries:
                state["active"][item["id"]]["notified_at"] = now_iso()
    for incident in unnotified:
        if incident["kind"] == "discovered":
            continue
        try:
            notify_admin(f"[{incident['profile'].upper()}] Service/data watchdog: {incident['identifier']}", incident["message"])
        except Exception:
            continue
        state["active"][incident["id"]]["notified_at"] = now_iso()


def notify_solved(solved: list[dict[str, Any]], mode: str) -> None:
    if mode != "live":
        return
    for incident in solved:
        if incident.get("status") != "solved" or not incident.get("notified_at"):
            continue
        try:
            notify_admin(
                f"[{incident['profile'].upper()}] Service/data watchdog: recovered {incident['identifier']}",
                f"Recovered condition: {incident['message']}",
            )
        except Exception:
            continue


def run(*, dry_run: bool = False) -> dict[str, Any]:
    root = Path(get_project_root()); config = read_json(str(root / CONFIG_PATH), {})
    now = datetime.now().astimezone(); previous = read_json(str(root / INCIDENTS_PATH), initial_incidents())
    bootstrap = not previous.get("known_units") and not previous.get("known_streams")
    candidates, units, streams = evaluate(root, config, now)
    state, opened, solved = update(previous, candidates, units, streams, config, now)
    snapshot = {"generated_at": now_iso(now), "active_incidents": list(state["active"].values()), "known_units": sorted(units), "known_streams": sorted(streams)}
    if not dry_run:
        notify_opened(state, opened, config.get("mode", "shadow"), bootstrap=bootstrap)
        notify_solved(solved, config.get("mode", "shadow"))
        atomic_write_json(str(root / INCIDENTS_PATH), state); atomic_write_json(str(root / STATE_PATH), snapshot)
        for item in solved: append_ndjson(str(root / SOLVED_PATH), item)
        ping_healthchecks(str(root), config)
    return {"state": state, "snapshot": snapshot, "opened": opened, "solved": solved}


def main() -> int:
    parser = argparse.ArgumentParser(description="Monitor Kazanfutes services and data streams.")
    parser.add_argument("command", choices=("check", "status", "coverage", "discover", "validate"), nargs="?", default="check")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(); root = Path(get_project_root())
    if args.command == "status":
        snapshot = read_json(str(root / STATE_PATH), {})
        print(render_active_incidents(snapshot.get("active_incidents", []))); return 0
    if args.command == "coverage":
        snapshot = read_json(str(root / STATE_PATH), {})
        print(json.dumps({"known_units": snapshot.get("known_units", []), "known_streams": snapshot.get("known_streams", [])}, indent=2)); return 0
    if args.command == "discover":
        config = read_json(str(root / CONFIG_PATH), {}); known = set(config.get("streams", {}))
        print("\n".join(sorted(discover_streams(root, config) - known))); return 0
    if args.command == "validate":
        config = read_json(str(root / CONFIG_PATH), {}); units = set(unit_list(root)); bad = [name for name, item in config.get("streams", {}).items() if item.get("service") not in units]
        print("valid" if not bad else "unknown service: " + ", ".join(bad)); return int(bool(bad))
    result = run(dry_run=args.dry_run)
    for incident in result["snapshot"]["active_incidents"]: print(f"{incident['profile']} {incident['identifier']}: {incident['message']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
