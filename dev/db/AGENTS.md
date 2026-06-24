# AGENTS.md — working rules for `dev/db`

This file defines how an agent should work in `dev/db`.

It is not project status, not a roadmap, and not a task list.

## document boundaries

Use the existing documents as the source of truth:

- `PROJECT_ORIENTATION.md` — what this subproject is
- `PLAN.md` — design direction and roadmap
- `STATUS.md` — current implementation state
- `REPO_MAP.txt` — repository navigation and large/ignored areas

Do not duplicate those documents here.

Do not put current next steps, live observations, stream counts, loaded-data status, or design decisions in this file.

When implementation state changes, update `STATUS.md`, not this file.

When design direction changes, update `PLAN.md`, not this file.

When repository navigation changes, update `REPO_MAP.txt`, not this file.

## default startup procedure

At the start of work in `dev/db`, read:

1. `PROJECT_ORIENTATION.md`
2. `STATUS.md`
3. `PLAN.md`
4. `REPO_MAP.txt`

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

`db_api.py` provides read-only query functions.

Do not move responsibilities between these files unless explicitly asked.

Do not duplicate query logic into a future server layer when `db_api.py` can be reused.

## import discipline

Do not run broad historical imports by default.

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

After a meaningful implementation change, or before stopping at a context/usage boundary, update `STATUS.md` if the change affects the live project state.

Keep the update compact. Record only:

- what changed
- what was checked
- whether it worked
- any blocker or unresolved decision
- the next useful step

Do not update `STATUS.md` for purely exploratory reads, failed experiments with no retained change, trivial typo fixes, or local scratch work that does not affect the project state.

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
- the context has become large enough that `STATUS.md` should be updated before continuing
