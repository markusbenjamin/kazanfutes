# AGENTS.md — working rules for `dev/db`

This file defines how an agent should work in `dev/db`.

It is not project status, not a roadmap, and not a task list.

## document boundaries

Additional handoff documents:

- `HANDOFF.md` - current active handoff for context switches, interrupted runs, or resumed work
- `RASPI_HANDOFF.md` - Raspberry Pi/Tailscale access handoff for dev API testing

Use the existing documents as the source of truth:

- `PROJECT_ORIENTATION.md` — what this subproject is
- `PLAN.md` — design direction and roadmap
- `STATUS.md` — durable current implementation state, not a live task log
- `HANDOFF.md` — latest operational baton for the next agent when context changes
- `REPO_MAP.txt` — repository navigation and large/ignored areas

Do not duplicate those documents here.

Do not put current next steps, live observations, stream counts, loaded-data status, or design decisions in this file.

When durable implementation state changes, update `STATUS.md`, not this file.

When stopping mid-task, switching context, handing off an interrupted run, or leaving a fragile operational state, write/update `HANDOFF.md`.

When design direction changes, update `PLAN.md`, not this file.

When repository navigation changes, update `REPO_MAP.txt`, not this file.

## default startup procedure

At the start of work in `dev/db`, read:

1. `PROJECT_ORIENTATION.md`
2. `STATUS.md`
3. `HANDOFF.md`
4. `PLAN.md`
5. `RASPI_HANDOFF.md`
6. `REPO_MAP.txt`

Then inspect only files directly needed for the current task.

Do not rediscover the whole repository.

## task discipline

Work in small, bounded steps.

Before editing, identify the smallest useful task that satisfies the user's request.

Do not broaden the task unless the user explicitly asks.

Prefer one source family, one parser mode, one API change, or one documentation update per pass.

Avoid unrelated refactors.

Do not create commits unless explicitly asked.

## context discipline

Keep context use low.

Do not paste or print large file contents, raw logs, full directory trees, long diffs, or broad grep results.

Use compact summaries, schemas, counts, and small representative samples.

When searching, restrict by path and purpose.

When logs are needed, inspect one specific source and preferably one specific date/file.

Do not broadly scan directories marked large or ignored in `REPO_MAP.txt`.

## database discipline

Preserve the current database model unless the user explicitly asks for a schema change.

Do not add metadata fields, lifecycle tracking, status columns, or new tables just because they seem useful.

Do not invent stream IDs, variables, or scope types silently.

Raw log names may differ from canonical stream IDs. Handle this with explicit raw-to-canonical mappings in parser code.

If a raw field has no clear canonical stream, pause and report the required naming decision.

Missing data should remain represented by absent observation rows.

## script responsibility discipline

Keep responsibilities separated.

`db_manager.py` manages schema, metadata loading, views, and availability outputs.

`log_parser.py` parses source logs and imports observations.

`db_queries.py` provides read-only query functions.

Do not move responsibilities between these files unless explicitly asked.

Do not duplicate query logic into a server layer when `db_queries.py` can be reused.

## import discipline

Do not run broad historical imports by default.

Before preparing or recommending a broad import, require an explicit source-route
review:

1. Read `stream_ingestion_routes.csv`.
2. Confirm every source log pattern maps to the intended stream target family.
3. Treat non-empty comment/issue columns or unresolved markers as blockers.
4. Demand user confirmation where the route depends on domain semantics.
5. Do not infer source semantics from variable names alone.

Known semantic traps:

- `occupancy/occupancy.json` is derived and should not be used as a raw ingestion source unless the user explicitly re-approves it.
- `presence/presence_all.json` feeds `room.*.presence_detected`, not `room.*.occupancy_state`.
- `thermostats/thermostats_state.json` feeds radiator valve state, not radiator temperature.
- Thermostat log names are historical valve labels, not reliable room labels. Resolve log key/name to thermostat ID first, then use `system/setup.json` as the authoritative thermostat-ID-to-room source.
- For rooms with multiple radiators and fewer TRVs, store each TRV valve state on the first radiator in its controlled group; derive this from thermostat order in `system/setup.json` plus radiator order in `metadata/scope_list.csv`.
- `service_execution/heating_control/heating_control.json` does not feed radiator valve state; use thermostat logs for that physical state.
- `aqara_and_nous.json` currently routes all Aqara fields, with Aqara `presence` mapped to `room.*.occupancy_state`, and only Nous CO2.
- Multiple Aqara devices in one room must remain independent observations for temperature, humidity, and illuminance; only Aqara occupancy is OR-combined per room/timestamp.
- `replace_existing` rewrites all rows at matching timestamp/stream keys for the selected import, so require narrow target/date review before using it for repairs.

For parser work:

1. inspect the source format narrowly
2. add or adjust the parser
3. run a small smoke check
4. report what the user should run locally for longer imports

Long imports should normally be run by the user locally after the parser is prepared.

## validation discipline

Prefer compact validation.

Use checks such as:

- Python compile checks for changed scripts
- one-file or one-day parser smoke checks
- small API-shape checks
- availability regeneration after successful import

Do not treat a broad import as validation unless explicitly requested.

## handoff discipline

Keep `STATUS.md` and `HANDOFF.md` separate:

- `STATUS.md` records durable implementation state: current scripts, behavior, schema assumptions, stable checks, and stable known limitations.
- `HANDOFF.md` records the live baton: what is currently happening, latest relevant files/reports, fragile config flags, blockers, exact next commands, and what not to do.
- `PLAN.md` records roadmap/design direction, not live state.

After a meaningful implementation change, update `STATUS.md` if the change affects durable project state.

Before stopping at a context/usage boundary, interrupted run, or fragile operational state, update `HANDOFF.md`.

Keep the update compact. Record only:

- what changed or was observed
- what was checked
- whether it worked
- any blocker, fragile config, or unresolved decision
- the exact next useful step

Do not update `STATUS.md` for purely exploratory reads, failed experiments with no retained change, trivial typo fixes, or local scratch work that does not affect the project state.

Do not use `STATUS.md` as a blow-by-blow run log. For volatile run state, update `HANDOFF.md` instead.

Final responses should be short and operational:

- changed
- checked
- remaining
- user action needed, if any

## pause conditions

Pause and report before continuing when:

- the next step is a user design/domain decision
- a stream or variable name would need to be invented
- a broad log scan would be required
- a long import would be required
- the task would cross file responsibilities
- the requested change would alter the database model
- the context has become large enough that `STATUS.md` or `HANDOFF.md` should be updated before continuing
