import csv
import json
from datetime import date, datetime
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import perf_counter, sleep

import duckdb

BATCH_FILE_COUNT = 10
IMPORT_EXISTING_POLICIES = {"skip_existing", "replace_existing", "fail_on_existing"}
IMPORT_INTERRUPTED = False
DUCKDB_CONNECT_RETRY_SECONDS = 180
DUCKDB_CONNECT_RETRY_INTERVAL_SECONDS = 2

SCRIPT_PATH = Path(__file__).resolve()
DEV_PATH = SCRIPT_PATH.parent.parent
PROJECT_PATH = DEV_PATH.parent

DB_PATH = DEV_PATH / "db" / "store" / "observations.duckdb"
LOG_PATH = PROJECT_PATH / "data" / "logs"
SETUP_PATH = PROJECT_PATH / "system" / "setup.json"
SCOPE_LIST_PATH = SCRIPT_PATH.parent / "metadata" / "scope_list.csv"

SOURCE_FILES = {
    "aqara_and_nous": ("aqara_and_nous", "aqara_and_nous.json"),
    "electric_main_meter": ("electricity", "main_meter.json"),
    "electric_submeters": ("electricity", "submeters.json"),
    "external_temp": ("external_temp", "external_temp.json"),
    "gas_impulses": ("gas_consumption", "gas_relay_turns.json"),
    "heatmeters": ("heat_delivery", "heatmeters_state.json"),
    "heating_control": (
        "service_execution/heating_control",
        "heating_control.json",
    ),
    "occupancy": ("occupancy", "occupancy.json"),
    "open_close": ("open_close", "open_close_events.json"),
    "oktopusz_presence": ("presence", "oktopusz_presence.json"),
    "presence_all": ("presence", "presence_all.json"),
    "pumps": ("pumps", "power.json"),
    "pv_inverter": ("electricity", "pv_inverter.json"),
    "radiator_temperatures": ("radiator_temps", "radiator_temps.json"),
    "thermostats": ("thermostats", "thermostats_state.json"),
    "temperature_and_humidity": (
        "temperature_and_humidity",
        "temperature_and_humidity.json",
    ),
    "weather_station": ("weather_station", "weather_station.json"),
}


# Device-to-stream mappings. These are intentionally explicit and easy to edit.

AQARA_ROOM_MAP = {
    "Aqara1": "2",
    "Aqara2": "4",
    "Aqara3": "1",
    "Aqara4": "1",
    "Aqara5": "16",
    "Aqara6": "13",
    "Aqara7": "11",
    "Aqara8": "18",
    "Aqara9": "6",
    "Aqara10": "24",
    "Aqara11": "12",
    "Aqara12": "11",
    "Aqara13": "3",
    "Aqara14": "5",
    "Aqara15": "7",
    "Aqara16": "5",
    "Aqara17": "25",
    "Aqara18": "17",
}

NOUS_ROOM_MAP = {
    "Nous1": "13",
    "Nous2": "12",
    "Nous3": "2",
    "Nous4": "17",
    "Nous5": "3",
    "Nous6": "1",
    "Nous7": "7",
    "Nous8": "6",
    "Nous9": "5",
    "Nous10": "4"
}

AQARA_FIELD_MAP = {
    "temp": "temperature",
    "hum": "humidity",
    "presence": "occupancy_state",
    "lux": "illuminance",
}

NOUS_FIELD_MAP = {
    "co2": "co2",
}

OPEN_CLOSE_STREAM_MAP = {
    "gep_muhely_ablak": "window.13.1.state",
    "gep_muhely_ajto": "door.13.1.state",
    "golyairoda_ablak_2": "window.7.1.state",
    "golyairoda_ajto": "door.7.1.state",
    "kisudvar_ajto": "door.17.1.state",
    "merce_ablak_1": "window.5.1.state",
    "merce_ablak_2": "window.5.2.state",
    "merce_ablak_3": "window.5.3.state",
    "merce_ablak_4": "window.5.4.state",
    "merce_ablak_5": "window.5.5.state",
    "merce_ablak_6": "window.5.6.state",
    "merce_ablak_7": "window.5.7.state",
    "merce_ablak_8": "window.5.8.state",
    "merce_ajto": "door.5.1.state",
    "merce_targyalo_ajto": "door.12.1.state",
    "oktopusz_keramia_ajto": "door.11.1.state",
    "oktopusz_szita_ablak": "window.1.1.state",
    "oktopusz_szita_ajto": "door.1.1.state",
    "ovi_ablak_1": "window.2.1.state",
    "ovi_ablak_2": "window.2.2.state",
    "ovi_ablak_3": "window.2.3.state",
    "ovi_ablak_4": "window.2.4.state",
    "ovi_ablak_5": "window.2.5.state",
    "ovi_ablak_6": "window.2.6.state",
    "ovi_ablak_7": "window.2.7.state",
    "ovi_ablak_8": "window.2.8.state",
    "ovi_ajto_1": "door.2.1.state",
    "ovi_ajto_2": "door.2.2.state",
    "pk_ablak_1": "window.3.1.state",
    "pk_ablak_2": "window.3.2.state",
    "pk_ablak_3": "window.3.3.state",
    "pk_ablak_4": "window.3.4.state",
    "pk_ajto": "door.3.1.state",
    "studio_ajto": "door.6.1.state",
    "szgk_ablak_1": "window.4.1.state",
    "szgk_ablak_2": "window.4.2.state",
    "szgk_ablak_3": "window.4.3.state",
    "szgk_ablak_4": "window.4.4.state",
    "szgk_ajto": "door.4.1.state",
    "tuzzaro_ajto": "door.24.1.state",
    "zsilipajto": "door.25.2.state",
}

ELECTRIC_SUBMETER_SCOPE_MAP = {
    "edzoterem": "oktopusz_szita",
    "golya": "golyairoda",
    "keramia": "oktopusz_keramia",
    "merce": "merce",
    "ovi": "golyafeszek",
    "pk": "pk",
    "studio": "studio",
    "szgk": "szgk",
    "hm division": "pk"
}

RADIATOR_TEMPERATURE_STREAM_MAP = {
    ("golya_radiatorok_shelly", "gólya1"): "radiator.7.1.temperature",
    ("golya_radiatorok_shelly", "gólya2"): "radiator.7.2.temperature",
    ("szgk_radiator_shelly", "temperature:100"): "radiator.4.1.temperature",
    ("pk_radiatorok_shelly", "temperature:100"): "radiator.3.1.temperature",
    ("pk_radiatorok_shelly", "temperature:101"): "radiator.3.2.temperature",
    ("oktopusz_1_radiator_shelly", "temperature:100"): "radiator.1.1.temperature",
    ("oktopusz_2_radiator_shelly", "temperature:100"): "radiator.1.2.temperature",
    ("gep_radiator_shelly", "temperature:100"): "radiator.13.1.temperature",
    ("merce_radiatorok_1_shelly", "temperature:100"): "radiator.5.1.temperature",
    ("merce_radiatorok_2_shelly", "temperature:100"): "radiator.12.1.temperature",
    ("merce_radiatorok_2_shelly", "temperature:101"): "radiator.12.2.temperature",
    ("merce_radiatorok_2_shelly", "temperature:102"): "radiator.12.3.temperature",
    ("ovi_radiatorok_shelly", "temperature:100"): "radiator.2.1.temperature",
    ("ovi_radiatorok_shelly", "temperature:101"): "radiator.2.2.temperature",
    ("ovi_radiatorok_shelly", "temperature:102"): "radiator.2.3.temperature",
    ("ovi_radiatorok_shelly", "temperature:103"): "radiator.2.4.temperature",
    ("studio_radiator_shelly", "temperature:100"): "radiator.6.1.temperature",
}

# Thermostat log names are historical valve labels, not reliable room labels.
# Resolve log labels to thermostat IDs first, then use system/setup.json for rooms.
THERMOSTAT_LOG_NAME_TO_ID = {
    "PK": "42",
    "Merce_targyalo": "53",
    "Merce": "57",
    "SZGK": "59",
    "GEP_muhely": "63",
    "Golyairoda": "65",
    "Lahmacun": "69",
    "Golyafeszek_1": "71",
    "Golyafeszek_2": "75",
    "Oktopusz_szita_1": "77",
    "Oktopusz_szita_2": "79",
}


def radiator_scope_sort_key(scope_id):
    return tuple(int(part) for part in scope_id.split("."))


def load_radiator_scope_ids_by_room():
    radiator_scope_ids_by_room = {}

    with SCOPE_LIST_PATH.open(newline="", encoding="utf-8") as file:
        for row in csv.DictReader(file):
            if row["scope_type"] != "radiator":
                continue

            room_id = row["scope_id"].split(".", 1)[0]
            radiator_scope_ids_by_room.setdefault(room_id, []).append(row["scope_id"])

    for radiator_scope_ids in radiator_scope_ids_by_room.values():
        radiator_scope_ids.sort(key=radiator_scope_sort_key)

    return radiator_scope_ids_by_room


def thermostat_ids_from_setup_value(value):
    if not isinstance(value, str):
        return []

    return [part.strip() for part in value.split(";") if part.strip()]


def build_thermostat_id_to_radiator_scope_map():
    with SETUP_PATH.open(encoding="utf-8") as file:
        setup = json.load(file)

    radiator_scope_ids_by_room = load_radiator_scope_ids_by_room()
    thermostat_id_to_radiator_scope = {}

    for room_id, room_config in setup.get("rooms", {}).items():
        thermostat_ids = thermostat_ids_from_setup_value(
            room_config.get("thermostats")
        )
        if not thermostat_ids:
            continue

        radiator_scope_ids = radiator_scope_ids_by_room.get(room_id, [])
        if not radiator_scope_ids:
            continue

        for index, thermostat_id in enumerate(thermostat_ids):
            radiator_index = min(
                index * len(radiator_scope_ids) // len(thermostat_ids),
                len(radiator_scope_ids) - 1,
            )
            thermostat_id_to_radiator_scope[thermostat_id] = radiator_scope_ids[
                radiator_index
            ]

    return thermostat_id_to_radiator_scope


def thermostat_id_from_log_entry(log_key, state):
    log_key = str(log_key)

    if log_key.isdigit():
        return log_key

    if log_key in THERMOSTAT_LOG_NAME_TO_ID:
        return THERMOSTAT_LOG_NAME_TO_ID[log_key]

    if log_key.startswith("Thermostat "):
        suffix = log_key.removeprefix("Thermostat ").strip()
        if suffix.isdigit():
            return suffix

    if isinstance(state, dict):
        state_name = state.get("name")
        if state_name in THERMOSTAT_LOG_NAME_TO_ID:
            return THERMOSTAT_LOG_NAME_TO_ID[state_name]

    return None


THERMOSTAT_ID_TO_RADIATOR_SCOPE_MAP = build_thermostat_id_to_radiator_scope_map()

# Historical scratch map only; heating-control logs are not a valve-state source.
DEPRECATED_HEATING_CONTROL_VALVE_STREAM_MAP = {
    # Oktopusz: two radiators, each with its own TRV
    "1": [
        "radiator.1.1.valve_state",
        "radiator.1.2.valve_state",
    ],

    # Gólyafészek: four radiators, two TRV chains
    # TRV 1 controls radiators 2.1-2.2, stored on master radiator 2.1
    # TRV 2 controls radiators 2.3-2.4, stored on master radiator 2.3
    "2": [
        "radiator.2.1.valve_state",
        "radiator.2.3.valve_state",
    ],
    "3": ["radiator.3.1.valve_state"],
    "4": ["radiator.4.1.valve_state"],
    "5": ["radiator.5.1.valve_state"],
    "6": ["radiator.6.1.valve_state"],
    "7": ["radiator.7.1.valve_state"],
    "12": ["radiator.12.1.valve_state"],
    "13": ["radiator.13.1.valve_state"],
}


MAIN_METER_FIELD_MAP = {
    "active_power_w": ("electric_main_meter.main.active_power", 1),
    "total_power_import_kwh": ("electric_main_meter.main.total_power_import", 1),
    "total_power_import_t1_kwh": ("electric_main_meter.main.total_power_import_t1", 1),
    "total_power_import_t2_kwh": ("electric_main_meter.main.total_power_import_t2", 1),
    "total_power_import_t3_kwh": ("electric_main_meter.main.total_power_import_t3", 1),
    "total_power_import_t4_kwh": ("electric_main_meter.main.total_power_import_t4", 1),
    "total_power_export_kwh": ("electric_main_meter.main.total_power_export", 1),
    "total_power_export_t1_kwh": ("electric_main_meter.main.total_power_export_t1", 1),
    "total_power_export_t2_kwh": ("electric_main_meter.main.total_power_export_t2", 1),
    "total_power_export_t3_kwh": ("electric_main_meter.main.total_power_export_t3", 1),
    "total_power_export_t4_kwh": ("electric_main_meter.main.total_power_export_t4", 1),
    "active_voltage_l1_v": ("electric_main_meter.main.active_voltage_l1", 1),
    "active_voltage_l2_v": ("electric_main_meter.main.active_voltage_l2", 1),
    "active_voltage_l3_v": ("electric_main_meter.main.active_voltage_l3", 1),
    "active_current_l1_a": ("electric_main_meter.main.active_current_l1", 1),
    "active_current_l2_a": ("electric_main_meter.main.active_current_l2", 1),
    "active_current_l3_a": ("electric_main_meter.main.active_current_l3", 1),
    "active_tariff": ("electric_main_meter.main.active_tariff", 1),
}

PV_FIELD_MAP = {
    "phase_a_voltage_v": ("pv.inverter.phase_a_voltage", 1),
    "phase_b_voltage_v": ("pv.inverter.phase_b_voltage", 1),
    "phase_c_voltage_v": ("pv.inverter.phase_c_voltage", 1),
    "grid_current_grid_phase_a_current_a": ("pv.inverter.grid_phase_a_current", 1),
    "phase_b_current_a": ("pv.inverter.phase_b_current", 1),
    "phase_c_current_a": ("pv.inverter.phase_c_current", 1),
    "power_factor": ("pv.inverter.power_factor", 1),
    "grid_frequency_hz": ("pv.inverter.grid_frequency", 1),
    "active_power_kw": ("pv.inverter.production", 1),
    "output_reactive_power_kvar": ("pv.inverter.output_reactive_power", 1),
    "daily_energy_kwh": ("pv.inverter.daily_energy", 1),
    "total_input_power_kw": ("pv.inverter.total_input_power", 1),
    "pv1_input_voltage_v": ("pv.inverter.pv1_input_voltage", 1),
    "pv1_input_current_a": ("pv.inverter.pv1_input_current", 1),
    "pv2_input_voltage_v": ("pv.inverter.pv2_input_voltage", 1),
    "pv2_input_current_a": ("pv.inverter.pv2_input_current", 1),
    "pv3_input_voltage_v": ("pv.inverter.pv3_input_voltage", 1),
    "pv3_input_current_a": ("pv.inverter.pv3_input_current", 1),
    "pv4_input_voltage_v": ("pv.inverter.pv4_input_voltage", 1),
    "pv4_input_current_a": ("pv.inverter.pv4_input_current", 1),
    "pv5_input_voltage_v": ("pv.inverter.pv5_input_voltage", 1),
    "pv5_input_current_a": ("pv.inverter.pv5_input_current", 1),
    "pv6_input_voltage_v": ("pv.inverter.pv6_input_voltage", 1),
    "pv6_input_current_a": ("pv.inverter.pv6_input_current", 1),
    "pv7_input_voltage_v": ("pv.inverter.pv7_input_voltage", 1),
    "pv7_input_current_a": ("pv.inverter.pv7_input_current", 1),
    "pv8_input_voltage_v": ("pv.inverter.pv8_input_voltage", 1),
    "pv8_input_current_a": ("pv.inverter.pv8_input_current", 1),
    "mppt_1_dc_cumulative_energy_kwh": (
        "pv.inverter.mppt_1_dc_cumulative_energy",
        1,
    ),
    "mppt_2_dc_cumulative_energy_kwh": (
        "pv.inverter.mppt_2_dc_cumulative_energy",
        1,
    ),
    "mppt_3_dc_cumulative_energy_kwh": (
        "pv.inverter.mppt_3_dc_cumulative_energy",
        1,
    ),
    "mppt_4_dc_cumulative_energy_kwh": (
        "pv.inverter.mppt_4_dc_cumulative_energy",
        1,
    ),
}

WEATHER_STATION_FIELD_MAP = {
    "temperature_c": ("weather_station.ws90.temperature", 1),
    "humidity_pct": ("weather_station.ws90.humidity", 1),
    "dewpoint_c": ("weather_station.ws90.dewpoint", 1),
    "illuminance_lux": ("weather_station.ws90.illuminance", 1),
    "rain_status": ("weather_station.ws90.rain_status", 1),
    "wind_speed_m_s": ("weather_station.ws90.wind_speed", 1),
    "gust_speed_m_s": ("weather_station.ws90.gust_speed", 1),
    "uv_index": ("weather_station.ws90.uv_index", 1),
    "wind_direction_deg": ("weather_station.ws90.wind_direction", 1),
}

HEATMETER_FIELD_MAP = {
    # The raw key says kWh, but sampled values look like Wh. Store canonical kWh.
    "energy_kwh": ("energy", 1000),
    "volume_m3": ("volume", 1),
    "power_w": ("power", 1),
    "volume_flow_m3h": ("volume_flow", 1),
    "flow_temperature_c": ("flow_temperature", 1),
    "return_temperature_c": ("return_temperature", 1),
}

SOURCE_REDUCTION_POLICIES = {
    # Source-update timestamps are available; repeated archive snapshots should
    # not create duplicate analytical rows.
    "temperature_and_humidity": "exact",
    "weather_station": "exact",

    # These sources are state/gauge snapshots. Keep analytical change points,
    # not every logger poll that repeats the same value.
    "aqara_and_nous": "changes",
    "electric_main_meter": "changes",
    "external_temp": "changes",
    "heatmeters": "changes",
    "heating_control": "changes",
    "occupancy": "changes",
    "oktopusz_presence": "changes",
    "presence_all": "changes",
    "pumps": "changes",
    "pv_inverter": "changes",
    "radiator_temperatures": "changes",
    "thermostats": "changes",
}


MODE_DESCRIPTIONS = {
    "list_modes": "print available modes",
    "import_aqara_and_nous": "Aqara room readings and Nous CO2 from Aqara/Nous logs",
    "import_electric_main_meter": "main electric meter values",
    "import_electric_submeter_impulses": "electric submeter impulse events",
    "import_gas_impulses": "gas meter impulse events",
    "import_heatmeters": "heating-cycle heatmeter readings",
    "import_heating_control_state": "room set temperatures and actual heating states from heating-control logs",
    "import_oktopusz_presence": "legacy Oktopusz presence boolean",
    "import_open_close": "door/window open-close state events",
    "import_outdoor_weather_com": "Weather.com outdoor temperature scrape",
    "import_room_presence": "raw room presence_detected readings from presence_all logs",
    "import_pump_power": "heating-cycle pump power readings",
    "import_pv_inverter": "PV inverter readings",
    "import_radiator_temperatures": "radiator Shelly temperature readings",
    "import_radiator_thermostats": "radiator thermostat valve readings",
    "import_room_occupancy": "room occupancy state readings",
    "import_room_temperature_humidity": "legacy room temperature/humidity readings",
    "import_weather_station": "WS90 weather station readings",
}


def is_duckdb_file_lock_error(error):
    message = str(error).lower()
    return (
        "cannot open file" in message
        and (
            "used by another process" in message
            or "file is already open" in message
        )
    )


def connect(read_only=False):
    started_at = perf_counter()
    next_report_at = 0
    attempts = 0

    while True:
        attempts += 1
        try:
            return duckdb.connect(str(DB_PATH), read_only=read_only)
        except Exception as error:
            if not is_duckdb_file_lock_error(error):
                raise

            elapsed = perf_counter() - started_at
            if elapsed >= DUCKDB_CONNECT_RETRY_SECONDS:
                raise

            if elapsed >= next_report_at:
                mode = "read-only" if read_only else "read-write"
                output(
                    "DuckDB file is locked; "
                    f"waiting to open {mode} connection "
                    f"(attempt {attempts}, elapsed {format_seconds(elapsed)})"
                )
                next_report_at = elapsed + 10

            sleep(DUCKDB_CONNECT_RETRY_INTERVAL_SECONDS)


def output(message):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {message}", flush=True)


def report(message):
    if REPORT_PROGRESS:
        output(message)


def format_seconds(seconds):
    if seconds < 60:
        return f"{seconds:.1f}s"

    minutes = int(seconds // 60)
    remaining_seconds = seconds % 60
    return f"{minutes}m {remaining_seconds:.0f}s"


def should_report_file_progress(index, total):
    if REPORT_FILE_DETAILS or index == 1 or index == total:
        return True

    return (
        REPORT_EVERY_FILES is not None
        and REPORT_EVERY_FILES > 0
        and index % REPORT_EVERY_FILES == 0
    )


_STREAM_ID_FILTER_SOURCE = object()
_STREAM_ID_FILTER_SET = None


def configured_stream_id_filter():
    global _STREAM_ID_FILTER_SOURCE
    global _STREAM_ID_FILTER_SET

    if STREAM_ID_FILTER is _STREAM_ID_FILTER_SOURCE:
        return _STREAM_ID_FILTER_SET

    _STREAM_ID_FILTER_SOURCE = STREAM_ID_FILTER

    if STREAM_ID_FILTER is None:
        _STREAM_ID_FILTER_SET = None
    elif isinstance(STREAM_ID_FILTER, str):
        _STREAM_ID_FILTER_SET = {STREAM_ID_FILTER}
    else:
        _STREAM_ID_FILTER_SET = set(STREAM_ID_FILTER)

    return _STREAM_ID_FILTER_SET


def stream_id_is_selected(target_stream_id):
    stream_id_filter = configured_stream_id_filter()
    return stream_id_filter is None or target_stream_id in stream_id_filter


def validate_import_config():
    if IMPORT_EXISTING_POLICY not in IMPORT_EXISTING_POLICIES:
        allowed_policies = ", ".join(sorted(IMPORT_EXISTING_POLICIES))
        raise ValueError(
            f"invalid IMPORT_EXISTING_POLICY {IMPORT_EXISTING_POLICY!r}; "
            f"expected one of: {allowed_policies}"
        )

    configured_stream_id_filter()


def log_day_from_path(path):
    try:
        return parse_day(path.name.rsplit(".", 1)[-1])
    except ValueError:
        return None


def report_interrupted_import(
    source_name,
    paths,
    last_committed_index,
    current_index,
    phase,
    parsed_count,
    inserted_count,
    skipped_existing_count,
    pending_row_count,
    source_reduced_count=0,
):
    output("import interrupted by Ctrl+C")
    output(f"source: {source_name}")
    output(f"interrupted while: {phase}")
    output(f"selected files: {len(paths)}")
    output(f"last fully committed file index: {last_committed_index}/{len(paths)}")

    if last_committed_index > 0:
        output(f"last fully committed file: {paths[last_committed_index - 1]}")
    else:
        output("last fully committed file: none")

    output(f"files parsed in this run: {current_index}")
    output(f"observations parsed in this run: {parsed_count}")
    output(f"observations dropped by source reduction: {source_reduced_count}")
    output(f"observations inserted in completed batches: {inserted_count}")
    output(f"existing observations skipped in completed batches: {skipped_existing_count}")
    output(f"pending uncommitted rows discarded: {pending_row_count}")

    next_index = last_committed_index + 1
    if next_index > len(paths):
        output("restart hint: all selected files were committed before interruption")
        return

    next_path = paths[next_index - 1]
    next_day = log_day_from_path(next_path)
    output(f"next uncommitted file: {next_path}")

    if next_day is None:
        output("restart hint: next file is the current unsuffixed log; keep INCLUDE_CURRENT_LOG = True")
    else:
        output(f"restart hint: set START_DATE = \"{next_day.isoformat()}\"")


def parse_day(day_text):
    if day_text is None:
        return None
    return date.fromisoformat(day_text)


def parse_timestamp(timestamp_text):
    if timestamp_text is None:
        return None

    if str(timestamp_text).lower() == "none":
        return None

    for timestamp_format in ("%Y-%m-%d-%H-%M-%S", "%Y-%m-%d-%H-%M"):
        try:
            return datetime.strptime(timestamp_text, timestamp_format)
        except ValueError:
            pass

    raise ValueError(
        f"time data {timestamp_text!r} does not match supported timestamp formats"
    )


def dated_log_paths(source_name):
    directory_name, file_name = SOURCE_FILES[source_name]
    directory = LOG_PATH / directory_name
    paths = []

    for path in directory.glob(f"{file_name}.*"):
        day_text = path.name.rsplit(".", 1)[-1]

        try:
            day = parse_day(day_text)
        except ValueError:
            continue

        paths.append((day, path))

    return sorted(paths)


def source_paths(source_name, start_day, end_day, include_current):
    directory_name, file_name = SOURCE_FILES[source_name]
    directory = LOG_PATH / directory_name
    paths = []

    for day, path in dated_log_paths(source_name):
        if start_day is not None and day < start_day:
            continue

        if end_day is not None and day > end_day:
            continue

        paths.append(path)

    if include_current:
        current_path = directory / file_name
        if current_path.exists():
            paths.append(current_path)

    return paths


def configured_source_paths(source_name):
    return source_paths(
        source_name=source_name,
        start_day=parse_day(START_DATE),
        end_day=parse_day(END_DATE),
        include_current=INCLUDE_CURRENT_LOG,
    )


def iter_ndjson(path):
    decode_error_count = 0
    decode_error_report_limit = 5

    with path.open("rb") as file:
        for line_number, raw_line in enumerate(file, start=1):
            raw_line = raw_line.strip()
            if not raw_line:
                continue

            try:
                line = raw_line.decode("utf-8")
            except UnicodeDecodeError as error:
                decode_error_count += 1
                if decode_error_count <= decode_error_report_limit:
                    output(
                        f"skipped undecodable line in {path} "
                        f"line {line_number}: {error}"
                    )
                elif decode_error_count == decode_error_report_limit + 1:
                    output(f"further undecodable lines in {path} suppressed")
                continue

            line = line.strip()
            if not line:
                continue

            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                output(f"skipped invalid JSON in {path} line {line_number}: {error}")

    if decode_error_count > decode_error_report_limit:
        output(f"skipped {decode_error_count} undecodable lines in {path}")


def clean_value(value, scale=1):
    if value is None:
        return None

    if isinstance(value, bool):
        return 1.0 if value else 0.0

    return float(value) / scale


def add_row(rows_by_key, timestamp, stream_id, value, scale=1):
    if timestamp is None or stream_id is None or value is None:
        return

    if not stream_id_is_selected(stream_id):
        return

    rows_by_key[(timestamp, stream_id)] = (
        timestamp,
        stream_id,
        clean_value(value, scale),
    )


def append_row(rows, timestamp, stream_id, value, scale=1, reduction_key=None):
    if timestamp is None or stream_id is None or value is None:
        return

    if not stream_id_is_selected(stream_id):
        return

    row = (timestamp, stream_id, clean_value(value, scale))
    if reduction_key is not None:
        row = (*row, reduction_key)

    rows.append(row)


def stream_id(scope_type, scope_id, variable):
    return f"{scope_type}.{scope_id}.{variable}"


def rows_from_mapping_file(path, field_map, timestamp_key="timestamp", state_key=None):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get(timestamp_key))
        values = record.get(state_key, {}) if state_key else record

        if not isinstance(values, dict):
            continue

        for raw_key, (target_stream_id, scale) in field_map.items():
            add_row(
                rows_by_key,
                timestamp,
                target_stream_id,
                values.get(raw_key),
                scale,
            )

    return sorted(rows_by_key.values())


def parse_room_temperature_humidity_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        for raw_room_id, state in record.items():
            if raw_room_id == "timestamp" or not isinstance(state, dict):
                continue

            timestamp = parse_timestamp(state.get("last_updated"))
            add_row(
                rows_by_key,
                timestamp,
                stream_id("room", raw_room_id, "temperature"),
                state.get("temp"),
                100,
            )
            add_row(
                rows_by_key,
                timestamp,
                stream_id("room", raw_room_id, "humidity"),
                state.get("hum"),
                100,
            )

    return sorted(rows_by_key.values())


def parse_aqara_and_nous_file(path):
    rows = []
    occupancy_rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))
        states = record.get("states", {})

        for device_name, state in states.get("aqara", {}).items():
            room_id = AQARA_ROOM_MAP.get(device_name)
            if room_id is None:
                continue

            for raw_key, variable in AQARA_FIELD_MAP.items():
                target_stream_id = stream_id("room", room_id, variable)
                if variable == "occupancy_state":
                    value = state.get(raw_key)
                    if (
                        timestamp is None
                        or value is None
                        or not stream_id_is_selected(target_stream_id)
                    ):
                        continue

                    key = (timestamp, target_stream_id)
                    current = occupancy_rows_by_key.get(key)
                    next_value = clean_value(value)
                    if current is None or next_value > current[2]:
                        occupancy_rows_by_key[key] = (
                            timestamp,
                            target_stream_id,
                            next_value,
                        )
                else:
                    append_row(
                        rows,
                        timestamp,
                        target_stream_id,
                        state.get(raw_key),
                        reduction_key=("aqara", device_name, variable),
                    )

        for device_name, state in states.get("nous", {}).items():
            room_id = NOUS_ROOM_MAP.get(device_name)
            if room_id is None:
                continue

            for raw_key, variable in NOUS_FIELD_MAP.items():
                append_row(
                    rows,
                    timestamp,
                    stream_id("room", room_id, variable),
                    state.get(raw_key),
                    reduction_key=("nous", device_name, variable),
                )

    rows.extend(occupancy_rows_by_key.values())
    return sorted(rows)


def parse_occupancy_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))
        states = record.get("states", {})

        for room_id, value in states.items():
            add_row(
                rows_by_key,
                timestamp,
                stream_id("room", room_id, "occupancy_state"),
                value,
            )

    return sorted(rows_by_key.values())


def parse_oktopusz_presence_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(
            record.get("last_updated") or record.get("timestamp")
        )
        add_row(
            rows_by_key,
            timestamp,
            "room.1.presence_detected",
            record.get("presence"),
        )

    return sorted(rows_by_key.values())


def parse_presence_all_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        fallback_timestamp = parse_timestamp(record.get("timestamp"))
        states = record.get("states", {})

        for room_id, state in states.items():
            if not isinstance(state, dict):
                continue

            if state.get("reachable") is not True:
                continue

            timestamp = parse_timestamp(state.get("last_updated")) or fallback_timestamp
            add_row(
                rows_by_key,
                timestamp,
                stream_id("room", room_id, "presence_detected"),
                state.get("state"),
            )

    return sorted(rows_by_key.values())


def parse_open_close_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))
        target_stream_id = OPEN_CLOSE_STREAM_MAP.get(record.get("sensor_name"))
        state = record.get("state")

        if state == "open":
            value = 1.0
        elif state == "closed":
            value = 0.0
        else:
            value = None

        add_row(rows_by_key, timestamp, target_stream_id, value)

    return sorted(rows_by_key.values())


def parse_gas_impulse_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        if record.get("gasmeter_pin_state_change") != 1:
            continue

        add_row(
            rows_by_key,
            parse_timestamp(record.get("timestamp")),
            "gas_meter.main.impulse",
            1.0,
        )

    return sorted(rows_by_key.values())


def parse_electric_submeter_impulse_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        submeter_scope_id = ELECTRIC_SUBMETER_SCOPE_MAP.get(record.get("submeter"))
        if submeter_scope_id is None:
            continue

        add_row(
            rows_by_key,
            parse_timestamp(record.get("timestamp")),
            stream_id("electric_submeter", submeter_scope_id, "impulse"),
            1.0,
        )

    return sorted(rows_by_key.values())


def parse_external_temp_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        add_row(
            rows_by_key,
            parse_timestamp(record.get("timestamp")),
            "outdoor.weather_com.temperature",
            record.get("external_temp"),
        )

    return sorted(rows_by_key.values())


def parse_weather_station_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("last_updated") or record.get("timestamp"))
        state = record.get("state", {})

        for raw_key, (target_stream_id, scale) in WEATHER_STATION_FIELD_MAP.items():
            add_row(
                rows_by_key,
                timestamp,
                target_stream_id,
                state.get(raw_key),
                scale,
            )

    return sorted(rows_by_key.values())


def parse_pump_power_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))
        power = record.get("power", {})

        for cycle_id, value in power.items():
            add_row(
                rows_by_key,
                timestamp,
                stream_id("heating_cycle", cycle_id, "pump_power"),
                value,
                1000,
            )

    return sorted(rows_by_key.values())


def parse_heatmeters_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))
        states = record.get("states", {})

        for cycle_id, state in states.items():
            for raw_key, (variable, scale) in HEATMETER_FIELD_MAP.items():
                add_row(
                    rows_by_key,
                    timestamp,
                    stream_id("heating_cycle", cycle_id, variable),
                    state.get(raw_key),
                    scale,
                )

    return sorted(rows_by_key.values())


def parse_heating_control_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))

        for room_id, value in record.get("set_temps", {}).items():
            add_row(
                rows_by_key,
                timestamp,
                stream_id("room", room_id, "set_temperature"),
                value,
            )

        for cycle_id, value in record.get("pump_states", {}).items():
            add_row(
                rows_by_key,
                timestamp,
                stream_id("heating_cycle", cycle_id, "state"),
                value,
            )

        if "boiler_state" in record:
            add_row(
                rows_by_key,
                timestamp,
                "heating.main.state",
                record.get("boiler_state"),
            )

    return sorted(rows_by_key.values())


def parse_radiator_temperatures_file(path):
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))

        for raw_group, raw_values in record.items():
            if raw_group == "timestamp" or not isinstance(raw_values, dict):
                continue

            for raw_key, value in raw_values.items():
                target_stream_id = RADIATOR_TEMPERATURE_STREAM_MAP.get(
                    (raw_group, raw_key)
                )
                add_row(rows_by_key, timestamp, target_stream_id, value)

    return sorted(rows_by_key.values())


def parse_thermostats_file(path):
    rows_by_key = {}
    unmapped_thermostat_keys = set()

    for record in iter_ndjson(path):
        fallback_timestamp = parse_timestamp(record.get("timestamp"))
        states = record.get("states", {})

        for thermostat_key, state in states.items():
            thermostat_id = thermostat_id_from_log_entry(thermostat_key, state)
            radiator_scope_id = THERMOSTAT_ID_TO_RADIATOR_SCOPE_MAP.get(thermostat_id)
            if radiator_scope_id is None:
                unmapped_thermostat_keys.add(f"{thermostat_key}->{thermostat_id}")
                continue

            timestamp = parse_timestamp(
                state.get("lastupdated") or state.get("last_updated")
            ) or fallback_timestamp
            add_row(
                rows_by_key,
                timestamp,
                stream_id("radiator", radiator_scope_id, "valve_state"),
                state.get("valve"),
            )

    if unmapped_thermostat_keys:
        report(
            f"skipped unmapped thermostat keys in {path.name}: "
            + ", ".join(sorted(unmapped_thermostat_keys))
        )

    return sorted(rows_by_key.values())


def create_import_table(con):
    con.execute("""
    CREATE TEMP TABLE IF NOT EXISTS imported_observations (
        "timestamp" TIMESTAMP NOT NULL,
        stream_id TEXT NOT NULL,
        value DOUBLE NOT NULL
    );
    """)


def load_imported_observations(con, rows):
    temp_path = None

    try:
        step_started_at = perf_counter()
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".csv",
            prefix="log_parser_batch_",
            dir=SCRIPT_PATH.parent,
            delete=False,
        ) as temp_file:
            temp_path = Path(temp_file.name)
            writer = csv.writer(temp_file)
            writer.writerows(rows)

        report(
            f"wrote batch CSV {temp_path.name} in "
            f"{format_seconds(perf_counter() - step_started_at)}"
        )

        step_started_at = perf_counter()
        con.execute("""
        INSERT INTO imported_observations (
            "timestamp",
            stream_id,
            value
        )
        SELECT
            column0::TIMESTAMP,
            column1::TEXT,
            column2::DOUBLE
        FROM read_csv(
            ?,
            header = false,
            auto_detect = false,
            columns = {
                'column0': 'VARCHAR',
                'column1': 'VARCHAR',
                'column2': 'DOUBLE'
            }
        );
        """, [str(temp_path)])
        report(
            "loaded temp table from batch CSV in "
            f"{format_seconds(perf_counter() - step_started_at)}"
        )

    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def insert_observation_batch(con, rows):
    if not rows:
        return 0, [], 0

    transaction_started = False

    try:
        report(f"batch write starting; rows staged: {len(rows)}")
        con.execute("BEGIN TRANSACTION;")
        transaction_started = True
        report("batch transaction opened")

        step_started_at = perf_counter()
        con.execute("DELETE FROM imported_observations;")
        report(
            "cleared temp table in "
            f"{format_seconds(perf_counter() - step_started_at)}"
        )

        load_imported_observations(con, rows)

        step_started_at = perf_counter()
        unknown_stream_ids = con.execute("""
        SELECT DISTINCT imported_observations.stream_id
        FROM imported_observations
        LEFT JOIN streams
            ON imported_observations.stream_id = streams.stream_id
        WHERE streams.stream_id IS NULL
        ORDER BY imported_observations.stream_id;
        """).fetchall()
        report(
            f"checked stream IDs in {format_seconds(perf_counter() - step_started_at)}; "
            f"unknown: {len(unknown_stream_ids)}"
        )

        if unknown_stream_ids:
            output("unknown stream IDs skipped:")
            for row in unknown_stream_ids:
                output(f"  {row[0]}")

            step_started_at = perf_counter()
            con.execute("""
            DELETE FROM imported_observations
            WHERE stream_id IN (
                SELECT imported_observations.stream_id
                FROM imported_observations
                LEFT JOIN streams
                    ON imported_observations.stream_id = streams.stream_id
                WHERE streams.stream_id IS NULL
            );
            """)
            report(
                "removed unknown stream rows from temp table in "
                f"{format_seconds(perf_counter() - step_started_at)}"
            )

        step_started_at = perf_counter()
        valid_count = con.execute("""
        SELECT count(*)
        FROM imported_observations;
        """).fetchone()[0]
        report(
            f"counted valid temp rows in {format_seconds(perf_counter() - step_started_at)}; "
            f"valid: {valid_count}"
        )

        replaced_count = 0
        skipped_count = 0

        if IMPORT_EXISTING_POLICY == "skip_existing":
            step_started_at = perf_counter()
            con.execute("""
            CREATE OR REPLACE TEMP TABLE import_existing_observation_counts AS
            SELECT
                observations."timestamp",
                observations.stream_id,
                observations.value,
                count(*) AS existing_count
            FROM observations
            INNER JOIN (
                SELECT DISTINCT
                    "timestamp",
                    stream_id,
                    value
                FROM imported_observations
            ) AS imported_distinct
                ON observations."timestamp" = imported_distinct."timestamp"
               AND observations.stream_id = imported_distinct.stream_id
               AND observations.value = imported_distinct.value
            GROUP BY
                observations."timestamp",
                observations.stream_id,
                observations.value;
            """)
            con.execute("""
            CREATE OR REPLACE TEMP TABLE import_insert_candidates AS
            WITH imported_ranked AS (
                SELECT
                    "timestamp",
                    stream_id,
                    value,
                    row_number() OVER (
                        PARTITION BY "timestamp", stream_id, value
                        ORDER BY "timestamp", stream_id, value
                    ) AS occurrence_number
                FROM imported_observations
            )
            SELECT
                imported_ranked."timestamp",
                imported_ranked.stream_id,
                imported_ranked.value
            FROM imported_ranked
            LEFT JOIN import_existing_observation_counts AS existing
                ON imported_ranked."timestamp" = existing."timestamp"
               AND imported_ranked.stream_id = existing.stream_id
               AND imported_ranked.value = existing.value
            WHERE imported_ranked.occurrence_number > coalesce(existing.existing_count, 0);
            """)
            inserted_count = con.execute("""
            SELECT count(*)
            FROM import_insert_candidates;
            """).fetchone()[0]
            skipped_count = valid_count - inserted_count
            report(
                "selected new exact observation rows in "
                f"{format_seconds(perf_counter() - step_started_at)}; "
                f"new: {inserted_count}; existing: {skipped_count}"
            )

            step_started_at = perf_counter()
            con.execute("""
            INSERT INTO observations (
                "timestamp",
                stream_id,
                value
            )
            SELECT
                "timestamp",
                stream_id,
                value
            FROM import_insert_candidates
            ORDER BY "timestamp", stream_id;
            """)
            report(
                f"inserted observation rows in "
                f"{format_seconds(perf_counter() - step_started_at)}; "
                f"inserted: {inserted_count}; skipped existing: {skipped_count}; "
                f"replaced: {replaced_count}"
            )
            con.execute("DROP TABLE IF EXISTS import_insert_candidates;")
            con.execute("DROP TABLE IF EXISTS import_existing_observation_counts;")

        else:
            step_started_at = perf_counter()
            existing_count = con.execute("""
            SELECT count(*)
            FROM imported_observations
            WHERE EXISTS (
                SELECT 1
                FROM observations
                WHERE observations."timestamp" = imported_observations."timestamp"
                  AND observations.stream_id = imported_observations.stream_id
            );
            """).fetchone()[0]
            report(
                f"checked existing observation keys in "
                f"{format_seconds(perf_counter() - step_started_at)}; "
                f"existing: {existing_count}"
            )

            if IMPORT_EXISTING_POLICY == "fail_on_existing" and existing_count:
                raise RuntimeError(
                    "import batch contains existing observation keys; "
                    "set IMPORT_EXISTING_POLICY to 'skip_existing' or "
                    "'replace_existing' to proceed"
                )

            if IMPORT_EXISTING_POLICY == "replace_existing":
                step_started_at = perf_counter()
                con.execute("""
                DELETE FROM observations
                USING imported_observations
                WHERE observations."timestamp" = imported_observations."timestamp"
                  AND observations.stream_id = imported_observations.stream_id;
                """)
                replaced_count = existing_count
                report(
                    "deleted replaceable existing rows in "
                    f"{format_seconds(perf_counter() - step_started_at)}"
                )
            else:
                report("kept existing observation rows")

            step_started_at = perf_counter()
            con.execute("""
            INSERT INTO observations (
                "timestamp",
                stream_id,
                value
            )
            SELECT
                imported_observations."timestamp",
                imported_observations.stream_id,
                imported_observations.value
            FROM imported_observations
            ORDER BY imported_observations."timestamp", imported_observations.stream_id;
            """)
            inserted_count = valid_count
            report(
                f"inserted observation rows in "
                f"{format_seconds(perf_counter() - step_started_at)}; "
                f"inserted: {inserted_count}; skipped existing: {skipped_count}; "
                f"replaced: {replaced_count}"
            )

        step_started_at = perf_counter()
        con.execute("COMMIT;")
        transaction_started = False
        report(
            "batch transaction committed in "
            f"{format_seconds(perf_counter() - step_started_at)}"
        )

        return inserted_count, [row[0] for row in unknown_stream_ids], skipped_count

    except KeyboardInterrupt:
        if transaction_started:
            rollback_started_at = perf_counter()
            try:
                con.execute("ROLLBACK;")
                output(
                    "batch write interrupted; rolled back current batch in "
                    f"{format_seconds(perf_counter() - rollback_started_at)}"
                )
            except Exception as rollback_error:
                output(f"batch write interrupted; rollback failed: {rollback_error}")
        raise

    except Exception:
        if transaction_started:
            try:
                con.execute("ROLLBACK;")
                output("batch write failed; rolled back current batch")
            except Exception as rollback_error:
                output(f"batch write failed; rollback failed: {rollback_error}")
        raise


def source_reduction_policy(source_name):
    return SOURCE_REDUCTION_POLICIES.get(source_name, "none")


def source_reduction_description(policy):
    if policy == "exact":
        return "drop exact duplicate analytical rows"

    if policy == "changes":
        return "drop exact duplicates and consecutive same-value snapshots"

    return "none"


def reduce_source_rows(source_name, rows, reduction_state):
    policy = source_reduction_policy(source_name)
    if policy == "none" or not rows:
        return rows, 0

    rows = sorted(rows)
    kept_rows = []
    dropped_count = 0
    seen_rows = reduction_state.setdefault("seen_rows", set())
    last_values = reduction_state.setdefault("last_values", {})

    for row in rows:
        timestamp, target_stream_id, value = row[:3]
        reduction_key = row[3] if len(row) > 3 else target_stream_id

        seen_key = (reduction_key, timestamp, target_stream_id, value)
        if seen_key in seen_rows:
            dropped_count += 1
            continue

        if policy == "changes":
            previous_value = last_values.get(reduction_key)
            if reduction_key in last_values and previous_value == value:
                dropped_count += 1
                continue

            last_values[reduction_key] = value

        seen_rows.add(seen_key)
        kept_rows.append((timestamp, target_stream_id, value))

    return kept_rows, dropped_count


def import_source(source_name, parse_file):
    global IMPORT_INTERRUPTED

    IMPORT_INTERRUPTED = False
    started_at = perf_counter()
    paths = configured_source_paths(source_name)

    if not paths:
        output("no log files found")
        return

    con = None
    inserted_count = 0
    skipped_existing_count = 0
    parsed_count = 0
    source_reduced_count = 0
    current_index = 0
    last_committed_index = 0
    phase = "starting"
    unknown_stream_ids = set()
    pending_rows = []
    reduction_state = {}

    try:
        reduction_policy = source_reduction_policy(source_name)
        report(f"importing {source_name}")
        report(f"date range: {START_DATE or 'first'} to {END_DATE or 'last'}")
        report(f"include current log: {INCLUDE_CURRENT_LOG}")
        report(f"log files: {len(paths)}")
        report(f"first log file: {paths[0]}")
        report(f"last log file: {paths[-1]}")
        report(f"batch file count: {BATCH_FILE_COUNT}")
        report(f"existing observation policy: {IMPORT_EXISTING_POLICY}")
        report(
            "source reduction: "
            f"{source_reduction_description(reduction_policy)}"
        )
        stream_id_filter = configured_stream_id_filter()
        if stream_id_filter is None:
            report("stream ID filter: all parsed streams")
        else:
            report(f"stream ID filter: {len(stream_id_filter)} stream(s)")

        phase = "opening database"
        con = connect()
        create_import_table(con)

        for index, path in enumerate(paths, start=1):
            current_index = index
            phase = f"parsing file {index}/{len(paths)}: {path}"
            file_started_at = perf_counter()
            parsed_rows = parse_file(path)
            file_seconds = perf_counter() - file_started_at
            parsed_count += len(parsed_rows)
            rows, reduced_in_file = reduce_source_rows(
                source_name,
                parsed_rows,
                reduction_state,
            )
            source_reduced_count += reduced_in_file

            phase = f"staging parsed rows from file {index}/{len(paths)}: {path}"
            pending_rows.extend(rows)

            if should_report_file_progress(index, len(paths)):
                elapsed_seconds = perf_counter() - started_at
                report(
                    f"parsed {index}/{len(paths)} files "
                    f"({index / len(paths):.0%}); "
                    f"file rows: {len(parsed_rows)}; "
                    f"staged rows: {len(rows)}; "
                    f"source-reduced: {reduced_in_file}; "
                    f"total parsed: {parsed_count}; "
                    f"total source-reduced: {source_reduced_count}; "
                    f"elapsed: {format_seconds(elapsed_seconds)}; "
                    f"last file: {format_seconds(file_seconds)}"
                )

            if index == len(paths) or index % BATCH_FILE_COUNT == 0:
                phase = f"preparing batch ending at file {index}/{len(paths)}"
                report(
                    f"preparing batch at {index}/{len(paths)} files; "
                    f"pending rows: {len(pending_rows)}"
                )
                batch_prepare_started_at = perf_counter()
                pending_rows = sorted(pending_rows)
                report(
                    "sorted pending rows in "
                    f"{format_seconds(perf_counter() - batch_prepare_started_at)}"
                )
                batch_started_at = perf_counter()
                phase = (
                    f"writing batch for files {last_committed_index + 1}-{index} "
                    f"of {len(paths)}"
                )
                (
                    inserted_in_batch,
                    unknown_in_batch,
                    skipped_in_batch,
                ) = insert_observation_batch(
                    con,
                    pending_rows,
                )
                last_committed_index = index
                batch_seconds = perf_counter() - batch_started_at
                inserted_count += inserted_in_batch
                skipped_existing_count += skipped_in_batch
                unknown_stream_ids.update(unknown_in_batch)
                pending_rows = []

                report(
                    f"committed batch at {index}/{len(paths)} files "
                    f"({index / len(paths):.0%}); "
                    f"batch inserted: {inserted_in_batch}; "
                    f"batch skipped existing: {skipped_in_batch}; "
                    f"total inserted: {inserted_count}; "
                    f"total skipped existing: {skipped_existing_count}; "
                    f"batch time: {format_seconds(batch_seconds)}"
                )

        elapsed_seconds = perf_counter() - started_at
        report(f"finished {source_name} in {format_seconds(elapsed_seconds)}")
        report(f"parsed observations: {parsed_count}")
        report(f"source-reduced observations: {source_reduced_count}")
        report(f"inserted observations: {inserted_count}")
        report(f"skipped existing observations: {skipped_existing_count}")
        report(f"unknown stream IDs skipped: {len(unknown_stream_ids)}")

    except KeyboardInterrupt:
        IMPORT_INTERRUPTED = True
        report_interrupted_import(
            source_name=source_name,
            paths=paths,
            last_committed_index=last_committed_index,
            current_index=current_index,
            phase=phase,
            parsed_count=parsed_count,
            inserted_count=inserted_count,
            skipped_existing_count=skipped_existing_count,
            pending_row_count=len(pending_rows),
            source_reduced_count=source_reduced_count,
        )

    finally:
        if con is not None:
            try:
                con.close()
                report("database connection closed")
            except Exception as close_error:
                output(f"database connection close failed: {close_error}")


def import_aqara_and_nous():
    import_source("aqara_and_nous", parse_aqara_and_nous_file)


def import_electric_main_meter():
    import_source(
        "electric_main_meter",
        lambda path: rows_from_mapping_file(path, MAIN_METER_FIELD_MAP),
    )


def import_electric_submeter_impulses():
    import_source("electric_submeters", parse_electric_submeter_impulse_file)


def import_gas_impulses():
    import_source("gas_impulses", parse_gas_impulse_file)


def import_heatmeters():
    import_source("heatmeters", parse_heatmeters_file)


def import_heating_control_state():
    import_source("heating_control", parse_heating_control_file)


def import_oktopusz_presence():
    import_source("oktopusz_presence", parse_oktopusz_presence_file)


def import_room_presence():
    import_source("presence_all", parse_presence_all_file)


def import_open_close():
    import_source("open_close", parse_open_close_file)


def import_outdoor_weather_com():
    import_source("external_temp", parse_external_temp_file)


def import_pump_power():
    import_source("pumps", parse_pump_power_file)


def import_pv_inverter():
    import_source(
        "pv_inverter",
        lambda path: rows_from_mapping_file(path, PV_FIELD_MAP),
    )


def import_radiator_temperatures():
    import_source("radiator_temperatures", parse_radiator_temperatures_file)


def import_radiator_thermostats():
    import_source("thermostats", parse_thermostats_file)


def import_room_occupancy():
    import_source("occupancy", parse_occupancy_file)


def import_room_temperature_humidity():
    import_source("temperature_and_humidity", parse_room_temperature_humidity_file)


def import_weather_station():
    import_source("weather_station", parse_weather_station_file)


def list_modes():
    output("Available MODE values:")
    for mode_name in sorted(MODE_DESCRIPTIONS):
        output(f"- {mode_name}: {MODE_DESCRIPTIONS[mode_name]}")


MODE_HANDLERS = {
    "list_modes": list_modes,
    "import_aqara_and_nous": import_aqara_and_nous,
    "import_electric_main_meter": import_electric_main_meter,
    "import_electric_submeter_impulses": import_electric_submeter_impulses,
    "import_gas_impulses": import_gas_impulses,
    "import_heatmeters": import_heatmeters,
    "import_heating_control_state": import_heating_control_state,
    "import_oktopusz_presence": import_oktopusz_presence,
    "import_room_presence": import_room_presence,
    "import_open_close": import_open_close,
    "import_outdoor_weather_com": import_outdoor_weather_com,
    "import_pump_power": import_pump_power,
    "import_pv_inverter": import_pv_inverter,
    "import_radiator_temperatures": import_radiator_temperatures,
    "import_radiator_thermostats": import_radiator_thermostats,
    "import_room_occupancy": import_room_occupancy,
    "import_room_temperature_humidity": import_room_temperature_humidity,
    "import_weather_station": import_weather_station,
}


MODE = "import_heating_control_state"

START_DATE = "2025-11-01"
END_DATE = "2026-04-01"
INCLUDE_CURRENT_LOG = False

# Existing-row handling:
# - "skip_existing": insert exact observation rows not already present
# - "replace_existing": rewrite matching rows, for directed repair imports
# - "fail_on_existing": stop and roll back if any imported row already exists
IMPORT_EXISTING_POLICY = "skip_existing"
STREAM_ID_FILTER = None

REPORT_PROGRESS = True
REPORT_EVERY_FILES = 10
REPORT_FILE_DETAILS = False


def main():
    try:
        validate_import_config()
    except ValueError as error:
        output(str(error))
        return

    handler = MODE_HANDLERS.get(MODE)

    if handler is None:
        output(f"unknown MODE: {MODE}")
        list_modes()
        return

    handler()


if __name__ == "__main__":
    main()
