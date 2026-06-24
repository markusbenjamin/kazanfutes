# DuckDB Data Layer Plan

This is the working plan for the incremental DuckDB-based data layer.

## Core Database Model

Core tables:

- `streams`
- `observations`

Derived view:

- `stream_availability`

One observation row means:

- one timestamped value
- from one stream

Missing data is represented by absent observation rows.

## Script Responsibilities

### `db_manager.py`

Framework/database management:

- initialize schema
- load generated stream metadata
- create/update SQL views
- generate availability HTML
- generate availability CSV

It should not parse raw source logs.

### `log_parser.py`

Raw log ingestion:

- read daily log files
- translate raw names to canonical stream IDs
- normalize timestamps to Budapest local time
- convert raw values to canonical units
- insert observations

It should grow source by source, carefully.

### `db_api.py`

Reusable read-only query layer:

- list streams
- list availability
- query raw observations
- query raw observations grouped by time bin
- query summaries
- query summaries in wide form

The future HTTP server should call this module rather than duplicating SQL.

### `API_local_test.py`

Local sandbox for testing `db_api.py` directly.

## Design Rules

- Metadata uses canonical names, not messy raw log names.
- Importers handle raw-to-canonical mapping.
- The database does not manage devices.
- Device-level issues such as battery warnings belong in Python services, not in DuckDB metadata.
- The third party should only get read access.
- The future server should be reachable through Tailscale, not public internet exposure.
- `stream_availability` is a summary, not gap analysis.
- Gap-aware availability should be added later through binned availability.
- The database timestamp convention is Budapest local time.
- The observation timestamp column is named `timestamp`.
- Raw log timestamps are assumed to already be Budapest local time unless a source clearly indicates otherwise.
- If a source provides UTC, epoch, or offset timestamps, importers convert those to Budapest local time before inserting.
- Summary/query APIs should expose generic metrics rather than enforce stream-specific semantic rules.
- The API may allow mathematically valid but domain-meaningless calls; documentation and examples should guide users toward meaningful metrics.

## Agent Responsibilities

Query/API layer:

1. Maintain read-only query functions in `db_api.py`.
2. Keep query logic reusable by the future HTTP server.
3. Support raw observation queries and summary/statistical queries.
4. Keep query shapes explicit:
   - long raw observations
   - long binned summaries
   - wide/pivoted binned results
   - grouped raw observations as nested JSON-like data
   - later named derived metrics
5. Keep local sandbox scripts available for trying query behavior before server work.

Availability/reporting layer:

1. Maintain stream availability summaries.
2. Add gap-aware binned availability views/reports where first/last/count is insufficient.
3. Keep HTML and CSV outputs aligned with the database views.

Near-term import work:

1. Extend `log_parser.py` carefully, source by source.
2. Import a small number of additional streams:
   - one additional room stream
   - one additional room variable
   - one non-room stream, such as weather station temperature
3. Keep raw-to-canonical mapping explicit in importer code.
4. Validate imported streams through availability outputs before broadening further.
5. Do not spend agent time running long prepared import scripts. Once a script is ready, the agent should recommend that the user run it locally, then inspect results or errors afterward.

Later implementation work:

1. Add HTTP server layer.
2. Expose read-only endpoints:
   - `/api/streams`
   - `/api/availability`
   - `/api/query`
   - `/api/summary`
   - report downloads
3. Keep server logic thin by calling `db_api.py`.
4. Improve availability viewer with gap-aware timelines.
5. Refine wide/pivoted summary outputs as more streams are imported.
6. Add grouped raw observation output if users need raw readings organized by bins without timestamp alignment.
7. Add named derived metrics after the base streams and summary semantics are clear.
8. Write final README/manual once the workflow is stable enough for handover/use.

## Query Shape Roadmap

### Long Raw Observations

Returns one row per observation.

Example columns:

- `timestamp`
- `stream_id`
- `variable`
- `scope_type`
- `scope_id`
- `unit`
- `value`

This is the simplest and most faithful representation of the stored data.

### Long Binned Summaries

Returns one row per stream per time bin.

Example columns:

- `bin_start`
- `stream_id`
- `variable`
- `scope_type`
- `scope_id`
- `unit`
- `mean_value`
- `min_value`
- `max_value`
- `observation_count`

This is useful for hourly/daily summaries and should remain the standard summary-query shape.

Summary statistics:

- `mean_value`
- `min_value`
- `max_value`
- `stddev_value`
- `sum_value`
- `observation_count`

Numeric summary values are rounded to the requested measurement precision.

The API should not forbid summary metrics that are unhelpful for a given stream. For example, `mean_value` is usually meaningful for temperature, while `observation_count` or `sum_value` is usually meaningful for impulse/event streams. The caller chooses the metric; examples and documentation explain the recommended choices.

### Wide/Pivoted Binned Results

Returns one row per time bin, with selected streams or metrics as columns.

Example columns:

- `bin_start`
- `gas_impulse_count`
- `heat_delivery`

This should be the preferred joined-stream format, because streams usually do not share exact timestamps.

### Grouped Raw Observations

Returns one object per time bin. Inside each bin, raw observations are grouped by stream while preserving their original private timestamps.

Example shape:

```json
[
  {
    "bin_start": "2024-12-01T00:00:00",
    "bin_end": "2024-12-01T01:00:00",
    "streams": {
      "room.1.temperature": [
        {"timestamp": "2024-12-01T00:01:55", "value": 17.9}
      ],
      "room.1.humidity": [
        {"timestamp": "2024-12-01T00:02:10", "value": 52.9}
      ]
    }
  }
]
```

This is a JSON/API shape, not a CSV/table shape. It is useful when users want raw readings organized by period without pretending timestamps align.

### Named Derived Metrics

Derived metrics are named query recipes built from one or more base streams.

Examples:

- `gas_impulse_count`: count gas-meter impulse events per bin
- `heat_delivery`: derive delivered heat from heatmeter or heating-cycle streams

This should be added only after base stream imports and summary semantics are stable.

## User Responsibilities

Domain/modeling work:

1. Map the physical locations of scopes/streams on the graphical floorplan/layout so external users can interpret scope IDs.
2. Decide whether main electric meter tariff breakdown fields are useful enough to keep.
3. Provide/approve exact mapping notes for electric submeters, since circuits are not exact room measurements.
4. Decide whether stream descriptions need human-friendly variable labels beyond generated labels.
5. Review generated metadata and flag canonical naming mistakes.

Deployment/access work:

1. Decide where the first live API server should run.
2. Provide Raspberry Pi/Tailscale details when server deployment begins.
3. Decide who should get Tailscale access.
4. Decide whether a simple read API token is needed in addition to Tailscale.

## Shared Checkpoints

Before broad imports:

- Confirm that `db_api.py` raw and summary query shapes are acceptable.
- Confirm whether early users need long-format data only, grouped raw data, or also wide/pivoted binned outputs.
- Confirm that the availability CSV/HTML outputs communicate the right information.
- Confirm that the first few imported streams look correct.

Before server deployment:

- Confirm read-only endpoint list.
- Confirm Tailscale access model.
- Confirm where logs, database, and server process will live on the Raspberry Pi.

Before third-party use:

- Confirm metadata CSVs are final enough for their framework.
- Confirm API query examples and report outputs are understandable.
- Confirm scope/floorplan documentation is available.
- Write a final README/manual covering setup, operation, API usage, reports, and maintenance.
