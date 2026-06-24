# DuckDB Data Layer Status

This file records the current working state of the experimental DuckDB data layer.

## Current Data Location

Database:

- `store/observations.duckdb`

Metadata:

- `metadata/scope_metadata.csv`
- `metadata/scope_list.csv`
- `metadata/variable_list.csv`
- `metadata/stream_metadata.csv`

Generated inspection outputs:

- `stream_availability.html`
- `stream_availability.csv`

Migration backup:

- `store/observations.before_timestamp_cleanup.duckdb`

## Current Database Schema

Core tables:

- `streams`
- `observations`

Timestamp convention:

- `observations.timestamp` stores Budapest local time
- API query ranges use Budapest local time

Current derived view:

- `stream_availability`

## Current Loaded Metadata

The generated stream catalog has been loaded into DuckDB.

Current stream count:

- `303`

## Current Loaded Observations

Currently imported real observation streams:

- `room.1.temperature`
- `room.1.humidity`
- `gas_meter.main.impulse`

Current observed range for `room.1.temperature`:

- first observation: `2024-10-10 15:45:31`
- last observation: `2026-06-23 13:13:30`
- observation count: `87122`

Current observed range for `room.1.humidity`:

- first observation: `2024-10-10 15:45:31`
- last observation: `2025-12-19 23:45:19`
- observation count: `60833`
- note: this import is partial; the long import was intentionally stopped

Current observed range for `gas_meter.main.impulse`:

- first observation: `2025-02-10 00:13:38`
- last observation: `2025-02-10 23:57:42`
- observation count: `625`
- note: this is a one-day test import from local date `2025-02-10`

## Current Scripts

### `metadata/generate_stream_metadata.py`

Generates `metadata/stream_metadata.csv` from:

- `scope_metadata.csv`
- `scope_list.csv`
- `variable_list.csv`

### `db_manager.py`

Current responsibilities:

- initialize database schema
- load stream metadata into DuckDB
- maintain `stream_availability`
- write availability HTML
- write availability CSV

### `log_parser.py`

Current responsibility:

- import observations from source-specific daily logs using a top-level `MODE`
- keep raw-to-canonical mapping explicit in editable dictionaries
- imports can be long; once import scripts are prepared, the user should run them locally and ask the agent to inspect results or errors

Current modes:

- `list_modes`
- `import_aqara_and_nous`
- `import_electric_main_meter`
- `import_electric_submeter_impulses`
- `import_gas_impulses`
- `import_heatmeters`
- `import_oktopusz_presence`
- `import_open_close`
- `import_outdoor_weather_com`
- `import_pump_power`
- `import_pv_inverter`
- `import_radiator_temperatures`
- `import_radiator_thermostats`
- `import_room_occupancy`
- `import_room_temperature_humidity`
- `import_weather_station`

Current parser smoke-check result:

- one representative daily file per mode was parsed successfully
- all produced stream IDs matched the loaded `streams` catalog
- no broad imports were run during the smoke check

### `db_api.py`

Current read-only API functions:

- `get_streams()`
- `get_stream_availability()`
- `query_observations(...)`
- `query_observations_grouped(...)`
- `query_summary(...)`
- `query_summary_wide(...)`

Current summary fields:

- `mean_value`
- `min_value`
- `max_value`
- `stddev_value`
- `observation_count`

Numeric summary values are rounded to the requested measurement precision.

## Current Next Step

The next implementation step should be chosen from `PLAN.md` based on the latest design decision.

## Known Limitations

- Only three real streams are imported so far; one is partial and one is a one-day test import.
- `stream_availability` is only first/last/count and does not show gaps.
- There is no HTTP server yet.
- There is no final README/manual yet.
- Some raw log names intentionally differ from canonical stream IDs; importers must handle that mapping.
