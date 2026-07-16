# Current Handoff

Generated: 2026-06-25

This file is the live baton for context switches. Keep it short, operational,
and current. Do not use `STATUS.md` as a live run log.

## Document Roles

- `PLAN.md`: roadmap, design direction, future work.
- `STATUS.md`: durable implementation state and stable known limitations.
- `HANDOFF.md`: current operational context, latest relevant artifacts, blockers,
  fragile config, exact next steps.

Decision: keep `STATUS.md`, but only for durable state. Use this file for active
or interrupted work.

## Active Context

Current active issue: overnight DB import/rebuild.

Latest verified DB snapshot from the last check:

- `streams`: `303`
- `observations`: `8,571,823`
- loaded streams in `stream_availability`: `143`

The DB is not empty. A substantial partial import succeeded.

## Latest Relevant Artifacts

Latest relevant run artifacts:

- transcript: `dev/db/test_reports/overnight_import_20260625_003732.log`
- error report: `dev/db/test_reports/overnight_import_errors_20260625_003732.txt`

Read the latest error report first. For this run, also inspect the matching
transcript tail because the error-only report captured the final runner failure,
while the transcript also showed preceding mode failures.

## Latest Failure

The latest run failed because DuckDB could not open:

- `dev/db/store/observations.duckdb`

The lock holder reported in the latest transcript/error report was Git for
Windows:

- `C:\Program Files\Git\mingw64\bin\git.exe`
- PIDs reported then: `23204`, `24668`

Do not assume those PIDs are still current. Check current process/file-lock state.

The run succeeded through `import_pv_inverter`. Then these failed due the same
DB lock:

- `import_weather_station`
- `import_outdoor_weather_com`
- final availability refresh

## Fragile Config

Current `log_parser_overnight_import.py` config previously had:

```python
CLEAR_OBSERVATIONS_BEFORE_IMPORT = True
CLEAR_OBSERVATIONS_ACK = "I_BACKED_UP_AND_WANT_TO_CLEAR_OBSERVATIONS_BEFORE_IMPORT"
CREATE_DB_BACKUP = False
IMPORT_EXISTING_POLICY = "skip_existing"
ENSURE_DB_SCHEMA_AND_METADATA = True
```

Before rerunning, inspect the current config directly.

If the user wants resume/fill-missing mode, set:

```python
CLEAR_OBSERVATIONS_BEFORE_IMPORT = False
IMPORT_EXISTING_POLICY = "skip_existing"
```

If the user explicitly wants a full rebuild from zero, `CLEAR_OBSERVATIONS_BEFORE_IMPORT`
may stay `True`, but confirm their backup is good.

## Next Steps

1. Check and remove/stop whatever is holding the DuckDB file open.
2. Confirm whether the user wants resume or full clean rebuild.
3. For resume, make sure `CLEAR_OBSERVATIONS_BEFORE_IMPORT = False`.
4. Rerun:

```powershell
cd C:\Users\Beno\Documents\SZAKI\dev\kazanfutes\dev\db
python log_parser_overnight_import.py
```

5. After the run, inspect the newest `overnight_import_errors_*.txt`.
6. If clean, inspect/regenerate availability outputs and update `STATUS.md` with
   stable final counts.

## Do Not Do

- Do not blindly rerun with `CLEAR_OBSERVATIONS_BEFORE_IMPORT = True`.
- Do not treat `STATUS.md` as the live run handoff.
- Do not inspect broad logs; only inspect the latest relevant error report and
  its matching transcript unless the user asks for broader investigation.
