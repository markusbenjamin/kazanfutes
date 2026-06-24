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

Current loaded observation summary:

- loaded stream count: `31`
- total observation count: `6063150`

Loaded observations by scope/variable:

- `gas_meter.impulse`: 1 stream, 625 observations, `2025-02-10 00:13:38` to `2025-02-10 23:57:42`
- `heating.state`: 1 stream, 211101 observations, `2025-11-01 00:00:06` to `2026-04-01 23:59:49`
- `heating_cycle.state`: 4 streams, 844688 observations, `2025-11-01 00:00:06` to `2026-04-01 23:59:49`
- `radiator.valve_state`: 11 streams, 2323805 observations, `2025-11-01 00:00:06` to `2026-04-01 23:59:49`
- `room.humidity`: 1 stream, 60833 observations, `2024-10-10 15:45:31` to `2025-12-19 23:45:19`
- `room.set_temperature`: 12 streams, 2534976 observations, `2025-11-01 00:00:06` to `2026-04-01 23:59:49`
- `room.temperature`: 1 stream, 87122 observations, `2024-10-10 15:45:31` to `2026-06-23 13:13:30`

Notes:

- `room.humidity` is partial; its long import was intentionally stopped.
- `gas_meter.main.impulse` is still only a one-day test import from local date `2025-02-10`.
- Heating-control streams have been loaded for `2025-11-01` through `2026-04-01`.

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
- `import_heating_control_state`
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
- `import_heating_control_state` was added and parse-only checked on `data/logs/service_execution/heating_control/heating_control.json.2026-06-23`
- that heating-control check produced 40,180 candidate observations across 28 streams with no unknown stream IDs
- `log_parser.py` now has toggleable import progress reporting; syntax/import checks passed without running an import
- progress output now includes wall-clock timestamps and batch-write stage messages
- `log_parser.py` now catches Ctrl+C during imports, closes the database connection, and prints the last committed file plus a restart `START_DATE` hint; this was checked with a simulated batch interrupt, not a real import
- batch temp-table loading was changed from Python `executemany()` to a temporary CSV plus DuckDB `read_csv()` bulk load after a 10-file heating-control batch spent several minutes loading 396,103 rows through `executemany()`; the CSV loader passed an in-memory smoke check
- imports now use `IMPORT_EXISTING_POLICY`; default `skip_existing` inserts only new `(timestamp, stream_id)` rows, while `replace_existing` is available for directed rewrites and `fail_on_existing` rejects collisions; all three policies passed in-memory smoke checks

Current parser coverage by scope:

- `room`: temperature, humidity, set_temperature, occupancy_state, presence_detected, co2, illuminance. Coverage depends on source instrumentation: room temperature/humidity and occupancy are keyed by room ID; Aqara/Nous fields depend on explicit device-to-room mappings; CO2 is only available where a Nous device exists.
- `heating`: main boiler/heating state from heating-control logs.
- `heating_cycle`: state, pump_power, flow_temperature, return_temperature, volume_flow, power, energy, volume.
- `radiator`: temperature and valve_state. Coverage depends on explicit radiator sensor mappings and, for heating-control valve states, room/list-position mappings.
- `door` and `window`: state from explicitly mapped open/close sensors.
- `gas_meter`: main impulse events.
- `electric_submeter`: mapped submeter impulse events.
- `electric_main_meter`: active power, import/export totals and tariffs, phase voltages, and phase currents.
- `pv`: inverter voltages, currents, frequency, power, energy, MPPT cumulative energy, and related inverter metrics.
- `weather_station`: WS90 temperature, humidity, dewpoint, illuminance, rain_status, wind speed/gust/direction, and UV index.
- `outdoor`: Weather.com outdoor temperature scrape.

Parser coverage notes:

- Scope-level parser setup does not imply every catalog stream has physical instrumentation.
- Some catalog streams are intentionally broader than current sensors, for example room CO2 exists only for rooms with Nous devices.
- Some source mappings are intentionally explicit because raw logs use device names, sensor names, or ordered list positions rather than canonical stream IDs.

### `db_queries.py`

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
- `sum_value`
- `observation_count`

Numeric summary values are rounded to the requested measurement precision.

### `db_server.py`

Thin read-only JSON HTTP API server using Python standard-library `http.server`.

Current endpoints:

- `/api/health`
- `/api/streams`
- `/api/availability`
- `/api/query`
- `/api/summary`

The server reuses `db_queries.py`; it does not duplicate SQL query logic. It accepts GET query strings and POSTed JSON bodies.

### `db_client.py`

Python client wrapper for remote scripts.

It exposes `DbApi`, with methods matching the local `db_queries.py` query layer, and calls the JSON server internally. `API_remote_test.py` is a small sandbox/example script for third-party-style usage.

### Removed stale scripts

- `db_gui.py` was removed. It only launched DuckDB's generic UI and was no longer part of the active database/API workflow.

## Current Next Step

The next implementation step should be chosen from `PLAN.md` based on the latest design decision. If validation/import broadening remains deferred, the next feature-oriented step is likely lightweight API examples/manual notes, then deciding whether to improve availability gap reporting or start deployment packaging.

## Known Limitations

- Many catalog streams are still empty; currently `31` of `303` streams have observations.
- `room.humidity` is partial and `gas_meter.main.impulse` is still a one-day test import.
- `stream_availability` is only first/last/count and does not show gaps.
- The HTTP server is local/dev only so far; deployment/service packaging is not done.
- There is no final README/manual yet.
- Some raw log names intentionally differ from canonical stream IDs; importers must handle that mapping.
