"""
Resilient V2 schedule/config updater.

The service keeps last-known-good local inputs, regenerates the same condensed
schedule model used by the existing controller, supports warm-up across midnight,
and publishes cloud telemetry only after local atomic persistence succeeds.
"""

from __future__ import annotations

import copy
import csv
import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from typing import Any

from utils.project import (
    JSONNodeAtURL,
    ModuleException,
    ServiceException,
    download_google_sheet_to_2D_array,
    generate_timepoint_info,
    get_project_root,
    get_rooms_info,
    get_rooms_occupancy,
    report,
    scrape_external_temperature,
    select_subtable_from_table,
    settings,
    timestamp,
    transpose_2D_array,
)


RUNTIME_CONFIG_PATH = "config/heating_control_runtime_v2.json"
CONFIG_V2_PATH = "config/heating_control_config_v2.json"
CONFIG_FALLBACK_PATH = "config/heating_control_config.json"
SWITCH_V2_PATH = "config/heating_switch_v2.json"
LOCAL_INPUT_V2_DIR = "config/scheduling/local_scheduling_files_v2"
LOCAL_INPUT_FALLBACK_DIR = "config/scheduling/local_scheduling_files"
WARMING_PARAMS_PATH = "config/warming_params.csv"
CONDENSED_SCHEDULE_PATH = "config/scheduling/condensed_schedule_v2.json"
SCHEDULE_META_PATH = "config/scheduling/condensed_schedule_v2.meta.json"
BASE_SCHEDULE_PATH = "system/base_schedule_v2.json"
PRESENCE_WITH_OVERRIDE_PATH = "system/presence_with_override_v2.json"
EXTERNAL_TEMP_CACHE_PATH = "system/external_temperature_cache_v2.json"
HEALTH_PATH = "system/schedule_and_config_updater_v2_health.json"
INCIDENTS_PATH = "data/error_management/schedule_and_config_updater_v2_incidents.json"
HEATING_TELEMETRY_OUTBOX_PATH = "data/heating_control/telemetry_outbox_v2.json"


def _full_path(path: str) -> str:
    return path if os.path.isabs(path) else os.path.join(get_project_root(), path)


def _load_json(path: str, default: Any = None) -> Any:
    try:
        with open(_full_path(path), "r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        if default is not None:
            return default
        raise


def _load_json_fallback(primary: str, fallback: str) -> tuple[Any, str]:
    try:
        return _load_json(primary), primary
    except Exception:
        return _load_json(fallback), fallback


def _atomic_write_json(data: Any, path: str) -> None:
    full_path = _full_path(path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    temporary_path = f"{full_path}.tmp.{os.getpid()}"
    try:
        with open(temporary_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(data, handle, indent=4, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, full_path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def _atomic_write_csv(rows: list[list[Any]], path: str) -> None:
    full_path = _full_path(path)
    os.makedirs(os.path.dirname(full_path), exist_ok=True)
    temporary_path = f"{full_path}.tmp.{os.getpid()}"
    try:
        with open(temporary_path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerows(rows)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, full_path)
    finally:
        try:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)
        except OSError:
            pass


def _record_incident(code: str, message: str, severity: int, error: Exception | None = None) -> None:
    now = timestamp()
    try:
        incidents = _load_json(INCIDENTS_PATH, default={})
        old = incidents.get(code, {})
        incidents[code] = {
            "code": code,
            "message": message,
            "severity": severity,
            "count": int(old.get("count", 0)) + 1,
            "first_seen": old.get("first_seen", now),
            "last_seen": now,
            "last_detail": str(error) if error else None,
        }
        _atomic_write_json(incidents, INCIDENTS_PATH)
    except Exception as incident_error:
        report(f"V2 schedule incident telemetry failed for {code}: {incident_error}")

    try:
        ServiceException(
            f"[schedule-v2:{code}] {message}",
            original_exception=error if isinstance(error, ModuleException) else None,
            severity=severity,
        )
    except Exception as registry_error:
        report(f"Established error registry failed for schedule V2 {code}: {registry_error}")


def _read_csv(path: str) -> list[list[str]]:
    with open(_full_path(path), "r", encoding="utf-8", newline="") as handle:
        return list(csv.reader(handle))


def _input_path(filename: str) -> str:
    v2 = os.path.join(LOCAL_INPUT_V2_DIR, filename)
    if os.path.exists(_full_path(v2)):
        return v2
    return os.path.join(LOCAL_INPUT_FALLBACK_DIR, filename)


def _validate_heating_config(config: dict[str, Any], rooms: dict[str, Any]) -> None:
    required = {
        "heating_control_config_id",
        "weekly_cycle_id",
        "override_rooms_id",
        "override_rooms_qr_id",
        "override_cycles_id",
        "system_on",
        "no_presence_offset",
        "heating_window",
        "hysteresis_buffer",
        "temp_data_expiry",
        "gain_P_lag",
        "gain_I",
        "gain_P_overshoot",
        "gain_D",
    }
    required.update(f"cycle_{cycle}_on" for cycle in range(1, 5))
    for room in rooms:
        required.update(
            {
                f"room_{room}_on",
                f"room_{room}_threshold_temp",
                f"room_{room}_in_threshold",
                f"room_{room}_weekly_cycle_weight",
            }
        )
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"heating configuration is missing keys: {missing}")

    if int(config["system_on"]) not in (0, 1):
        raise ValueError("system_on must be 0 or 1")
    for cycle in range(1, 5):
        if int(config[f"cycle_{cycle}_on"]) not in (-1, 0, 1):
            raise ValueError(f"cycle_{cycle}_on must be -1, 0, or 1")
    for room in rooms:
        if int(config[f"room_{room}_on"]) not in (-1, 0, 1):
            raise ValueError(f"room_{room}_on must be -1, 0, or 1")


def _generate_switch(config: dict[str, Any], rooms: dict[str, Any]) -> dict[str, Any]:
    switch = {
        "system": int(config["system_on"]),
        "cycles": {str(cycle): int(config[f"cycle_{cycle}_on"]) for cycle in range(1, 5)},
        "rooms": {room: int(config[f"room_{room}_on"]) for room in rooms},
        "last_updated": timestamp(),
    }
    _atomic_write_json(switch, SWITCH_V2_PATH)
    return switch


def _download_heating_config(current: dict[str, Any], rooms: dict[str, Any]) -> dict[str, Any]:
    table = download_google_sheet_to_2D_array(current["heating_control_config_id"])
    selected = select_subtable_from_table(table, [1, -0], [0, -1])
    columns = transpose_2D_array(selected)
    updated = dict(zip(columns[0], columns[1]))
    _validate_heating_config(updated, rooms)
    _atomic_write_json(updated, CONFIG_V2_PATH)
    _generate_switch(updated, rooms)
    return updated


def _refresh_remote_inputs(config: dict[str, Any], rooms: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    results: dict[str, Any] = {}
    try:
        config = _download_heating_config(config, rooms)
        results["heating_config"] = {"success": True}
    except Exception as error:
        results["heating_config"] = {"success": False, "error": str(error)}
        _record_incident("heating_config_download", "Could not refresh the heating configuration", 2, error)

    downloads = [
        ("override_rooms.csv", config["override_rooms_id"], None),
        ("override_rooms_qr.csv", config["override_rooms_qr_id"], None),
        ("override_cycles.csv", config["override_cycles_id"], None),
    ]
    downloads.extend(
        (
            f"weekly_cycle_room_{room}.csv",
            config["weekly_cycle_id"],
            info["name"],
        )
        for room, info in rooms.items()
    )

    for filename, spreadsheet_id, sheet_name in downloads:
        try:
            rows = download_google_sheet_to_2D_array(spreadsheet_id, sheet_name)
            if not isinstance(rows, list) or len(rows) < 2:
                raise ValueError("downloaded sheet did not contain a header and data")
            _atomic_write_csv(rows, os.path.join(LOCAL_INPUT_V2_DIR, filename))
            results[filename] = {"success": True}
        except Exception as error:
            results[filename] = {"success": False, "error": str(error)}
            _record_incident(
                f"download_{filename}",
                f"Could not refresh {filename}; its last-known-good copy remains in use",
                2,
                error,
            )

    return config, results


def _parse_warming_params(rooms: dict[str, Any]) -> dict[str, dict[str, float]]:
    rows = _read_csv(WARMING_PARAMS_PATH)
    by_name: dict[str, dict[str, float]] = {}
    for row in rows[1:]:
        if len(row) < 7:
            continue
        by_name[row[0]] = {
            "a": float(row[1]),
            "b": float(row[2]),
            "start_factor": float(row[3]),
            "end_factor": float(row[4]),
            "t_min": float(row[5]),
            "t_max": float(row[6]),
        }
    output: dict[str, dict[str, float]] = {}
    for room, info in rooms.items():
        if info["name"] not in by_name:
            raise ValueError(f"no warming parameters for room {room} ({info['name']})")
        output[room] = by_name[info["name"]]
    return output


def _parse_weekly_cycle(room: str) -> dict[str, dict[str, float]]:
    rows = _read_csv(_input_path(f"weekly_cycle_room_{room}.csv"))
    if len(rows) < 25 or len(rows[0]) < 8:
        raise ValueError(f"weekly cycle for room {room} is incomplete")
    cycle = {str(day): {} for day in range(1, 8)}
    for row in rows[1:]:
        if len(row) < 8:
            continue
        hour = str(int(row[0]))
        for day in range(1, 8):
            cycle[str(day)][hour] = float(row[day])
    for day in cycle:
        if len(cycle[day]) != 24:
            raise ValueError(f"weekly cycle for room {room}, day {day}, has {len(cycle[day])} hours")
    return cycle


def _parse_google_datetime(date_value: str, hour_value: str) -> datetime:
    return datetime.strptime(f"{date_value.strip()}-{hour_value.strip()}", "%d/%m/%Y-%H")


def _parse_override_rows(filename: str, with_temperature: bool) -> list[dict[str, Any]]:
    rows = _read_csv(_input_path(filename))
    overrides: list[dict[str, Any]] = []
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    for row in rows[1:]:
        required_length = 6 if with_temperature else 5
        if len(row) < required_length or not any(cell.strip() for cell in row):
            continue
        try:
            start = _parse_google_datetime(row[2], row[3])
            end = start + timedelta(hours=int(row[4]))
            if end < today:
                continue
            item = {
                "google_timestamp": datetime.strptime(row[0].strip(), "%d/%m/%Y %H:%M:%S"),
                "target": row[1].strip(),
                "start": start,
                "end": end,
            }
            if with_temperature:
                item["temperature"] = float(row[5])
            overrides.append(item)
        except (TypeError, ValueError):
            continue
    return overrides


def _presence_probability(
    room: str,
    day_of_week: str,
    hour: str,
    weekly_cycles: dict[str, Any],
    learned_presence: dict[str, Any],
    config: dict[str, Any],
) -> float:
    weekly = float(weekly_cycles[room][day_of_week][hour])
    weight = float(config[f"room_{room}_weekly_cycle_weight"])
    learned = 0.0
    threshold = float(config[f"room_{room}_in_threshold"])
    try:
        if threshold > 0:
            learned = math.floor(float(learned_presence[room][day_of_week][hour]) / threshold)
    except (KeyError, TypeError, ValueError):
        learned = 0.0
    return max(0.0, min(1.0, weight * weekly + (1.0 - weight) * learned))


def _external_temperature() -> tuple[float, str]:
    try:
        value = float(scrape_external_temperature())
        _atomic_write_json(
            {"temperature": value, "updated_at": timestamp(), "epoch": time.time()},
            EXTERNAL_TEMP_CACHE_PATH,
        )
        return value, "live"
    except Exception as error:
        cached = _load_json(EXTERNAL_TEMP_CACHE_PATH, default={})
        if cached.get("temperature") is not None:
            _record_incident(
                "external_temperature_cached",
                "External temperature was unavailable; cached value used for schedule generation",
                1,
                error,
            )
            return float(cached["temperature"]), "cached"
        _record_incident(
            "external_temperature_default",
            "External temperature and cache were unavailable; conservative 10 C default used",
            2,
            error,
        )
        return 10.0, "default"


def _generate_base_schedule(
    config: dict[str, Any],
    rooms: dict[str, Any],
    runtime: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    warming_params = _parse_warming_params(rooms)
    weekly_cycles = {room: _parse_weekly_cycle(room) for room in rooms}
    learned_presence = _load_json(
        os.path.join(LOCAL_INPUT_FALLBACK_DIR, "occupancy.json"),
        default={},
    )
    room_overrides = _parse_override_rows("override_rooms.csv", with_temperature=True)
    room_overrides.extend(_parse_override_rows("override_rooms_qr.csv", with_temperature=True))
    cycle_overrides = _parse_override_rows("override_cycles.csv", with_temperature=False)

    start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    day_count = int(runtime["schedule_days"]) + 2
    slots: list[tuple[str, str, datetime, str]] = []
    for day_offset in range(day_count):
        day_start = start + timedelta(days=day_offset)
        for hour in range(24):
            point = day_start.replace(hour=hour, minute=30)
            info = generate_timepoint_info(point)
            slots.append(
                (
                    str(info["unix_day"]),
                    str(hour),
                    point,
                    str(info["day_of_week"]),
                )
            )

    presence: dict[str, Any] = {room: {} for room in rooms}
    for room, info in rooms.items():
        for day, hour, point, day_of_week in slots:
            value = _presence_probability(
                room,
                day_of_week,
                hour,
                weekly_cycles,
                learned_presence,
                config,
            )
            applicable_rooms = [
                item
                for item in room_overrides
                if item["target"] == info["name"] and item["start"] <= point < item["end"]
            ]
            if applicable_rooms:
                latest = max(applicable_rooms, key=lambda item: item["google_timestamp"])
                value = math.floor(float(latest["temperature"]) / 17.0)
            if any(
                item["target"] == str(info["cycle"])
                and item["start"] <= point < item["end"]
                for item in cycle_overrides
            ):
                # Preserve the established meaning: cycle shutdown selects Tmin.
                value = 0.0
            presence[room].setdefault(day, {})[hour] = value

    requested_temperature: dict[str, Any] = {room: {} for room in rooms}
    for room in rooms:
        params = warming_params[room]
        for day, hours in presence[room].items():
            requested_temperature[room][day] = {
                hour: params["t_min"] + value * (params["t_max"] - params["t_min"])
                for hour, value in hours.items()
            }

    outside_temp, outside_source = _external_temperature()
    warming_curves: dict[str, dict[int, float]] = {}
    back_hour_count = 7
    for room, params in warming_params.items():
        tau = max(1.0, params["a"] + params["b"] * outside_temp)
        curve: dict[int, float] = {}
        for minutes in range(0, back_hour_count * 60 + 1, 60):
            key = minutes // 60 - back_hour_count
            raw = (
                params["t_max"] * params["end_factor"]
                + (
                    params["t_min"] * params["start_factor"]
                    - params["t_max"] * params["end_factor"]
                )
                * math.exp(-minutes / tau)
            )
            curve[key] = max(params["t_min"], min(raw, params["t_max"]))
        warming_curves[room] = curve

    heating = copy.deepcopy(requested_temperature)
    ordered_keys = [(day, hour) for day, hour, _, _ in slots]
    for room in rooms:
        curve = warming_curves[room]
        curve_items = list(curve.items())
        for index, (day, hour) in enumerate(ordered_keys):
            target = requested_temperature[room][day][hour]
            nearest_key, _ = min(curve_items, key=lambda item: abs(item[1] - target))
            back_hours = back_hour_count + nearest_key
            for offset in range(1, back_hours + 1):
                previous_index = index - offset
                if previous_index < 0:
                    break
                previous_day, previous_hour = ordered_keys[previous_index]
                warming_key = nearest_key - offset
                heating[room][previous_day][previous_hour] = max(
                    heating[room][previous_day][previous_hour],
                    curve[warming_key],
                )

    schedule = copy.deepcopy(heating)
    no_presence_offset = float(config["no_presence_offset"])
    for room, info in rooms.items():
        params = warming_params[room]
        enforce_offset = isinstance(info.get("pres"), str)
        for day, hours in schedule[room].items():
            for hour, value in hours.items():
                adjusted = value - (no_presence_offset if enforce_offset else 0.0)
                schedule[room][day][hour] = round(
                    max(params["t_min"], min(adjusted, params["t_max"])),
                    1,
                )

    generation = {
        "generated_at": timestamp(),
        "generated_epoch": time.time(),
        "external_temperature": outside_temp,
        "external_temperature_source": outside_source,
        "first_day": ordered_keys[0][0],
        "last_day": ordered_keys[-1][0],
    }
    return presence, schedule, generation


def _enforce_current_occupancy(
    base_schedule: dict[str, Any],
    config: dict[str, Any],
    rooms: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    condensed = copy.deepcopy(base_schedule)
    try:
        window = int(config["heating_window"])
        occupancy_by_time = get_rooms_occupancy(minutes=range(-window, 1))
        occupied: dict[str, bool] = {room: False for room in rooms}
        for states in occupancy_by_time.values():
            for room in rooms:
                occupied[room] = occupied[room] or bool(states.get(room, False))
        point = generate_timepoint_info()
        day = str(point["unix_day"])
        hour = str(point["hour_of_day"])
        warming_params = _parse_warming_params(rooms)
        for room, is_occupied in occupied.items():
            if is_occupied and day in condensed.get(room, {}):
                condensed[room][day][hour] = warming_params[room]["t_max"]
        return condensed, {"valid": True, "occupied": occupied, "error": None}
    except Exception as error:
        _record_incident(
            "presence_enforcement",
            "Current occupancy could not be applied; base last-known-good schedule used",
            2,
            error,
        )
        return condensed, {"valid": False, "occupied": {}, "error": str(error)}


class _FirebaseBridge:
    def __init__(self, runtime: dict[str, Any]):
        self.runtime = runtime
        self.nodes: dict[str, JSONNodeAtURL] = {}
        self.next_retry_epoch = 0.0
        self.last_update_fingerprint: str | None = None
        self.last_heating_telemetry_fingerprint: str | None = None

    def _node(self, path: str) -> JSONNodeAtURL:
        if path not in self.nodes:
            self.nodes[path] = JSONNodeAtURL(node_relative_path=path)
        return self.nodes[path]

    def _failed(self) -> None:
        self.nodes = {}
        self.next_retry_epoch = time.time() + float(self.runtime["firebase_retry_seconds"])

    def poll_update_changed(self) -> bool:
        if time.time() < self.next_retry_epoch:
            return False
        try:
            state = self._node("update").read()
            fingerprint = json.dumps(state, sort_keys=True, separators=(",", ":"))
            changed = (
                self.last_update_fingerprint is not None
                and fingerprint != self.last_update_fingerprint
            )
            self.last_update_fingerprint = fingerprint
            return changed
        except Exception as error:
            self._failed()
            _record_incident(
                "firebase_update_poll",
                "Firebase update polling failed; periodic local refresh remains active",
                1,
                error,
            )
            return False

    def publish_schedule(self, schedule: dict[str, Any], metadata: dict[str, Any]) -> bool:
        if time.time() < self.next_retry_epoch:
            return False
        try:
            node = self._node("schedule")
            node.write(schedule, "condensed_schedule_v2")
            node.write(metadata, "condensed_schedule_v2_metadata")
            return True
        except Exception as error:
            self._failed()
            _record_incident(
                "firebase_schedule_publish",
                "V2 schedule was saved locally but Firebase publication failed",
                1,
                error,
            )
            return False

    def publish_heating_telemetry(self) -> tuple[bool, bool]:
        """Publish the latest controller outbox outside the control process."""
        outbox = _load_json(HEATING_TELEMETRY_OUTBOX_PATH, default={})
        if not outbox:
            return True, False
        fingerprint = json.dumps(outbox, sort_keys=True, separators=(",", ":"))
        if fingerprint == self.last_heating_telemetry_fingerprint:
            return True, False
        if time.time() < self.next_retry_epoch:
            return False, False
        try:
            node = self._node("system")
            node.write(outbox["control"], "control_v2")
            node.write(outbox["state"], "state_v2")
            node.write(outbox["health"], "health_v2")
            self.last_heating_telemetry_fingerprint = fingerprint
            return True, True
        except Exception as error:
            self._failed()
            _record_incident(
                "firebase_heating_telemetry",
                "Heating control remains local, but its staged Firebase telemetry could not be published",
                1,
                error,
            )
            return False, False


def main() -> int:
    settings["log"] = True
    settings["verbosity"] = True
    runtime = _load_json(RUNTIME_CONFIG_PATH)
    rooms = get_rooms_info()
    config, config_source = _load_json_fallback(CONFIG_V2_PATH, CONFIG_FALLBACK_PATH)
    _validate_heating_config(config, rooms)
    _generate_switch(config, rooms)

    bridge = _FirebaseBridge(runtime)
    base_schedule = _load_json(BASE_SCHEDULE_PATH, default={}) or None
    presence = _load_json(PRESENCE_WITH_OVERRIDE_PATH, default={}) or None
    base_generation: dict[str, Any] = {}
    last_remote_refresh = 0.0
    last_firebase_poll = 0.0
    last_base_day: str | None = None
    last_condensed = _load_json(CONDENSED_SCHEDULE_PATH, default={}) or None
    last_publish = 0.0

    while True:
        loop_started = time.time()
        health: dict[str, Any] = {
            "last_updated": timestamp(),
            "config_source": config_source,
        }
        try:
            # On a fresh V2 installation, form and atomically save a schedule
            # from local last-known-good inputs before attempting the batch of
            # remote sheet calls.  The next pass performs the due refresh.
            local_schedule_ready = last_condensed is not None
            remote_due = (
                local_schedule_ready
                and loop_started - last_remote_refresh
                >= float(runtime["schedule_remote_refresh_hours"]) * 3600.0
            )
            if (
                local_schedule_ready
                and
                loop_started - last_firebase_poll
                >= float(runtime["schedule_firebase_poll_seconds"])
            ):
                remote_due = bridge.poll_update_changed() or remote_due
                last_firebase_poll = loop_started

            if remote_due:
                config, refresh_results = _refresh_remote_inputs(config, rooms)
                config_source = CONFIG_V2_PATH if os.path.exists(_full_path(CONFIG_V2_PATH)) else config_source
                health["remote_refresh"] = refresh_results
                last_remote_refresh = loop_started

            current_day = datetime.now().strftime("%Y-%m-%d")
            regenerate = (
                base_schedule is None
                or presence is None
                or current_day != last_base_day
                or remote_due
            )
            if regenerate:
                new_presence, new_base_schedule, base_generation = _generate_base_schedule(
                    config,
                    rooms,
                    runtime,
                )
                presence = new_presence
                base_schedule = new_base_schedule
                last_base_day = current_day
                _atomic_write_json(presence, PRESENCE_WITH_OVERRIDE_PATH)
                _atomic_write_json(base_schedule, BASE_SCHEDULE_PATH)

            condensed, occupancy_health = _enforce_current_occupancy(
                base_schedule,
                config,
                rooms,
            )
            content_changed = condensed != last_condensed
            metadata = {
                **base_generation,
                "last_validated_at": timestamp(),
                "last_validated_epoch": time.time(),
                "occupancy": occupancy_health,
            }
            if content_changed or not os.path.exists(_full_path(CONDENSED_SCHEDULE_PATH)):
                _atomic_write_json(condensed, CONDENSED_SCHEDULE_PATH)
                last_condensed = condensed
            # The small metadata file is refreshed every pass; the 50 KB schedule
            # is only replaced when its content actually changes.
            _atomic_write_json(metadata, SCHEDULE_META_PATH)

            publish_due = content_changed or loop_started - last_publish >= 300.0
            firebase_success = True
            if publish_due:
                firebase_success = bridge.publish_schedule(condensed, metadata)
                if firebase_success:
                    last_publish = loop_started

            telemetry_success, telemetry_published = bridge.publish_heating_telemetry()

            health.update(
                {
                    "success": True,
                    "base_regenerated": regenerate,
                    "schedule_content_changed": content_changed,
                    "firebase_publish_success": firebase_success,
                    "heating_telemetry_publish_success": telemetry_success,
                    "heating_telemetry_published": telemetry_published,
                    "base_generation": base_generation,
                    "occupancy": occupancy_health,
                    "duration_seconds": time.time() - loop_started,
                }
            )
            _atomic_write_json(health, HEALTH_PATH)
            report(
                f"Schedule V2 pass complete: regenerated={regenerate}, changed={content_changed}, firebase={firebase_success}."
            )
        except Exception as error:
            _record_incident(
                "schedule_loop",
                "V2 schedule loop failed; existing last-known-good schedule was retained",
                3,
                error,
            )
            health.update(
                {
                    "success": False,
                    "error": str(error),
                    "duration_seconds": time.time() - loop_started,
                }
            )
            try:
                _atomic_write_json(health, HEALTH_PATH)
            except Exception:
                pass

        sleep_seconds = max(
            1.0,
            float(runtime["schedule_loop_seconds"]) - (time.time() - loop_started),
        )
        time.sleep(sleep_seconds)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as fatal_error:
        _record_incident("fatal", "Schedule V2 terminated unexpectedly", 3, fatal_error)
        sys.exit(3)
