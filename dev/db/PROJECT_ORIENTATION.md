# DuckDB Data Layer Orientation

This document orients another assistant to the current `dev/db` DuckDB data-layer project only. The rest of the repository matters mainly as a source of raw logs and existing service scripts.

## Purpose

The `dev/db` project is an incremental DuckDB-based data layer for heterogeneous building/heating logs. It is experimental and intentionally small. It currently focuses on:

- a canonical stream catalog
- one fact table of timestamped observations
- source-specific log parsing into canonical streams
- a local read-only Python query layer
- availability inspection outputs

Do not redesign this into a larger framework without explicit instruction.

## Location

Main project directory:

- `dev/db/`

Current database:

- `dev/db/store/observations.duckdb`

Current metadata:

- `dev/db/metadata/scope_metadata.csv`
- `dev/db/metadata/scope_list.csv`
- `dev/db/metadata/variable_list.csv`
- `dev/db/metadata/stream_metadata.csv`

Generated inspection outputs:

- `dev/db/stream_availability.csv`
- `dev/db/stream_availability.html`

## Implemented Database Architecture

Core tables:

- `streams`
- `observations`

Derived view:

- `stream_availability`

Current timestamp convention:

- `observations.timestamp` stores Budapest local time.
- API query ranges use Budapest local time.
- Raw log timestamps are assumed Budapest local unless a source clearly indicates otherwise.

Observation granularity:

- one row = one timestamped value from one stream

The `streams` table stores stable stream metadata. The `observations` table stores only:

- `timestamp`
- `stream_id`
- `value`

`stream_availability` is derived from `streams LEFT JOIN observations`; it is not a core table.

## Metadata Flow

`dev/db/metadata/generate_stream_metadata.py` generates:

- `dev/db/metadata/stream_metadata.csv`

from:

- `scope_metadata.csv`
- `scope_list.csv`
- `variable_list.csv`

The generated stream catalog is loaded into DuckDB by `db_manager.py`.

Current loaded stream count in `STATUS.md`: `303`.

## Key Scripts

### `dev/db/db_manager.py`

Database management script using a top-level `MODE`.

Current responsibilities:

- initialize/migrate schema
- load stream metadata
- maintain `stream_availability`
- write availability CSV
- write availability HTML timeline

It should not parse raw logs.

### `dev/db/log_parser.py`

Source-specific ingestion script using a top-level `MODE`.

Current responsibilities:

- read daily NDJSON log files
- map raw source names to canonical `stream_id`s
- normalize timestamps and units
- insert into `observations`

Default mode is:

- `list_modes`

Broad imports can be long. The working rule is: the assistant prepares/debugs parser modes, but the user runs long prepared imports locally, then asks the assistant to inspect results/errors.

### `dev/db/db_queries.py`

Read-only Python query layer.

### `dev/db/db_client.py`

Remote Python client wrapper intended for third-party scripts. It calls the JSON server and exposes `DbApi`.

Current functions:

- `get_streams()`
- `get_stream_availability()`
- `query_observations(...)`
- `query_observations_grouped(...)`
- `query_summary(...)`
- `query_summary_wide(...)`

This is intended to be reused by a future HTTP API server rather than duplicating SQL in the server layer.

### `dev/db/API_local_test.py`

Local sandbox for interacting with `db_queries.py`. It is not a formal test suite.

### `dev/db/PLAN.md`

Design/roadmap document. It should describe intended direction and design rules, not live implementation status.

### `dev/db/STATUS.md`

Live implementation status for the `dev/db` data layer. It records what currently exists, loaded streams/observations, parser modes, and smoke-check status. Update it when implementation state changes. Do not use it for transient sandbox output.

## Current Ingestion Modes

`log_parser.py` currently lists these modes:

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

Editable raw-to-canonical mappings live near the top of `log_parser.py`. Some radiator/thermostat mappings are explicitly provisional.

## Current Loaded Observations

As recorded in `STATUS.md`, only a small amount of real data has been loaded so far:

- `room.1.temperature`
- `room.1.humidity`
- `gas_meter.main.impulse`

One loaded stream is partial, and gas impulses are currently a one-day test import.

## Query/API Design Choices

The API exposes generic summary metrics and does not enforce stream-specific semantic rules. Some mathematically valid calls may be domain-meaningless. Documentation/examples should guide meaningful use.

Current summary fields:

- `mean_value`
- `min_value`
- `max_value`
- `stddev_value`
- `observation_count`

`PLAN.md` also includes planned `sum_value`, but implementation status should be checked before relying on it.

Raw observations remain long-format. Joined analytical tables should use binned summaries, especially via `query_summary_wide(...)`.

## Tests And Smoke Checks

There is no formal test suite yet.

Current smoke-check practice:

- run `python -m py_compile ...` for changed scripts
- run `dev/db/API_local_test.py` for local API shape checks
- run parse-only checks on one representative daily file per `log_parser.py` mode before broad imports

The latest parser smoke-check result is recorded in `STATUS.md`.

## Inputs Outside `dev/db`

Raw logs are read from:

- `data/logs/`

Existing service scripts can clarify log formats and source locations:

- `services/data_formatter.py`
- `services/heating_control.py`
- source-specific logger scripts under `services/`

These are inputs/context for the db project, not part of the db layer itself.

## Avoid Broad Scans

Avoid scanning these broadly:

- `data/logs/` raw logs
- `data/formatted/` or generated data outputs if present
- `dev/db/store/` DuckDB binaries and backups
- `dev/db/__pycache__/`
- `analysis/`
- `dev/dut/`
- `dev/heatmeter_reading/`
- `config/secrets_and_env/`

When logs are needed, inspect a specific source/date/file.

## Exact Next Task

The next clear task is to inspect heating-control activity logs referenced by `services/data_formatter.py`, then plan and add `log_parser.py` support for heating system activity streams such as:

- room set temperatures
- room heating votes/on-off state
- heating-cycle pump votes/on-off state
- boiler/heating main state

Do this incrementally and keep raw-to-canonical mappings explicit.
