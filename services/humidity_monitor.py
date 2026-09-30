"""Alert when a humidity sensor stays high for too much of a recent window.

The monitor consumes the existing temperature/humidity and Aqara/Nous NDJSON
logs. Alerts are keyed by sensor name rather than room. Runtime state is kept
outside the repository so a persistent incident is not emailed on every run.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from utils.project import get_project_root, get_rooms_info, notify_admin, report


# Operational policy. Keep these here so the service has no private config file.
HUMIDITY_THRESHOLD_PERCENT = 60.0
LOOKBACK_HOURS = 24.0
PERMITTED_HIGH_HUMIDITY_HOURS = 6.0

# Sampling safeguards. A missing interval never counts as humid time.
MAX_SAMPLE_GAP_MINUTES = 15.0
MIN_RECOVERY_COVERAGE_RATIO = 0.75

ROOM_LOG_RELATIVE_PATH = "data/logs/temperature_and_humidity/temperature_and_humidity.json"
AIR_SENSOR_LOG_RELATIVE_PATH = "data/logs/aqara_and_nous/aqara_and_nous.json"
STATE_PATH = Path("/var/lib/kazanfutes/humidity_monitor/state.json")


def parse_timestamp(value: Any) -> datetime | None:
    """Parse project timestamps and return an aware local datetime."""
    text = str(value or "").strip()
    if not text:
        return None

    for fmt in ("%Y-%m-%d-%H-%M-%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text.split(".")[0], fmt).astimezone()
        except ValueError:
            pass

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone() if parsed.tzinfo is None else parsed.astimezone()


def humidity_percent(value: Any) -> float | None:
    """Normalize either percentage or deCONZ hundredths-of-a-percent values."""
    try:
        humidity = float(value)
    except (TypeError, ValueError):
        return None
    if humidity > 100.0:
        humidity /= 100.0
    if not 0.0 <= humidity <= 100.0:
        return None
    return humidity


def recent_log_files(path: Path, cutoff: datetime) -> list[Path]:
    """Return the live NDJSON log and recent daily rotations."""
    candidates = [path, *path.parent.glob(path.name + ".*")]
    earliest_mtime = (cutoff - timedelta(days=1)).timestamp()
    recent: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.is_file() and candidate.stat().st_mtime >= earliest_mtime:
                recent.append(candidate)
        except OSError:
            continue
    return sorted(set(recent), key=lambda item: item.stat().st_mtime)


def read_ndjson(path: Path, cutoff: datetime) -> Iterable[dict[str, Any]]:
    """Yield valid recent records, tolerating a partial line during logging."""
    for log_path in recent_log_files(path, cutoff):
        try:
            with log_path.open("r", encoding="utf-8", errors="replace") as stream:
                for line in stream:
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(record, dict):
                        yield record
        except OSError:
            continue


def add_point(
    points: dict[str, dict[datetime, float]],
    sensor_name: Any,
    timestamp_value: Any,
    humidity_value: Any,
) -> None:
    name = str(sensor_name or "").strip()
    observed_at = parse_timestamp(timestamp_value)
    humidity = humidity_percent(humidity_value)
    if name and observed_at is not None and humidity is not None:
        points[name][observed_at] = humidity


def room_sensor_names() -> dict[str, str]:
    """Map room-log keys back to the sensor names that produced the values."""
    names: dict[str, str] = {}
    for room, info in get_rooms_info(just_controlled=False).items():
        sensor_name = info.get("sensor") if isinstance(info, dict) else None
        if sensor_name:
            names[str(room)] = str(sensor_name)
    return names


def load_room_log_points(
    path: Path,
    cutoff: datetime,
    points: dict[str, dict[datetime, float]],
) -> bool:
    files = recent_log_files(path, cutoff)
    if not files:
        return False

    names = room_sensor_names()
    for record in read_ndjson(path, cutoff):
        observed_at = record.get("timestamp")
        for room, sensor_name in names.items():
            reading = record.get(room)
            if isinstance(reading, dict):
                add_point(points, sensor_name, observed_at, reading.get("hum"))
    return True


def load_air_sensor_log_points(
    path: Path,
    cutoff: datetime,
    points: dict[str, dict[datetime, float]],
) -> bool:
    files = recent_log_files(path, cutoff)
    if not files:
        return False

    for record in read_ndjson(path, cutoff):
        observed_at = record.get("timestamp")
        states = record.get("states")
        if not isinstance(states, dict):
            continue
        for family in ("nous", "aqara"):
            sensors = states.get(family)
            if not isinstance(sensors, dict):
                continue
            for key, reading in sensors.items():
                if not isinstance(reading, dict):
                    continue
                add_point(
                    points,
                    reading.get("name") or key,
                    observed_at,
                    reading.get("hum"),
                )
    return True


def load_sensor_points(now: datetime) -> dict[str, list[tuple[datetime, float]]]:
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    read_from = cutoff - timedelta(minutes=MAX_SAMPLE_GAP_MINUTES)
    root = Path(get_project_root())
    points: dict[str, dict[datetime, float]] = defaultdict(dict)

    source_results = [
        load_room_log_points(root / ROOM_LOG_RELATIVE_PATH, read_from, points),
        load_air_sensor_log_points(root / AIR_SENSOR_LOG_RELATIVE_PATH, read_from, points),
    ]
    if not any(source_results):
        raise FileNotFoundError("no configured humidity log source exists")

    return {
        sensor: sorted(observations.items())
        for sensor, observations in points.items()
        if observations
    }


def summarize_samples(
    samples: Iterable[tuple[datetime, float]],
    now: datetime,
) -> dict[str, Any]:
    """Integrate represented time above the threshold over the lookback."""
    cutoff = now - timedelta(hours=LOOKBACK_HOURS)
    gap_limit = timedelta(minutes=MAX_SAMPLE_GAP_MINUTES)
    ordered = sorted(
        (timestamp, humidity)
        for timestamp, humidity in samples
        if timestamp <= now and timestamp >= cutoff - gap_limit
    )
    if not ordered:
        return {
            "high_hours": 0.0,
            "covered_hours": 0.0,
            "latest_at": None,
            "latest_humidity": None,
        }

    covered_seconds = 0.0
    high_seconds = 0.0
    for index, (observed_at, humidity) in enumerate(ordered):
        next_at = ordered[index + 1][0] if index + 1 < len(ordered) else now
        represented_until = min(next_at, observed_at + gap_limit, now)
        represented_from = max(observed_at, cutoff)
        if represented_until <= represented_from:
            continue
        seconds = (represented_until - represented_from).total_seconds()
        covered_seconds += seconds
        if humidity > HUMIDITY_THRESHOLD_PERCENT:
            high_seconds += seconds

    latest_at, latest_humidity = ordered[-1]
    return {
        "high_hours": high_seconds / 3600.0,
        "covered_hours": covered_seconds / 3600.0,
        "latest_at": latest_at,
        "latest_humidity": latest_humidity,
    }


def initial_state() -> dict[str, Any]:
    return {"schema_version": 1, "sensors": {}}


def read_state(path: Path = STATE_PATH) -> dict[str, Any]:
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return initial_state()
    if not isinstance(state, dict) or not isinstance(state.get("sensors"), dict):
        return initial_state()
    return state


def atomic_write_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def render_alert(alerts: list[dict[str, Any]]) -> str:
    lines = [
        "One or more humidity sensors exceeded the configured duration limit.",
        "",
        f"Threshold: above {HUMIDITY_THRESHOLD_PERCENT:.0f}% RH",
        f"Limit: {PERMITTED_HIGH_HUMIDITY_HOURS:g} hours in the last {LOOKBACK_HOURS:g} hours",
        "",
    ]
    for alert in alerts:
        latest_at = alert["latest_at"].strftime("%Y-%m-%d %H:%M:%S %Z")
        lines.extend(
            [
                alert["sensor"],
                f"  High-humidity time: {alert['high_hours']:.1f} hours",
                f"  Represented log coverage: {alert['covered_hours']:.1f} hours",
                f"  Latest reading: {alert['latest_humidity']:.1f}% at {latest_at}",
                "",
            ]
        )
    lines.append("Please inspect the relevant area for condensation, dampness, or mould risk.")
    return "\n".join(lines)


def run_monitor(
    *,
    now: datetime | None = None,
    send_notifications: bool = True,
    write_state: bool = True,
    state_path: Path = STATE_PATH,
) -> dict[str, Any]:
    now = now or datetime.now().astimezone()
    points = load_sensor_points(now)
    state = read_state(state_path)
    sensor_state = state.setdefault("sensors", {})
    alerts: list[dict[str, Any]] = []
    summaries: dict[str, dict[str, Any]] = {}
    minimum_recovery_coverage = LOOKBACK_HOURS * MIN_RECOVERY_COVERAGE_RATIO
    freshness_limit = timedelta(minutes=MAX_SAMPLE_GAP_MINUTES)

    for sensor, samples in sorted(points.items(), key=lambda item: item[0].casefold()):
        summary = summarize_samples(samples, now)
        summaries[sensor] = summary
        previous = sensor_state.get(sensor, {})
        was_active = bool(previous.get("active"))
        exceeds_limit = summary["high_hours"] > PERMITTED_HIGH_HUMIDITY_HOURS
        latest_at = summary["latest_at"]
        fresh = latest_at is not None and now - latest_at <= freshness_limit
        enough_recovery_data = summary["covered_hours"] >= minimum_recovery_coverage and fresh

        active = exceeds_limit or (was_active and not enough_recovery_data)
        if exceeds_limit and not was_active:
            alerts.append({"sensor": sensor, **summary})

        sensor_state[sensor] = {
            "active": active,
            "high_hours": round(summary["high_hours"], 3),
            "covered_hours": round(summary["covered_hours"], 3),
            "latest_at": latest_at.isoformat() if latest_at else None,
            "latest_humidity": summary["latest_humidity"],
            "last_evaluated_at": now.isoformat(),
            "last_alert_at": (
                now.isoformat()
                if exceeds_limit and not was_active
                else previous.get("last_alert_at")
            ),
        }

    if alerts and send_notifications:
        if not notify_admin(
            subject=f"Humidity warning: {len(alerts)} sensor(s)",
            body=render_alert(alerts),
        ):
            raise RuntimeError("humidity alert email was not confirmed as sent")

    state["last_run_at"] = now.isoformat()
    if write_state:
        atomic_write_state(state, state_path)

    return {
        "sensor_count": len(summaries),
        "new_alerts": [alert["sensor"] for alert in alerts],
        "summaries": summaries,
    }


def self_test() -> None:
    now = datetime(2026, 1, 15, 12, 0, 0).astimezone()
    start = now - timedelta(hours=24)
    samples = []
    for step in range(24 * 12 + 1):
        observed_at = start + timedelta(minutes=5 * step)
        humidity = 65.0 if observed_at < start + timedelta(hours=7) else 50.0
        samples.append((observed_at, humidity))
    summary = summarize_samples(samples, now)
    assert 6.9 < summary["high_hours"] < 7.1, summary
    assert 23.9 < summary["covered_hours"] <= 24.0, summary

    gap_samples = [
        (start, 70.0),
        (start + timedelta(hours=12), 70.0),
    ]
    gap_summary = summarize_samples(gap_samples, now)
    assert gap_summary["high_hours"] <= 0.5, gap_summary
    print("humidity_monitor self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="evaluate logs without sending email or updating incident state",
    )
    parser.add_argument("--self-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    try:
        result = run_monitor(
            send_notifications=not args.dry_run,
            write_state=not args.dry_run,
        )
    except Exception as error:
        report(f"Humidity monitor failed: {type(error).__name__}: {error}")
        return 1

    alert_names = ", ".join(result["new_alerts"]) or "none"
    report(
        f"Humidity monitor evaluated {result['sensor_count']} sensors; "
        f"new alerts: {alert_names}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
