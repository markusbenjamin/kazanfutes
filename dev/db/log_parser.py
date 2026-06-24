import json
from datetime import date, datetime
from pathlib import Path

import duckdb


MODE = "list_modes"

START_DATE = None
END_DATE = None
INCLUDE_CURRENT_LOG = True
BATCH_FILE_COUNT = 50

SCRIPT_PATH = Path(__file__).resolve()
DEV_PATH = SCRIPT_PATH.parent.parent
PROJECT_PATH = DEV_PATH.parent

DB_PATH = DEV_PATH / "db" / "store" / "observations.duckdb"
LOG_PATH = PROJECT_PATH / "data" / "logs"

SOURCE_FILES = {
    "aqara_and_nous": ("aqara_and_nous", "aqara_and_nous.json"),
    "electric_main_meter": ("electricity", "main_meter.json"),
    "electric_submeters": ("electricity", "submeters.json"),
    "external_temp": ("external_temp", "external_temp.json"),
    "gas_impulses": ("gas_consumption", "gas_relay_turns.json"),
    "heatmeters": ("heat_delivery", "heatmeters_state.json"),
    "occupancy": ("occupancy", "occupancy.json"),
    "open_close": ("open_close", "open_close_events.json"),
    "oktopusz_presence": ("presence", "oktopusz_presence.json"),
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
    # Aqara11 was "DiosEdit" in old notes; no current scope.
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
    # Nous2 was "DiosEdit" in old notes; no current scope.
    "Nous3": "2",
    "Nous4": "17",
    "Nous5": "3",
    "Nous6": "1",
    "Nous7": "7",
    "Nous8": "6",
    "Nous9": "5",
    # Nous10 was "DiosEdit" in old notes; no current scope.
}

AQARA_FIELD_MAP = {
    "temp": "temperature",
    "hum": "humidity",
    "presence": "presence_detected",
    "lux": "illuminance",
}

NOUS_FIELD_MAP = {
    "temp": "temperature",
    "hum": "humidity",
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
    # "hm division" has no canonical stream yet.
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

# Mock mapping: thermostat names do not cleanly identify radiator IDs yet.
THERMOSTAT_RADIATOR_SCOPE_MAP = {
    "PK": "3.1",
    "Merce_targyalo": "12.1",
    "Merce": "5.1",
    "SZGK": "4.1",
    "GEP_muhely": "13.1",
    "Thermostat 65": "1.1",
    "Thermostat 67": "1.2",
    "Thermostat 69": "2.1",
    "Thermostat 71": "2.2",
    "Thermostat 75": "2.3",
    "Thermostat 77": "2.4",
    "Thermostat 79": "7.1",
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


MODE_DESCRIPTIONS = {
    "list_modes": "print available modes",
    "import_aqara_and_nous": "room temp/humidity/CO2/presence/illuminance from Aqara/Nous logs",
    "import_electric_main_meter": "main electric meter values",
    "import_electric_submeter_impulses": "electric submeter impulse events",
    "import_gas_impulses": "gas meter impulse events",
    "import_heatmeters": "heating-cycle heatmeter readings",
    "import_oktopusz_presence": "legacy Oktopusz presence boolean",
    "import_open_close": "door/window open-close state events",
    "import_outdoor_weather_com": "Weather.com outdoor temperature scrape",
    "import_pump_power": "heating-cycle pump power readings",
    "import_pv_inverter": "PV inverter readings",
    "import_radiator_temperatures": "radiator Shelly temperature readings",
    "import_radiator_thermostats": "radiator thermostat temperature/valve readings",
    "import_room_occupancy": "room occupancy state readings",
    "import_room_temperature_humidity": "legacy room temperature/humidity readings",
    "import_weather_station": "WS90 weather station readings",
}


def connect():
    return duckdb.connect(str(DB_PATH))


def parse_day(day_text):
    if day_text is None:
        return None
    return date.fromisoformat(day_text)


def parse_timestamp(timestamp_text):
    if timestamp_text is None:
        return None

    if str(timestamp_text).lower() == "none":
        return None

    return datetime.strptime(timestamp_text, "%Y-%m-%d-%H-%M-%S")


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
    with path.open(encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            line = line.strip()
            if not line:
                continue

            try:
                yield json.loads(line)
            except json.JSONDecodeError as error:
                print(f"skipped invalid JSON in {path} line {line_number}: {error}")


def clean_value(value, scale=1):
    if value is None:
        return None

    if isinstance(value, bool):
        return 1.0 if value else 0.0

    return float(value) / scale


def add_row(rows_by_key, timestamp, stream_id, value, scale=1):
    if timestamp is None or stream_id is None or value is None:
        return

    rows_by_key[(timestamp, stream_id)] = (
        timestamp,
        stream_id,
        clean_value(value, scale),
    )


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
    rows_by_key = {}

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))
        states = record.get("states", {})

        for device_name, state in states.get("aqara", {}).items():
            room_id = AQARA_ROOM_MAP.get(device_name)
            if room_id is None:
                continue

            for raw_key, variable in AQARA_FIELD_MAP.items():
                add_row(
                    rows_by_key,
                    timestamp,
                    stream_id("room", room_id, variable),
                    state.get(raw_key),
                )

        for device_name, state in states.get("nous", {}).items():
            room_id = NOUS_ROOM_MAP.get(device_name)
            if room_id is None:
                continue

            for raw_key, variable in NOUS_FIELD_MAP.items():
                add_row(
                    rows_by_key,
                    timestamp,
                    stream_id("room", room_id, variable),
                    state.get(raw_key),
                )

    return sorted(rows_by_key.values())


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
        timestamp = parse_timestamp(record.get("timestamp"))
        add_row(
            rows_by_key,
            timestamp,
            "room.1.presence_detected",
            record.get("presence"),
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

    for record in iter_ndjson(path):
        timestamp = parse_timestamp(record.get("timestamp"))
        states = record.get("states", {})

        for thermostat_name, state in states.items():
            radiator_scope_id = THERMOSTAT_RADIATOR_SCOPE_MAP.get(thermostat_name)
            if radiator_scope_id is None:
                continue

            add_row(
                rows_by_key,
                timestamp,
                stream_id("radiator", radiator_scope_id, "temperature"),
                state.get("temperature"),
                100,
            )
            add_row(
                rows_by_key,
                timestamp,
                stream_id("radiator", radiator_scope_id, "valve_state"),
                state.get("valve"),
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


def insert_observation_batch(con, rows):
    if not rows:
        return 0

    con.execute("DELETE FROM imported_observations;")

    con.executemany("""
    INSERT INTO imported_observations (
        "timestamp",
        stream_id,
        value
    )
    VALUES (?, ?, ?);
    """, rows)

    unknown_stream_ids = con.execute("""
    SELECT DISTINCT imported_observations.stream_id
    FROM imported_observations
    LEFT JOIN streams
        ON imported_observations.stream_id = streams.stream_id
    WHERE streams.stream_id IS NULL
    ORDER BY imported_observations.stream_id;
    """).fetchall()

    if unknown_stream_ids:
        print("unknown stream IDs skipped:", flush=True)
        for row in unknown_stream_ids:
            print(" ", row[0], flush=True)

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

    valid_count = con.execute("""
    SELECT count(*)
    FROM imported_observations;
    """).fetchone()[0]

    con.execute("""
    DELETE FROM observations
    USING imported_observations
    WHERE observations."timestamp" = imported_observations."timestamp"
      AND observations.stream_id = imported_observations.stream_id;
    """)

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
    FROM imported_observations
    ORDER BY "timestamp", stream_id;
    """)

    return valid_count


def import_source(source_name, parse_file):
    paths = configured_source_paths(source_name)

    if not paths:
        print("no log files found", flush=True)
        return

    print(f"importing {source_name}", flush=True)
    print("log files:", len(paths), flush=True)
    print("first log file:", paths[0], flush=True)
    print("last log file:", paths[-1], flush=True)

    con = connect()
    create_import_table(con)

    inserted_count = 0
    parsed_count = 0
    pending_rows_by_key = {}

    for index, path in enumerate(paths, start=1):
        rows = parse_file(path)
        parsed_count += len(rows)

        for row in rows:
            pending_rows_by_key[(row[0], row[1])] = row

        if index == len(paths) or index % BATCH_FILE_COUNT == 0:
            pending_rows = sorted(pending_rows_by_key.values())
            inserted_count += insert_observation_batch(con, pending_rows)
            pending_rows_by_key = {}

            print(
                f"processed {index}/{len(paths)} files; inserted {inserted_count} observations",
                flush=True,
            )

    con.close()

    print("parsed observations:", parsed_count, flush=True)
    print("inserted observations:", inserted_count, flush=True)


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


def import_oktopusz_presence():
    import_source("oktopusz_presence", parse_oktopusz_presence_file)


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
    print("Available MODE values:")
    for mode_name in sorted(MODE_DESCRIPTIONS):
        print(f"- {mode_name}: {MODE_DESCRIPTIONS[mode_name]}")


MODE_HANDLERS = {
    "list_modes": list_modes,
    "import_aqara_and_nous": import_aqara_and_nous,
    "import_electric_main_meter": import_electric_main_meter,
    "import_electric_submeter_impulses": import_electric_submeter_impulses,
    "import_gas_impulses": import_gas_impulses,
    "import_heatmeters": import_heatmeters,
    "import_oktopusz_presence": import_oktopusz_presence,
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


def main():
    handler = MODE_HANDLERS.get(MODE)

    if handler is None:
        print("unknown MODE:", MODE)
        list_modes()
        return

    handler()


if __name__ == "__main__":
    main()
