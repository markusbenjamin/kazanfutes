"""
Local-first V2 heating controller.

This is a parallel implementation.  It deliberately uses V2 state, command,
PID and telemetry paths so installing it does not modify the existing
controller's persisted state.  The control model remains:

    condensed schedule -> room votes -> cycle votes -> actuator commands

The main differences are fault isolation, corrected temperature/PID handling,
latest-intent command semantics, boiler/pump interlocks, and best-effort cloud
telemetry.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any

from utils.project import (
    ModuleException,
    ServiceException,
    get_boiler_state,
    get_cycles_info,
    get_project_root,
    get_pump_state,
    get_rooms_info,
    get_rooms_occupancy,
    generate_timepoint_info,
    read_sensors,
    report,
    set_boiler_state,
    set_pump_state,
    set_thermostat_state_by_id,
    settings,
    shutdown_all_thermostats,
    timestamp,
)


RUNTIME_CONFIG_PATH = "config/heating_control_runtime_v2.json"
HEATING_CONFIG_PATHS = (
    "config/heating_control_config_v2.json",
    "config/heating_control_config.json",
)
HEATING_SWITCH_PATHS = (
    "config/heating_switch_v2.json",
    "config/heating_switch.json",
)
SCHEDULE_PATHS = (
    "config/scheduling/condensed_schedule_v2.json",
    "config/scheduling/condensed_schedule.json",
)
SCHEDULE_META_PATH = "config/scheduling/condensed_schedule_v2.meta.json"

STATE_PATH = "system/state_v2.json"
CONTROL_PATH = "system/control_v2.json"
PID_PATH = "system/PID_state_v2.json"
TRV_OUTPUT_PATH = "system/TRV_output_state_v2.json"
ACTUATOR_HISTORY_PATH = "system/actuator_history_v2.json"
MODE_STATE_PATH = "system/heating_mode_state_v2.json"
HEALTH_PATH = "system/heating_control_v2_health.json"
COMMANDS_PATH = "data/heating_control/commands_v2.json"
COMMANDS_ARCHIVE_PATH = "data/heating_control/commands_archive_v2.json"
INCIDENTS_PATH = "data/error_management/heating_control_v2_incidents.json"
TELEMETRY_OUTBOX_PATH = "data/heating_control/telemetry_outbox_v2.json"


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


def _load_first(paths: tuple[str, ...]) -> tuple[Any, str]:
    last_error: Exception | None = None
    for path in paths:
        try:
            return _load_json(path), path
        except Exception as error:
            last_error = error
    raise RuntimeError(f"none of the configured files could be loaded: {paths}") from last_error


def _atomic_write_json(data: Any, path: str) -> None:
    full_path = _full_path(path)
    directory = os.path.dirname(full_path)
    os.makedirs(directory, exist_ok=True)
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


def _atomic_write_text(text: str, path: str) -> None:
    full_path = _full_path(path)
    directory = os.path.dirname(full_path)
    os.makedirs(directory, exist_ok=True)
    temporary_path = f"{full_path}.tmp.{os.getpid()}"
    try:
        with open(temporary_path, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
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
    """Keep occurrence telemetry and also feed the established error registry."""
    now = timestamp()
    try:
        incidents = _load_json(INCIDENTS_PATH, default={})
        existing = incidents.get(code, {})
        incidents[code] = {
            "code": code,
            "message": message,
            "severity": severity,
            "count": int(existing.get("count", 0)) + 1,
            "first_seen": existing.get("first_seen", now),
            "last_seen": now,
            "last_detail": str(error) if error else None,
        }
        _atomic_write_json(incidents, INCIDENTS_PATH)
    except Exception as registry_error:
        report(f"V2 incident telemetry failed for {code}: {registry_error}")

    try:
        ServiceException(
            f"[heating-v2:{code}] {message}",
            original_exception=error if isinstance(error, ModuleException) else None,
            severity=severity,
        )
    except Exception as registry_error:
        report(f"Established error registry failed for {code}: {registry_error}")


def _parse_deconz_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _local_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone().strftime(settings["timestamp_format"])


def _age_minutes(value: datetime | None, now_utc: datetime) -> float | None:
    if value is None:
        return None
    return (now_utc - value).total_seconds() / 60.0


def _is_fresh(age_minutes: float | None, expiry_minutes: float, future_tolerance: float) -> bool:
    return (
        age_minutes is not None
        and -future_tolerance <= age_minutes <= expiry_minutes
    )


def _load_runtime_config() -> dict[str, Any]:
    runtime = _load_json(RUNTIME_CONFIG_PATH)
    required = {
        "temperature_future_tolerance_minutes",
        "schedule_interpolation_hours",
        "schedule_lookahead_hours",
        "schedule_warning_age_hours",
        "schedule_hard_expiry_hours",
        "valve_demand_open_percent",
        "valve_demand_close_percent",
        "pid_integral_min",
        "pid_integral_max",
        "pid_reset_after_minutes",
        "pid_dt_cap_seconds",
        "trv_setpoint_change_c",
        "trv_external_temp_change_c",
        "trv_refresh_minutes",
        "trv_confirmation_timeout_seconds",
        "command_ttl_minutes",
        "boiler_minimum_on_minutes",
        "boiler_minimum_off_minutes",
        "pump_prestart_seconds",
        "pump_overrun_minutes",
        "off_mode_trv_check_minutes",
        "heartbeat_path",
    }
    missing = sorted(required - set(runtime))
    if missing:
        raise ValueError(f"V2 runtime configuration is missing keys: {missing}")
    if float(runtime["schedule_hard_expiry_hours"]) <= float(
        runtime["schedule_warning_age_hours"]
    ):
        raise ValueError("schedule hard expiry must exceed its warning age")
    if float(runtime["valve_demand_open_percent"]) <= float(
        runtime["valve_demand_close_percent"]
    ):
        raise ValueError("valve open threshold must exceed its close threshold")
    if float(runtime["pid_integral_max"]) < float(runtime["pid_integral_min"]):
        raise ValueError("PID integral maximum must not be below its minimum")
    return runtime


def _validate_switch(
    switch: dict[str, Any],
    cycles: dict[str, Any],
    rooms: dict[str, Any] | None = None,
) -> None:
    if int(switch.get("system", -999)) not in (0, 1):
        raise ValueError("heating switch system value must be 0 or 1")
    cycle_switches = switch.get("cycles")
    if not isinstance(cycle_switches, dict):
        raise ValueError("heating switch has no cycle map")
    for cycle in cycles:
        if int(cycle_switches.get(str(cycle), -999)) not in (-1, 0, 1):
            raise ValueError(f"heating switch for cycle {cycle} must be -1, 0, or 1")
    if rooms is None:
        return
    room_switches = switch.get("rooms")
    if not isinstance(room_switches, dict):
        raise ValueError("heating switch has no room map")
    for room in rooms:
        if int(room_switches.get(str(room), -999)) not in (-1, 0, 1):
            raise ValueError(f"heating switch for room {room} must be -1, 0, or 1")


def _validate_heating_config(config: dict[str, Any], rooms: dict[str, Any]) -> None:
    required = {
        "hysteresis_buffer",
        "temp_data_expiry",
        "gain_P_lag",
        "gain_I",
        "gain_P_overshoot",
        "gain_D",
    }
    required.update(f"room_{room}_threshold_temp" for room in rooms)
    missing = sorted(required - set(config))
    if missing:
        raise ValueError(f"heating configuration is missing keys: {missing}")
    if float(config["temp_data_expiry"]) <= 0:
        raise ValueError("temp_data_expiry must be positive")


def _schedule_age_hours(schedule_path: str) -> float:
    if schedule_path == SCHEDULE_PATHS[0]:
        try:
            metadata = _load_json(SCHEDULE_META_PATH)
            validated_epoch = float(metadata["last_validated_epoch"])
            return max(0.0, (time.time() - validated_epoch) / 3600.0)
        except Exception:
            pass
    return max(0.0, (time.time() - os.path.getmtime(_full_path(schedule_path))) / 3600.0)


def _read_sensor_snapshot() -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Read Deconz once and index room sensors by name and TRVs by sensor ID."""
    by_name: dict[str, dict[str, Any]] = {}
    thermostats: dict[str, dict[str, Any]] = {}

    for sensor_id, sensor in read_sensors():
        raw = sensor.raw if hasattr(sensor, "raw") else sensor
        sensor_type = getattr(sensor, "type", raw.get("type"))
        name = getattr(sensor, "name", raw.get("name"))
        state = raw.get("state", {})
        config = raw.get("config", {})
        updated_at = _parse_deconz_utc(state.get("lastupdated"))

        if sensor_type == "ZHAThermostat":
            raw_temperature = state.get("temperature")
            thermostats[str(sensor_id)] = {
                "id": str(sensor_id),
                "name": name,
                "temperature": None if raw_temperature is None else float(raw_temperature) / 100.0,
                "valve": state.get("valve"),
                "updated_at": updated_at,
                "reachable": bool(config.get("reachable", True)),
                "config": config,
            }
            continue

        if not name:
            continue
        record = by_name.setdefault(
            str(name),
            {
                "temperature": None,
                "temperature_updated_at": None,
                "humidity": None,
                "humidity_updated_at": None,
            },
        )
        if sensor_type == "ZHATemperature":
            raw_temperature = getattr(sensor, "temperature", state.get("temperature"))
            record["temperature"] = (
                None if raw_temperature is None else float(raw_temperature) / 100.0
            )
            record["temperature_updated_at"] = updated_at
        elif sensor_type == "ZHAHumidity":
            raw_humidity = getattr(sensor, "humidity", state.get("humidity"))
            record["humidity"] = None if raw_humidity is None else float(raw_humidity) / 100.0
            record["humidity_updated_at"] = updated_at

    return by_name, thermostats


def _thermostat_ids(room_info: dict[str, Any]) -> list[str]:
    configured = room_info.get("thermostats")
    if not isinstance(configured, str):
        return []
    return [item.strip() for item in configured.split(";") if item.strip()]


def _build_room_inputs(
    rooms: dict[str, dict[str, Any]],
    heating_config: dict[str, Any],
    runtime: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    now_utc = datetime.now(timezone.utc)
    expiry_minutes = float(heating_config["temp_data_expiry"])
    future_tolerance = float(runtime["temperature_future_tolerance_minutes"])
    room_inputs: dict[str, Any] = {}
    health: dict[str, dict[str, Any]] = {}

    try:
        by_name, thermostats = _read_sensor_snapshot()
        mesh_error = None
    except Exception as error:
        by_name, thermostats = {}, {}
        mesh_error = error
        _record_incident("deconz_snapshot", "Could not acquire the Deconz sensor snapshot", 3, error)

    for room, info in rooms.items():
        primary = by_name.get(str(info.get("sensor")), {})
        primary_temp = primary.get("temperature")
        primary_dt = primary.get("temperature_updated_at")
        primary_age = _age_minutes(primary_dt, now_utc)
        primary_fresh = primary_temp is not None and _is_fresh(
            primary_age, expiry_minutes, future_tolerance
        )

        fresh_trv_temps: list[float] = []
        fresh_trv_times: list[datetime] = []
        valve_values: list[float] = []
        missing_thermostats: list[str] = []

        for thermostat_id in _thermostat_ids(info):
            thermostat = thermostats.get(thermostat_id)
            if not thermostat:
                missing_thermostats.append(thermostat_id)
                continue
            age = _age_minutes(thermostat.get("updated_at"), now_utc)
            reachable = thermostat.get("reachable", True)
            if (
                reachable
                and thermostat.get("temperature") is not None
                and _is_fresh(age, expiry_minutes, future_tolerance)
            ):
                fresh_trv_temps.append(float(thermostat["temperature"]))
                fresh_trv_times.append(thermostat["updated_at"])
            if reachable and thermostat.get("valve") is not None:
                valve_values.append(float(thermostat["valve"]))

        fallback_temp = (
            sum(fresh_trv_temps) / len(fresh_trv_temps) if fresh_trv_temps else None
        )
        # The oldest member bounds the freshness of an averaged fallback value.
        fallback_dt = min(fresh_trv_times) if fresh_trv_times else None

        if primary_fresh:
            measured_temp = primary_temp
            measured_dt = primary_dt
            source = "room_sensor"
        elif fallback_temp is not None:
            measured_temp = fallback_temp
            measured_dt = fallback_dt
            source = "thermostat_fallback"
        else:
            measured_temp = None
            measured_dt = primary_dt or fallback_dt
            source = "unavailable"

        humidity = primary.get("humidity")
        humidity_dt = primary.get("humidity_updated_at")
        humidity_age = _age_minutes(humidity_dt, now_utc)
        if not _is_fresh(humidity_age, expiry_minutes, future_tolerance):
            humidity = None

        if isinstance(info.get("thermostats"), str):
            valves = valve_values
            valve_available = bool(valve_values)
        elif info.get("thermostats"):
            valves = [100.0]
            valve_available = True
        else:
            valves = [0.0]
            valve_available = True

        room_inputs[room] = {
            "temperature": measured_temp,
            "temperature_updated_at": _local_timestamp(measured_dt),
            "temperature_age_minutes": _age_minutes(measured_dt, now_utc),
            "temperature_source": source,
            "humidity": humidity,
            "humidity_updated_at": _local_timestamp(humidity_dt),
            "valves": valves,
            "valve_available": valve_available,
            "thermostat_ids": _thermostat_ids(info),
        }
        health[room] = {
            "temperature_valid": measured_temp is not None,
            "temperature_source": source,
            "primary_age_minutes": primary_age,
            "fallback_age_minutes": _age_minutes(fallback_dt, now_utc),
            "valve_available": valve_available,
            "missing_thermostats": missing_thermostats,
            "deconz_snapshot_error": str(mesh_error) if mesh_error else None,
        }

    room_inputs["_thermostats"] = thermostats
    return room_inputs, health


def _read_occupancy(rooms: dict[str, Any]) -> tuple[dict[str, bool], dict[str, Any]]:
    try:
        occupancy = get_rooms_occupancy()
        return (
            {room: bool(occupancy.get(room, False)) for room in rooms},
            {"valid": True, "error": None},
        )
    except Exception as error:
        _record_incident("occupancy", "Occupancy was unavailable; control continued without display occupancy", 2, error)
        return (
            {room: False for room in rooms},
            {"valid": False, "error": str(error)},
        )


def _schedule_values(
    condensed_schedule: dict[str, Any],
    rooms: dict[str, Any],
    runtime: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    now = datetime.now()
    timepoint = generate_timepoint_info(now)
    unix_day = int(timepoint["unix_day"])
    hour = int(timepoint["hour_of_day"])
    hour_fraction = now.minute / 60.0 + now.second / 3600.0
    lookahead = int(runtime["schedule_lookahead_hours"])
    interpolation_window = float(runtime["schedule_interpolation_hours"])
    values: dict[str, dict[str, Any]] = {}
    valid_count = 0

    for room in rooms:
        try:
            days = condensed_schedule[room]
            set_now = float(days[str(unix_day)][str(hour)])
            set_interpolated = set_now
            hours_ahead: int | None = None
            next_set = set_now

            for ahead in range(1, lookahead + 1):
                future_hour = (hour + ahead) % 24
                future_day = unix_day + (hour + ahead) // 24
                # JSON object keys are strings.
                if str(future_day) not in days:
                    break
                candidate = float(days[str(future_day)][str(future_hour)])
                if candidate != set_now:
                    hours_ahead = ahead
                    next_set = candidate
                    break

            if hours_ahead is not None:
                time_until_change = max(0.0, hours_ahead - hour_fraction)
                if time_until_change < interpolation_window:
                    fraction = (
                        interpolation_window - time_until_change
                    ) / interpolation_window
                    set_interpolated = set_now + (next_set - set_now) * fraction

            values[room] = {
                "nominal": set_now,
                "interpolated": set_interpolated,
                # Interpolation only anticipates increases, never scheduled setbacks.
                "effective": max(set_now, set_interpolated),
                "valid": True,
                "error": None,
            }
            valid_count += 1
        except Exception as error:
            values[room] = {
                "nominal": None,
                "interpolated": None,
                "effective": None,
                "valid": False,
                "error": str(error),
            }
            _record_incident(
                f"schedule_room_{room}",
                f"No usable current schedule value for room {room}",
                3,
                error,
            )

    return values, {"valid_rooms": valid_count, "total_rooms": len(rooms)}


def _read_actuators(cycles: dict[str, Any]) -> tuple[dict[str, int | None], dict[str, Any]]:
    actual: dict[str, int | None] = {}
    health: dict[str, Any] = {}
    for cycle in cycles:
        device = f"pump_{cycle}"
        try:
            actual[device] = int(bool(get_pump_state(cycle)))
            health[device] = {"valid": True, "error": None}
        except Exception as error:
            actual[device] = None
            health[device] = {"valid": False, "error": str(error)}
            _record_incident(device, f"Could not read {device}", 3, error)
    try:
        actual["boiler"] = int(bool(get_boiler_state()))
        health["boiler"] = {"valid": True, "error": None}
    except Exception as error:
        actual["boiler"] = None
        health["boiler"] = {"valid": False, "error": str(error)}
        _record_incident("boiler_read", "Could not read boiler output state", 3, error)
    return actual, health


def _initial_actuator_history(actual: dict[str, int | None]) -> dict[str, Any]:
    now = time.time()
    old_enough = now - 86400
    history = _load_json(ACTUATOR_HISTORY_PATH, default={})
    for device, state in actual.items():
        if device not in history:
            history[device] = {
                "state": state,
                "last_transition_epoch": old_enough,
                "last_transition": timestamp(datetime.fromtimestamp(old_enough)),
            }
        elif state is not None and history[device].get("state") != state:
            history[device] = {
                "state": state,
                "last_transition_epoch": now,
                "last_transition": timestamp(),
            }
    return history


def _load_previous_room_states(rooms: dict[str, Any]) -> dict[str, int]:
    for path in (STATE_PATH, "system/state.json"):
        try:
            state = _load_json(path)
            previous = state.get("room_states", {})
            return {room: int(bool(previous.get(room, 0))) for room in rooms}
        except Exception:
            continue
    return {room: 0 for room in rooms}


def _load_pid_state() -> dict[str, Any]:
    state = _load_json(PID_PATH, default={})
    return state if isinstance(state, dict) else {}


def _compute_pid_output(
    thermostat_id: str,
    measured_temp: float,
    set_temp: float,
    valve_open_percent: float,
    heating_config: dict[str, Any],
    runtime: dict[str, Any],
    pid_state: dict[str, Any],
) -> tuple[float, dict[str, Any], bool]:
    now_epoch = time.time()
    gain_p_lag = float(heating_config["gain_P_lag"])
    gain_i = float(heating_config["gain_I"])
    gain_p_overshoot = float(heating_config["gain_P_overshoot"])
    gain_d = float(heating_config["gain_D"])
    integral_min = float(runtime["pid_integral_min"])
    integral_max = float(runtime["pid_integral_max"])
    reset_after = float(runtime["pid_reset_after_minutes"]) * 60.0
    dt_cap = float(runtime["pid_dt_cap_seconds"])

    previous = pid_state.get(thermostat_id, {})
    previous_epoch = float(previous.get("epoch", 0) or 0)
    elapsed = now_epoch - previous_epoch if previous_epoch else 60.0
    if elapsed <= 0 or elapsed > reset_after:
        previous_integral = 0.0
        previous_temp = measured_temp
        dt = min(60.0, dt_cap)
        reset = True
    else:
        previous_integral = float(previous.get("bias_I", 0.0))
        previous_temp = float(previous.get("temp", measured_temp))
        dt = min(max(elapsed, 1.0), dt_cap)
        reset = False

    error_raw = set_temp - measured_temp
    error_positive = max(0.0, error_raw)
    proportional_lag = gain_p_lag * error_positive
    candidate_integral = previous_integral
    if error_raw > 0:
        if proportional_lag + previous_integral < integral_max:
            candidate_integral += gain_i * error_raw * dt
    else:
        candidate_integral += gain_i * error_raw * dt
    integral = max(integral_min, min(candidate_integral, integral_max))

    weight_lag = 1.0 / (1.0 + math.exp(-20.0 * (error_positive - 0.25))) if error_raw > 0 else 0.0
    lag_bias = weight_lag * max(0.0, min(proportional_lag + integral, integral_max))

    heat_rate = (measured_temp - previous_temp) / dt
    overshoot = max(0.0, measured_temp - (set_temp + 0.5))
    overshoot_bias = min(
        -gain_p_overshoot * overshoot - gain_d * max(0.0, heat_rate),
        0.0,
    )
    overshoot_active = error_raw < -0.2 and valve_open_percent > float(runtime["valve_demand_close_percent"])
    if not overshoot_active:
        overshoot_bias = 0.0

    effective_setpoint = set_temp + lag_bias + overshoot_bias
    telemetry = {
        "error": error_raw,
        "dt_seconds": dt,
        "state_reset": reset,
        "bias_P_lag": proportional_lag,
        "bias_I": integral,
        "bias_lag": lag_bias,
        "heat_rate": heat_rate,
        "overshoot": overshoot,
        "bias_overshoot": overshoot_bias,
        "effective_setpoint": effective_setpoint,
    }
    return effective_setpoint, telemetry, overshoot_active


def _should_write_trv(
    thermostat: dict[str, Any] | None,
    thermostat_id: str,
    target_setpoint: float,
    measured_temp: float,
    runtime: dict[str, Any],
    output_state: dict[str, Any],
) -> bool:
    now_epoch = time.time()
    previous = output_state.get(thermostat_id, {})
    refresh_due = now_epoch - float(previous.get("last_success_epoch", 0) or 0) >= float(
        runtime["trv_refresh_minutes"]
    ) * 60.0
    if thermostat is None:
        return True
    config = thermostat.get("config", {})
    actual_setpoint = config.get("heatsetpoint")
    actual_external = config.get("externalsensortemp")
    setpoint_delta = (
        math.inf
        if actual_setpoint is None
        else abs(float(actual_setpoint) / 100.0 - target_setpoint)
    )
    external_delta = (
        math.inf
        if actual_external is None
        else abs(float(actual_external) / 100.0 - measured_temp)
    )
    return (
        refresh_due
        or setpoint_delta >= float(runtime["trv_setpoint_change_c"])
        or external_delta >= float(runtime["trv_external_temp_change_c"])
    )


def _write_trv_if_needed(
    thermostat_id: str,
    thermostat: dict[str, Any] | None,
    target_setpoint: float,
    measured_temp: float,
    runtime: dict[str, Any],
    output_state: dict[str, Any],
    dry_run: bool,
) -> dict[str, Any]:
    needed = _should_write_trv(
        thermostat,
        thermostat_id,
        target_setpoint,
        measured_temp,
        runtime,
        output_state,
    )
    if not needed:
        return {"needed": False, "success": True, "dry_run": dry_run}
    if dry_run:
        return {"needed": True, "success": True, "dry_run": True}
    try:
        success = bool(
            set_thermostat_state_by_id(
                thermostat_id,
                timeout_s=float(runtime["trv_confirmation_timeout_seconds"]),
                heatsetpoint=target_setpoint,
                externalsensortemp=measured_temp,
            )
        )
        if not success:
            _record_incident(
                f"trv_write_{thermostat_id}",
                f"Thermostat {thermostat_id} did not confirm its requested state",
                2,
            )
            return {"needed": True, "success": False, "dry_run": False}
        output_state[thermostat_id] = {
            "last_success_epoch": time.time(),
            "last_success": timestamp(),
            "heatsetpoint": target_setpoint,
            "externalsensortemp": measured_temp,
        }
        return {"needed": True, "success": True, "dry_run": False}
    except Exception as error:
        _record_incident(
            f"trv_write_{thermostat_id}",
            f"Thermostat {thermostat_id} update failed",
            2,
            error,
        )
        return {"needed": True, "success": False, "dry_run": False, "error": str(error)}


def _vote_rooms(
    rooms: dict[str, dict[str, Any]],
    switch: dict[str, Any],
    schedule_values: dict[str, dict[str, Any]],
    room_inputs: dict[str, Any],
    occupancy: dict[str, bool],
    previous_room_states: dict[str, int],
    heating_config: dict[str, Any],
    runtime: dict[str, Any],
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, int], dict[str, int], dict[str, Any]]:
    pid_state = _load_pid_state()
    output_state = _load_json(TRV_OUTPUT_PATH, default={})
    thermostat_snapshot = room_inputs.get("_thermostats", {})
    cycle_counts = {cycle: 0 for cycle in get_cycles_info()}
    room_votes: dict[str, int] = {}
    room_control: dict[str, Any] = {}
    usable_rooms = 0

    for room, info in rooms.items():
        cycle = str(info["cycle"])
        room_input = room_inputs[room]
        schedule = schedule_values[room]
        previous_vote = int(bool(previous_room_states.get(room, 0)))
        vote = 0
        reason = "safe_off"
        relation = "no usable schedule"
        degraded = False
        trv_results: dict[str, Any] = {}
        pid_telemetry: dict[str, Any] = {}

        if not schedule["valid"]:
            reason = "schedule_unavailable"
        else:
            usable_rooms += 1
            set_temp = float(schedule["effective"])
            cycle_master = int(switch.get("cycles", {}).get(cycle, 0))
            room_master = int(switch.get("rooms", {}).get(room, 0))

            if set_temp == -1:
                reason = "scheduled_master_off"
                relation = "schedule requested hard off"
            elif cycle_master == -1:
                reason = "cycle_master_off"
                relation = f"cycle {cycle} forced off"
            elif cycle_master == 1:
                vote = 1
                reason = "cycle_master_on"
                relation = f"cycle {cycle} forced on"
            elif room_master == -1:
                reason = "room_master_off"
                relation = "room forced off"
            elif room_master == 1:
                vote = 1
                reason = "room_master_on"
                relation = "room forced on"
            else:
                measured_temp = room_input["temperature"]
                if measured_temp is None:
                    degraded = True
                    if (
                        isinstance(info.get("thermostats"), str)
                        and not room_input["valve_available"]
                    ):
                        vote = 0
                        reason = "temperature_and_valve_unavailable"
                        relation = "degraded timed demand blocked because no TRV path was confirmed"
                    else:
                        threshold = float(heating_config[f"room_{room}_threshold_temp"])
                        vote = int(set_temp > threshold)
                        reason = "timed_on_degraded" if vote else "timed_off_degraded"
                        relation = "temperature unavailable; schedule reduced to timed demand"
                elif isinstance(info.get("thermostats"), str):
                    valve_values = room_input["valves"]
                    if not valve_values:
                        degraded = True
                        vote = 0
                        reason = "valve_state_unavailable"
                        relation = "no confirmed open TRV path"
                    else:
                        demand = max(valve_values)
                        threshold = (
                            float(runtime["valve_demand_open_percent"])
                            if previous_vote == 0
                            else float(runtime["valve_demand_close_percent"])
                        )
                        room_overshoot = False
                        for thermostat_id in room_input["thermostat_ids"]:
                            thermostat = thermostat_snapshot.get(thermostat_id)
                            if not thermostat or thermostat.get("valve") is None:
                                trv_results[thermostat_id] = {
                                    "needed": False,
                                    "success": False,
                                    "error": "thermostat unavailable in current snapshot",
                                }
                                continue
                            valve = float(thermostat["valve"])
                            effective_setpoint, pid_info, overshoot = _compute_pid_output(
                                thermostat_id,
                                float(measured_temp),
                                set_temp,
                                valve,
                                heating_config,
                                runtime,
                                pid_state,
                            )
                            pid_state[thermostat_id] = {
                                "bias_I": pid_info["bias_I"],
                                "temp": float(measured_temp),
                                "epoch": time.time(),
                                "timestamp": timestamp(),
                            }
                            pid_telemetry[thermostat_id] = pid_info
                            room_overshoot = room_overshoot or overshoot
                            trv_results[thermostat_id] = _write_trv_if_needed(
                                thermostat_id,
                                thermostat,
                                effective_setpoint,
                                float(measured_temp),
                                runtime,
                                output_state,
                                dry_run,
                            )

                        if room_overshoot:
                            vote = 0
                            reason = "above_setpoint"
                        elif demand > threshold:
                            vote = 1
                            reason = "open_valves"
                        elif demand < threshold:
                            vote = 0
                            reason = "closed_valves"
                        else:
                            vote = previous_vote
                            reason = "valve_hysteresis"
                        relation = f"valve demand {demand:.1f}% against {threshold:.1f}% threshold"
                else:
                    hysteresis = float(heating_config["hysteresis_buffer"])
                    low = set_temp - hysteresis
                    high = set_temp + hysteresis
                    if measured_temp < low:
                        vote = 1
                        reason = "below_setpoint"
                    elif measured_temp > high:
                        vote = 0
                        reason = "above_setpoint"
                    else:
                        vote = previous_vote
                        reason = "temperature_hysteresis"
                    relation = f"{measured_temp:.2f} C against {set_temp:.2f} C"

        room_votes[room] = vote
        cycle_counts[cycle] += vote
        room_control[room] = {
            "vote": vote,
            "reason": reason,
            "relation": relation,
            "occupied": bool(occupancy.get(room, False)),
            "degraded": degraded,
            "temperature_source": room_input.get("temperature_source"),
            "trv_updates": trv_results,
            "PID": pid_telemetry,
        }

    if not dry_run:
        _atomic_write_json(pid_state, PID_PATH)
        _atomic_write_json(output_state, TRV_OUTPUT_PATH)

    pump_votes = {cycle: int(count > 0) for cycle, count in cycle_counts.items()}
    control = {
        "rooms": room_control,
        "cycles": pump_votes,
        "boiler": int(any(pump_votes.values())),
        "last_updated": timestamp(),
    }
    return control, room_votes, pump_votes, {"usable_rooms": usable_rooms}


def _reconcile_command_queue(
    desired: dict[str, int],
    actual: dict[str, int | None],
    history: dict[str, Any],
    runtime: dict[str, Any],
    generation: str,
    force_shutdown: bool,
) -> dict[str, dict[str, Any]]:
    now = time.time()
    existing = _load_json(COMMANDS_PATH, default={})
    if not isinstance(existing, dict):
        existing = {}
    queue: dict[str, dict[str, Any]] = {}
    ttl = float(runtime["command_ttl_minutes"]) * 60.0

    boiler_history = history.get("boiler", {})
    boiler_last = float(boiler_history.get("last_transition_epoch", now - 86400))
    boiler_state = boiler_history.get("state")
    if desired["boiler"]:
        boiler_due = now
        if boiler_state == 0:
            boiler_due = max(
                boiler_due,
                boiler_last + float(runtime["boiler_minimum_off_minutes"]) * 60.0,
            )
        if not any(actual.get(f"pump_{cycle}") == 1 for cycle in get_cycles_info()):
            boiler_due = max(boiler_due, now + float(runtime["pump_prestart_seconds"]))
    else:
        boiler_due = now
        if boiler_state == 1 and not force_shutdown:
            boiler_due = max(
                boiler_due,
                boiler_last + float(runtime["boiler_minimum_on_minutes"]) * 60.0,
            )

    all_pumps_off = not any(
        desired.get(f"pump_{cycle}", 0) for cycle in get_cycles_info()
    )
    boiler_off_since = (
        boiler_last if actual.get("boiler") == 0 and boiler_state == 0 else boiler_due
    )

    for device, setting in desired.items():
        if actual.get(device) == setting:
            continue

        if device == "boiler":
            due_epoch = boiler_due
        elif setting == 1:
            due_epoch = now
        elif all_pumps_off:
            due_epoch = max(
                now,
                boiler_off_since + float(runtime["pump_overrun_minutes"]) * 60.0,
            )
        else:
            due_epoch = now

        old = existing.get(device)
        if (
            isinstance(old, dict)
            and int(old.get("setting", -999)) == setting
            and float(old.get("expires_epoch", 0)) > now
        ):
            if force_shutdown and setting == 0:
                old["due_epoch"] = min(float(old.get("due_epoch", due_epoch)), due_epoch)
            old["generation"] = generation
            queue[device] = old
            continue

        queue[device] = {
            "device": device,
            "setting": setting,
            "generation": generation,
            "issued_epoch": now,
            "issued_at": timestamp(),
            "due_epoch": due_epoch,
            "due_at": timestamp(datetime.fromtimestamp(due_epoch)),
            "expires_epoch": due_epoch + ttl,
            "expires_at": timestamp(datetime.fromtimestamp(due_epoch + ttl)),
            "attempts": 0,
            "last_attempt": None,
            "last_error": None,
        }
    return queue


def _append_command_archive(entries: list[dict[str, Any]]) -> None:
    if not entries:
        return
    archive = _load_json(COMMANDS_ARCHIVE_PATH, default=[])
    if not isinstance(archive, list):
        archive = []
    archive.extend(entries)
    _atomic_write_json(archive, COMMANDS_ARCHIVE_PATH)


def _set_device(device: str, setting: int) -> bool:
    if device == "boiler":
        return bool(set_boiler_state(setting))
    return bool(set_pump_state(device.rsplit("_", 1)[1], setting))


def _execute_command_queue(
    queue: dict[str, dict[str, Any]],
    actual: dict[str, int | None],
    history: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any], bool]:
    now = time.time()
    results: dict[str, Any] = {}
    archived: list[dict[str, Any]] = []
    success = True

    order = [
        ("boiler", 0),
        ("pumps", 1),
        ("boiler", 1),
        ("pumps", 0),
    ]

    for device_type, setting in order:
        devices = [
            device
            for device, command in queue.items()
            if int(command["setting"]) == setting
            and ((device == "boiler") == (device_type == "boiler"))
        ]
        for device in sorted(devices):
            command = queue.get(device)
            if command is None or float(command["due_epoch"]) > now:
                continue
            if float(command["expires_epoch"]) <= now:
                _record_incident(
                    f"command_expired_{device}",
                    f"A fresh decision did not complete the {device} command before expiry",
                    3,
                )
                command["expired_at"] = timestamp()
                archived.append(command)
                del queue[device]
                success = False
                continue

            if device == "boiler" and setting == 1:
                if not any(
                    actual.get(f"pump_{cycle}") == 1 for cycle in get_cycles_info()
                ):
                    command["attempts"] = int(command.get("attempts", 0)) + 1
                    command["last_attempt"] = timestamp()
                    command["last_error"] = "no pump confirmed on"
                    results[device] = {"success": False, "error": command["last_error"]}
                    _record_incident(
                        "boiler_start_interlock",
                        "Boiler start was blocked because no pump was confirmed on",
                        3,
                    )
                    success = False
                    continue

            if device.startswith("pump_") and setting == 0 and actual.get("boiler") == 1:
                remaining_on = [
                    pump
                    for pump in (f"pump_{cycle}" for cycle in get_cycles_info())
                    if pump != device and actual.get(pump) == 1
                ]
                if not remaining_on:
                    command["last_error"] = "boiler still on; final pump stop postponed"
                    results[device] = {"success": False, "postponed": True, "error": command["last_error"]}
                    continue

            try:
                command["attempts"] = int(command.get("attempts", 0)) + 1
                command["last_attempt"] = timestamp()
                command_success = _set_device(device, setting)
                if not command_success:
                    raise RuntimeError("device did not confirm the requested state")
                actual[device] = setting
                history[device] = {
                    "state": setting,
                    "last_transition_epoch": time.time(),
                    "last_transition": timestamp(),
                }
                command["executed_at"] = timestamp()
                command["success"] = True
                archived.append(command)
                del queue[device]
                results[device] = {"success": True, "setting": setting}
            except Exception as error:
                command["last_error"] = str(error)
                results[device] = {"success": False, "setting": setting, "error": str(error)}
                _record_incident(
                    f"command_{device}",
                    f"{device} did not reach requested state {setting}",
                    3,
                    error,
                )
                success = False

    # An ON boiler without any confirmed circulation path is never allowed to persist.
    if actual.get("boiler") == 1 and not any(
        actual.get(f"pump_{cycle}") == 1 for cycle in get_cycles_info()
    ):
        try:
            emergency_success = _set_device("boiler", 0)
            if not emergency_success:
                raise RuntimeError("emergency boiler OFF was not confirmed")
            actual["boiler"] = 0
            history["boiler"] = {
                "state": 0,
                "last_transition_epoch": time.time(),
                "last_transition": timestamp(),
            }
            results["boiler_interlock"] = {"success": True, "setting": 0}
        except Exception as error:
            _record_incident(
                "boiler_emergency_off",
                "Boiler was on without a confirmed pump and emergency OFF failed",
                3,
                error,
            )
            results["boiler_interlock"] = {"success": False, "error": str(error)}
            success = False

    _append_command_archive(archived)
    return queue, results, success


def _apply_desired_state(
    desired: dict[str, int],
    actual: dict[str, int | None],
    runtime: dict[str, Any],
    force_shutdown: bool,
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, int | None], bool]:
    history = _initial_actuator_history(actual)
    generation = timestamp()
    queue = _reconcile_command_queue(
        desired,
        actual,
        history,
        runtime,
        generation,
        force_shutdown,
    )

    if dry_run:
        return {"dry_run": True, "planned_commands": queue}, actual, True

    _atomic_write_json(queue, COMMANDS_PATH)
    queue, results, success = _execute_command_queue(queue, actual, history)

    # A normal pump prestart is short enough to finish safely inside this
    # one-shot service.  Longer minimum-off delays remain queued for a later pass.
    pending_boiler = queue.get("boiler")
    if (
        pending_boiler
        and int(pending_boiler["setting"]) == 1
        and any(actual.get(f"pump_{cycle}") == 1 for cycle in get_cycles_info())
    ):
        wait_seconds = float(pending_boiler["due_epoch"]) - time.time()
        if 0 < wait_seconds <= float(runtime["pump_prestart_seconds"]) + 1.0:
            time.sleep(wait_seconds)
            queue, second_results, second_success = _execute_command_queue(
                queue,
                actual,
                history,
            )
            results.update(second_results)
            success = success and second_success

    _atomic_write_json(queue, COMMANDS_PATH)
    _atomic_write_json(history, ACTUATOR_HISTORY_PATH)
    return {
        "dry_run": False,
        "generation": generation,
        "results": results,
        "pending_commands": queue,
    }, actual, success


def _clear_stale_commands() -> None:
    try:
        old = _load_json(COMMANDS_PATH, default={})
        if old:
            now = timestamp()
            archived = []
            if isinstance(old, dict):
                archived = [dict(command, cancelled_at=now, cancellation_reason="invalid_control_snapshot") for command in old.values()]
            _append_command_archive(archived)
        _atomic_write_json({}, COMMANDS_PATH)
    except Exception as error:
        _record_incident("command_clear", "Could not clear stale V2 commands", 3, error)


def _write_heartbeat(runtime: dict[str, Any], mode: str) -> None:
    payload = json.dumps(
        {
            "epoch": time.time(),
            "timestamp": timestamp(),
            "mode": mode,
        },
        separators=(",", ":"),
    )
    _atomic_write_text(payload + "\n", str(runtime["heartbeat_path"]))


def _stage_telemetry(
    state: dict[str, Any],
    control: dict[str, Any],
    health: dict[str, Any],
) -> bool:
    try:
        _atomic_write_json(
            {
                "generation": timestamp(),
                "created_epoch": time.time(),
                "state": state,
                "control": control,
                "health": health,
            },
            TELEMETRY_OUTBOX_PATH,
        )
        return True
    except Exception as error:
        _record_incident(
            "telemetry_outbox",
            "Local control completed but its telemetry outbox could not be persisted",
            2,
            error,
        )
        return False


def _shutdown_trvs_if_due(runtime: dict[str, Any], dry_run: bool) -> dict[str, Any]:
    mode_state = _load_json(MODE_STATE_PATH, default={})
    now = time.time()
    last_check = float(mode_state.get("last_trv_shutdown_epoch", 0) or 0)
    transitioned = mode_state.get("last_mode") != "heating_off"
    due = transitioned or now - last_check >= float(runtime["off_mode_trv_check_minutes"]) * 60.0
    result: dict[str, Any] = {"due": due, "transitioned": transitioned}
    if due and not dry_run:
        try:
            thermostat_results = shutdown_all_thermostats(calibrate=False)
            success = all(item.get("success", False) for item in thermostat_results.values())
            result.update({"success": success, "thermostats": thermostat_results})
            if not success:
                _record_incident(
                    "off_mode_trv_shutdown",
                    "One or more thermostats did not confirm shutdown",
                    2,
                )
        except Exception as error:
            result.update({"success": False, "error": str(error)})
            _record_incident(
                "off_mode_trv_shutdown",
                "Thermostat shutdown watchdog failed",
                2,
                error,
            )
    elif due:
        result["success"] = True
        result["dry_run"] = True
    else:
        result["success"] = True

    if result.get("success"):
        mode_state["last_trv_shutdown_epoch"] = now if due else last_check
        mode_state["last_trv_shutdown"] = timestamp() if due else mode_state.get("last_trv_shutdown")
    mode_state["last_mode"] = "heating_off"
    mode_state["last_updated"] = timestamp()
    if not dry_run:
        _atomic_write_json(mode_state, MODE_STATE_PATH)
    return result


def _run_off_mode(
    runtime: dict[str, Any],
    cycles: dict[str, Any],
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    actual, actuator_health = _read_actuators(cycles)
    desired = {f"pump_{cycle}": 0 for cycle in cycles}
    desired["boiler"] = 0
    actuation, actual, actuator_success = _apply_desired_state(
        desired,
        actual,
        runtime,
        force_shutdown=True,
        dry_run=dry_run,
    )
    trv_shutdown = _shutdown_trvs_if_due(runtime, dry_run)
    critical_success = actuator_success and (dry_run or actual.get("boiler") == 0)
    state = {
        "mode": "heating_off",
        "pump_states": {cycle: actual.get(f"pump_{cycle}") for cycle in cycles},
        "boiler_state": actual.get("boiler"),
        "last_updated": timestamp(),
    }
    control = {
        "mode": "heating_off",
        "cycles": {cycle: 0 for cycle in cycles},
        "boiler": 0,
        "actuation": actuation,
        "TRV_shutdown": trv_shutdown,
        "last_updated": timestamp(),
    }
    health = {
        "decision_valid": True,
        "critical_actuation_success": critical_success,
        "actuators": actuator_health,
        "last_updated": timestamp(),
    }
    return state, control, health, critical_success


def _run_active_mode(
    switch: dict[str, Any],
    heating_config: dict[str, Any],
    runtime: dict[str, Any],
    rooms: dict[str, Any],
    cycles: dict[str, Any],
    schedule: dict[str, Any],
    schedule_path: str,
    dry_run: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bool]:
    started = time.time()
    room_inputs, room_health = _build_room_inputs(rooms, heating_config, runtime)
    occupancy, occupancy_health = _read_occupancy(rooms)
    schedule_values, schedule_health = _schedule_values(schedule, rooms, runtime)
    previous_room_states = _load_previous_room_states(rooms)
    actual, actuator_health = _read_actuators(cycles)

    control, room_votes, pump_votes, decision_health = _vote_rooms(
        rooms,
        switch,
        schedule_values,
        room_inputs,
        occupancy,
        previous_room_states,
        heating_config,
        runtime,
        dry_run,
    )
    decision_valid = decision_health["usable_rooms"] > 0

    if not decision_valid:
        _clear_stale_commands()
        actuation = {"skipped": True, "reason": "no usable room schedule"}
        actuation_success = False
    else:
        desired = {f"pump_{cycle}": vote for cycle, vote in pump_votes.items()}
        desired["boiler"] = int(any(pump_votes.values()))
        actuation, actual, actuation_success = _apply_desired_state(
            desired,
            actual,
            runtime,
            force_shutdown=False,
            dry_run=dry_run,
        )

    mode_state = _load_json(MODE_STATE_PATH, default={})
    mode_state.update({"last_mode": "heating_active", "last_updated": timestamp()})
    if not dry_run:
        _atomic_write_json(mode_state, MODE_STATE_PATH)

    public_inputs = {key: value for key, value in room_inputs.items() if key != "_thermostats"}
    state = {
        "mode": "heating_active",
        "room_inputs": public_inputs,
        "set_temps": {room: values["nominal"] for room, values in schedule_values.items()},
        "set_temps_interp": {room: values["interpolated"] for room, values in schedule_values.items()},
        "occupancy": occupancy,
        "room_states": room_votes,
        "pump_states": {cycle: actual.get(f"pump_{cycle}") for cycle in cycles},
        "boiler_state": actual.get("boiler"),
        "last_updated": timestamp(),
    }
    control["actuation"] = actuation
    health = {
        "decision_valid": decision_valid,
        "critical_actuation_success": actuation_success,
        "schedule": {
            **schedule_health,
            "path": schedule_path,
            "age_hours": _schedule_age_hours(schedule_path),
        },
        "rooms": room_health,
        "occupancy": occupancy_health,
        "actuators": actuator_health,
        "duration_seconds": time.time() - started,
        "last_updated": timestamp(),
    }
    return state, control, health, decision_valid and actuation_success


def main() -> int:
    settings["log"] = True
    settings["verbosity"] = True
    started = time.time()
    dry_run = os.environ.get("HEATING_V2_DRY_RUN", "0").strip().lower() in {
        "1",
        "true",
        "yes",
    }

    try:
        runtime = _load_runtime_config()
        switch, switch_path = _load_first(HEATING_SWITCH_PATHS)
        cycles = get_cycles_info()
        _validate_switch(switch, cycles)
    except Exception as error:
        _clear_stale_commands()
        _record_incident("initialization", "V2 local configuration could not be loaded", 3, error)
        health = {
            "decision_valid": False,
            "critical_actuation_success": False,
            "error": str(error),
            "last_updated": timestamp(),
        }
        try:
            _atomic_write_json(health, HEALTH_PATH)
        except Exception:
            pass
        return 2

    heating_config_path: str | None = None
    try:
        if int(switch.get("system", 0)) == 0:
            state, control, health, success = _run_off_mode(runtime, cycles, dry_run)
        else:
            heating_config, heating_config_path = _load_first(HEATING_CONFIG_PATHS)
            rooms = get_rooms_info()
            _validate_switch(switch, cycles, rooms)
            _validate_heating_config(heating_config, rooms)
            schedule, schedule_path = _load_first(SCHEDULE_PATHS)
            schedule_age_hours = _schedule_age_hours(schedule_path)
            if schedule_age_hours > float(runtime["schedule_hard_expiry_hours"]):
                raise RuntimeError(
                    f"last-known-good schedule is {schedule_age_hours:.1f} hours old"
                )
            if schedule_age_hours > float(runtime["schedule_warning_age_hours"]):
                _record_incident(
                    "schedule_stale",
                    f"V2 schedule is stale but remains inside its hard validity horizon ({schedule_age_hours:.1f} hours)",
                    2,
                )
            state, control, health, success = _run_active_mode(
                switch,
                heating_config,
                runtime,
                rooms,
                cycles,
                schedule,
                schedule_path,
                dry_run,
            )
    except Exception as error:
        _clear_stale_commands()
        _record_incident("control_pass", "V2 could not form or apply a safe control decision", 3, error)
        state = {
            "mode": "control_invalid",
            "last_updated": timestamp(),
            "error": str(error),
        }
        control = {
            "skipped": True,
            "reason": "invalid control pass",
            "last_updated": timestamp(),
        }
        health = {
            "decision_valid": False,
            "critical_actuation_success": False,
            "error": str(error),
            "duration_seconds": time.time() - started,
            "last_updated": timestamp(),
        }
        success = False

    health.update(
        {
            "dry_run": dry_run,
            "switch_path": switch_path,
            "heating_config_path": heating_config_path,
            "duration_seconds": time.time() - started,
        }
    )

    try:
        _atomic_write_json(state, STATE_PATH)
        _atomic_write_json(control, CONTROL_PATH)
        _atomic_write_json(health, HEALTH_PATH)
    except Exception as error:
        _record_incident("local_state_export", "V2 could not atomically persist its local state", 3, error)
        success = False

    if success and not dry_run:
        try:
            _write_heartbeat(runtime, state["mode"])
            health["heartbeat_updated"] = True
        except Exception as error:
            health["heartbeat_updated"] = False
            _record_incident("heartbeat", "V2 safety heartbeat could not be updated", 3, error)
            success = False

    health["telemetry_staged"] = _stage_telemetry(
        state,
        control,
        health,
    )
    try:
        _atomic_write_json(health, HEALTH_PATH)
    except Exception:
        pass

    report(
        f"Heating V2 pass completed: mode={state.get('mode')}, success={success}, dry_run={dry_run}."
    )
    return 0 if success else 3


if __name__ == "__main__":
    sys.exit(main())
