# DuckDB Data Layer Status

This file records the current working state of the experimental DuckDB data layer.

Document boundary:

- `PLAN.md` records roadmap and design direction.
- `STATUS.md` records durable implementation state and stable known limitations.
- `HANDOFF.md` records the live baton for context switches, interrupted runs, fragile config, latest reports, and exact next steps.

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

- active overnight import/rebuild state is volatile; read `HANDOFF.md` for latest verified counts and latest run artifacts

Loaded observations by scope/variable:

- not currently maintained here during the active overnight rebuild; regenerate from `stream_availability` after the rebuild is stable

Notes:

- `observations` was cleared after user-confirmed backup so the database can be rebuilt from the current parser specs.
- the clean reinitialized database has been reloaded with `303` stream metadata rows from `metadata/stream_metadata.csv`.
- `stream_availability.html` and `stream_availability.csv` were regenerated after clearing observations.
- a later partial overnight import succeeded substantially before hitting a DuckDB file-lock issue; see `HANDOFF.md` for current operational state.

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
- `import_room_presence`
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
- imports now use `IMPORT_EXISTING_POLICY`; default `skip_existing` inserts exact observation rows whose multiplicity is not already present, while `replace_existing` is available for directed rewrites and `fail_on_existing` rejects key collisions; all three policies passed earlier in-memory smoke checks
- duplicate-aware `skip_existing` was checked in memory: with one existing `(timestamp, stream_id, value)` row and two duplicate imported rows for that same triple, only the missing duplicate was inserted
- timestamp parsing accepts both second-resolution (`YYYY-MM-DD-HH-MM-SS`) and legacy minute-resolution (`YYYY-MM-DD-HH-MM`) timestamps; this was checked against `temperature_and_humidity.json.2024-07-27`
- thermostat valve-state parsing now resolves raw thermostat log keys/names to thermostat IDs, then uses `system/setup.json` as the authoritative thermostat-ID-to-room source; radiator target scopes are derived from radiator order in `metadata/scope_list.csv`
- narrow thermostat parse checks passed for `thermostats_state.json.2026-06-23` and `thermostats_state.json.2025-10-06`; the current setup-derived map is `42->3.1`, `53->12.1`, `57->13.1`, `59->4.1`, `63->5.1`, `65->7.1`, `69->6.1`, `71->2.1`, `75->2.3`, `77->1.1`, `79->1.2`
- historical key `Thermostat 67` appears in `thermostats_state.json.2025-10-06` but has no ID in `system/setup.json`; the parser reports and skips it rather than guessing

Current parser coverage by scope:

- `room`: temperature, humidity, set_temperature, occupancy_state, presence_detected, co2, illuminance. Coverage depends on source instrumentation: temperature/humidity can come from room-keyed legacy logs and Aqara; Aqara presence maps to `occupancy_state`; raw `presence_all` maps to `presence_detected`; CO2 is only available where a Nous device exists. Multiple Aqara temperature/humidity/illuminance readings mapped to the same room are kept as independent observations; only Aqara occupancy is OR-combined per room/timestamp.
- `heating`: main boiler/heating state from heating-control logs.
- `heating_cycle`: state, pump_power, flow_temperature, return_temperature, volume_flow, power, energy, volume.
- `radiator`: temperature and valve_state. Temperature comes from radiator Shelly logs; valve state comes from thermostat state logs.
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
- `occupancy/occupancy.json` is derived and is intentionally excluded from broad ingestion.
- `thermostats/thermostats_state.json` no longer feeds `radiator.*.temperature`; it can feed radiator valve state only.
- `thermostats/thermostats_state.json` must not map log names directly to rooms; names first resolve to thermostat IDs, then `system/setup.json` maps IDs to rooms.
- `service_execution/heating_control/heating_control.json` no longer feeds `radiator.*.valve_state`; thermostat state logs are the valve-state source.
- `aqara_and_nous.json` keeps Aqara temperature/humidity/illuminance as independent observations when multiple devices map to the same room; Aqara occupancy is the only combined Aqara field.
- `open_close/open_close_events.json` feeds sparse door/window state-transition observations: each event records the resulting state at the event timestamp, not a dense continuous state series.
- `replace_existing` is a key-level repair mode: it deletes existing rows at matching timestamp/stream keys before inserting the selected importer's rows, so use it only with reviewed target/date bounds.

### `log_parser_test_modes.py`

Developer-facing parse-only smoke-test runner for all current `log_parser.py` import modes.

Current behavior:

- tests importer/stream-variable combinations without writing to `observations`
- default target selection builds one target per `scope_type.variable` group from the loaded stream metadata
- tests every relevant importer for a target instead of stopping after the first importer succeeds
- scans up to `MAX_DAYS_TO_TRY_PER_IMPORTER` recent archived log days per importer; default is `30`
- also checks the oldest archived source day by default, so legacy source formats are sampled before broad imports
- does not write to `observations`
- imports `log_parser.py` and calls the same parser functions used by the real import modes
- validates that its importer registry matches `log_parser.py` import modes, excluding `list_modes`
- checks whether archived source files exist for each importer source
- catches parser exceptions and writes full tracebacks to a report
- validates candidate stream IDs against the loaded `streams` catalog using a read-only DuckDB connection
- reports candidate row counts, first/last parsed timestamps, out-of-date row counts, unknown stream IDs, malformed row examples, and scope/variable counts
- writes timestamped reports to `dev/db/test_reports/`

Run example:

```bash
python3 log_parser_test_modes.py
```

Latest report reviewed:

- `dev/db/test_reports/log_parser_stream_variable_test_20260624_224608.txt`
- `87` importer-target checks: `74` pass, `11` pass with warnings, `2` empty result.
- No parser exceptions, no unknown stream IDs, no config errors, no missing source-log days.
- Empty results were from `import_radiator_thermostats` on recent thermostat logs; this is not a blocker for other importers.
- Warnings were stale timestamps in legacy room temperature/humidity and one weather-station row just before midnight; these are not ingestion blockers with `skip_existing`.
- This report predates the latest source-route corrections for Aqara independent observations, thermostat valve state, and heating-control non-valve state. Rerun `log_parser_test_modes.py` before the next broad write.

### `log_parser_overnight_import.py`

Fail-safe runner for long local ingestion runs.

Current context handoff:

- `HANDOFF.md`

Older focused handoff retained for reference:

- `OVERNIGHT_IMPORT_HANDOFF.md`

Current behavior:

- hardcoded top-level config, no CLI arguments required
- has a route-review breadcrumb: broad import refuses to run until `ROUTE_REVIEW_ACK` is replaced after manually checking `stream_ingestion_routes.csv`
- default `INGEST_TARGETS = "ALL_STREAMS_WITH_IMPORTERS"`
- can target exact streams, scope/variable groups, or scope/scope_id/variable tuples
- plans all relevant importers for each target and sets `STREAM_ID_FILTER` per importer, so a stream-targeted run ingests all available data sources for that stream without inserting unrelated streams
- defaults to `START_DATE = None`, `END_DATE = None`, and `INCLUDE_CURRENT_LOG = False`, so it scans all archived logs and avoids mutable current logs
- defaults to `IMPORT_EXISTING_POLICY = "skip_existing"`, which skips exact observation rows already present while preserving independent duplicate readings
- writes a full transcript to `dev/db/test_reports/overnight_import_<timestamp>.log`
- writes a terse error-only artifact to `dev/db/test_reports/overnight_import_errors_<timestamp>.txt`; clean runs still write the file with `no errors recorded`
- renders a compact live terminal dashboard when running in an interactive terminal: overall importer progress, current mode/file progress bars, row counts, current target stream families, recent events, and error count
- ensures database schema and stream metadata before building the import plan; this calls `db_manager.init_db()` and `db_manager.load_stream_metadata()` so a clean DB can still plan imports from metadata
- creates a timestamped DuckDB backup in `dev/db/store/import_backups/` before importing
- can optionally clear all existing `observations` before importing via `CLEAR_OBSERVATIONS_BEFORE_IMPORT`; this is guarded by a separate backup/clear acknowledgement breadcrumb
- stops remaining modes on Ctrl+C after the active batch is rolled back by `log_parser.py`
- refreshes `stream_availability.html` and `stream_availability.csv` at the end
- excludes `import_room_occupancy` by default because `occupancy/occupancy.json` is derived

Run example:

```bash
python3 log_parser_overnight_import.py
```

### `stream_ingestion_routes.csv`

Simple human route table from source log patterns to stream target families.

Current behavior:

- two columns only: `source_log_file_name_pattern` and `stream_target`
- rows are scope/variable-oriented rather than one row per stream ID
- `presence/presence_all.json` points at `room.*.presence_detected`
- `aqara_and_nous.json` points at Aqara room temperature, humidity, occupancy_state, illuminance, and Nous CO2
- the old derived `occupancy/occupancy.json` route is intentionally excluded

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

Read `HANDOFF.md` for the active overnight import/rebuild next step. Keep this section stable rather than using it as a live run log.

## Known Limitations

- Active import/rebuild state is volatile; use `HANDOFF.md` for current run status and update this file only after stable counts are available.
- `stream_availability` is only first/last/count and does not show gaps.
- Sparse transition-state streams such as door/window open-close state need state-aware API summary logic for duration/open-fraction style metrics; ordinary observation means over event rows are not semantically meaningful.
- Derived streams that depend on sparse state transitions should reconstruct intervals or use as-of/last-observation-carried-forward logic rather than treating transition rows as dense samples.
- The HTTP server is local/dev only so far; deployment/service packaging is not done.
- There is no final README/manual yet.
- Some raw log names intentionally differ from canonical stream IDs; importers must handle that mapping.
