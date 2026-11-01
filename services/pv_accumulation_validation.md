# PV inspection watchdog: accumulated evidence and separate fault patterns

Local implementation and retrospective evaluation, 1 November 2026.

Deployment update: the implementation was published to GitHub and installed on
the Pi on 1 November 2026. The scheduled wrapper and email delivery are now
enabled. See `pv_performance_watchdog.md` for operation and deployment evidence.
The investigation and publication-block notes below record the earlier state.

The new detector raises an inspection from **11 March 2026 observations on
logged PV1 and PV2**, before the two-panel repair on 13 March. A daily run after
the day closes would report this on 12 March. The independent array track
crosses on 7 March, but its default seven-day weather lag would postpone that
report until 14 March. No historical notifications were actually sent.

This is a successful development regression case, **not an independent estimate
of fault detection accuracy**. March was already known during development, and
the first reference split failed. The frozen earlier failures remain available.

## What changed

`pv_accumulating_monitor.py` supplies `calibrate`, `replay`, and persistent
`shadow` commands. It accumulates modest shortfalls instead of requiring each
day to exceed the old 20% conservative threshold. Its output is an inspection
recommendation with evidence, rather than a claim of a defective panel.

There are two independent tracks:

- **Whole array:** total AC output against comparable historical sun position,
  independent ERA5 radiation, diffuse fraction, and temperature. Shared loss is
  compatible with soiling, but does not establish that cause.
- **Relative input:** each calibrated logged input against its empirical peers
  under comparable conditions. This can expose local imbalance. Shared MPPT
  voltages and uncertain physical string labels limit localization. A relative
  loss does not prove which physical string or panel is faulty.

Both can be open simultaneously. Uniform loss can leave relative ratios
unchanged; localized shading or uneven dirt can also produce relative loss.
The report describes the observed pattern and explicitly leaves cause and
physical string mapping unconfirmed.

The user's preference is sensitivity: inspecting panels is easy, missing a
fault is costly. Windows contain 3–10 qualifying days within 21 calendar days.
The mean of bias-corrected daily shortfalls is compared with an earlier
calibration threshold, with a 3% floor. At least two thirds of the days must
support a loss of at least 1.5%. Daily contributions are capped at 25% so one
shutdown cannot dominate otherwise normal days. These thresholds are empirical
inspection rules, not confidence levels or false-alarm guarantees.

Three qualifying days below 1.5% clear an incident. Missing evidence pauses
recovery. Open incidents persist through gaps, and repeated runs do not emit
duplicate opening events. No reference or threshold adapts to newly low output.

## Reference choice and leakage controls

1. The first attempt used 4 April–December 2024 as reference, January–June 2025
   for calibration, and July–December 2025 as a reserved background check.
   It produced seven background inspection openings. It then failed March 2026
   because essentially no comparable spring reference hours were available:
   zero qualifying array days during 1–12 March. This was a coverage failure,
   not evidence of healthy production.
2. After observing that coverage failure, the reference was extended through
   June 2025. July–December 2025 became calibration. **It is no longer an
   independent validation period for this revised model.** The algorithm,
   weather eligibility rules, 90th-percentile calibration rule, 3% floor,
   persistence and recovery parameters were unchanged.
3. The revised model was fitted using only pre-2026 observations, saved, and
   hash-checked before replaying January–26 October 2026. No 2026 observations,
   repair dates or cleaning dates enter fitting or threshold calculations.
   The March observations influenced the overall development process; this
   prevents a claim that the test was blind or that overfitting has been ruled
   out. Future labelled observations are still needed.

The final reference interval is `[2024-04-04, 2025-07-01)`, and calibration is
`[2025-07-01, 2026-01-01)`. It has 1,790 suitable array reference hours and 85
qualifying array calibration days. PV1–PV4 have 91–95 calibration days.
PV6 and PV8 have only 27 and 29; their relative detectors are explicitly
unavailable. The array track still includes their contribution to AC production.

History exports are restricted to files acquired before the relevant cutoff.
Reference and calibration periods are not certified healthy; existing faults
or dirt can bias the expected output. Regional retrospective ERA5 weather is
not measured roof irradiance or a point-in-time weather archive.

Final model identity:
`87d4dc0625aa9068e51bb2c8d175ab4421f060fcc761ac140fd8cb876ec6fdf8`.
Source hashes, weather URLs, response hashes, input quality, calibration windows,
and every evaluation decision are saved in the JSON artifacts.

## March result and practical timing

| Track | Evidence window | Accumulated shortfall | Threshold | Crossed | Default daily reporting date |
|---|---|---:|---:|---|---|
| Whole array | 4–7 March | 8.04% | 7.05% | 7 March | 14 March, subject to weather availability |
| Logged PV1 | 9–11 March | 3.26% | 3.00% | 11 March | 12 March |
| Logged PV2 | 9–11 March | 4.31% | 3.00% | 11 March | 12 March |

These crossings precede the separate zero-output observation on 12 March;
that shutdown did not cause them. The array's median corrected shortfall on
the ten qualifying days during 1–11 March was 8.66%.

PV2 recovers on 23 March; PV1 does not recover until 18 April, and the array
until 4 April. The result therefore does not isolate the effect of the repair.
Cleaning on 17 March, weather error and other performance changes remain
possible contributors. The damaged physical string is not identified.

## Alert burden and sensitivity controls

The 299-day 2026 replay used 46,499 accepted unique observations.

| Track | Qualifying days | Inspection openings | Calendar days with an inspection open |
|---|---:|---:|---:|
| Array | 160 | 6 | 117 |
| PV1 | 165 | 3 | 76 |
| PV2 | 163 | 2 | 39 |
| PV3 | 156 | 1 | 41 |
| PV4 | 157 | 0 | 0 |

There are 12 openings in total, nine outside the three March openings. These
are not 12 proven faults, or nine proven false positives: background health is
unlabelled. Open durations include days without enough new evidence to recover.
This intentionally sensitive policy can leave an inspection open for weeks.

Before evaluating the revised model, synthetic controls were specified as
5% and 10% additional residual loss over 21 days from the first of each month
April–September 2026, separately on all five calibrated targets. Of 60 controls,
16 overlap an inspection in the unchanged background and cannot demonstrate
incremental detection. All remaining **44/44** produced an inspection: 20/20
relative-input cases and 2/2 array cases at each loss size. This small array
sample is a material limitation. Eligibility and references stay fixed, and
these controls do not simulate electrical coupling, physical panel faults,
weather changes, or reliable field detection rates.

## Operation and verification

The service uses only the Python standard library. It never sends messages,
installs timers, or controls equipment. State is locked and written atomically.
An existing calibration file cannot be overwritten; state/model mismatches and
invalid intervals fail visibly. Output paths cannot overwrite the input trees
or the model.

Relative checks process completed days through yesterday. The array has its own
cursor and defaults to seven-day-old observations. Missing weather is retried;
it cannot consume the pending array interval or stop relative checks. Reports
include last evidence dates, evidence age, unavailable targets and explicit
monitoring gaps. An absence of alerts is not presented as proof of health.

56 synthetic tests pass, covering accumulation, noise, one-day shutdowns,
calibration leakage, model integrity, missing data, recovery, idempotence,
separate cursors, weather failure/retry, DST, and file boundaries. Earlier
detector tests continue to pass. Tests do not assert that the known March event
must be detected.

Read-only Pi evaluation streamed code and models into memory; only derived
artifacts were saved locally. No Pi files, services or devices were changed.
The actual shadow command was also exercised in memory against October logs,
with the date fixed to 1 November. It processed relative inputs through
31 October and array observations through 25 October, as intended. Starting
fresh on 1 October, it opens PV1/PV2 inspections on 3 October and an array
inspection on 13 October; all remain open at the preview cutoff. These current
inspection suggestions also have unconfirmed causes. Their opening dates differ
from the full-year replay because this preview starts with empty October state.

The current service can be reproduced after publication with an explicit model:

```text
python -B -m services.pv_accumulating_monitor replay --model services/pv_accumulation_model_2025.json --logs /media/pi/program_stick/kazanfutes/data/logs --from 2026-01-01 --until 2026-10-27 --allow-legacy-timestamps
python -B -m services.pv_accumulating_monitor shadow --model services/pv_accumulation_model_2025.json --logs /media/pi/program_stick/kazanfutes/data/logs --allow-legacy-timestamps
```

For persistence, supply `--state` with a reviewed writable runtime path outside
input trees. The second command above writes no state and sends no notification.
Calibration reproduction uses the explicit intervals above and the notebook
export directory; exact replay uses the saved model because weather retrieval
metadata can change its identity. `plot_pv_accumulation_validation.py` renders
the saved aggregate report.

## Artifacts and publication

- `pv_accumulation_model_2025.json`: final reference and frozen calibration.
- `pv_accumulation_calibration_2025_h2.json`: final fitting evidence and protocol.
- `pv_accumulation_seasonal_validation_2026.json`: final replay and controls.
- `pv_accumulation_shadow_preview_2026-11-01.json`: actual service preview from
  October observations, with in-memory model/state and no notifications.
- `pv_accumulation_validation_2026.png`: evidence plot and open inspections.
- `pv_accumulation_model_2024_2025.json`, `pv_accumulation_calibration_2025.json`,
  and `pv_accumulation_validation_2026.json`: preserved first attempt, including
  its failed March coverage and reserved 2025 background results.
- `pv_performance_validation.md` and its older JSON artifacts: preserved
  previous detector failures.

Before deployment, publication and notification scheduling were pending. The
original checkout was 265 commits behind fetched `origin/main`, with unrelated local
edits to the presence calculator, PV logger, service-data watchdog, occupancy
unit/utilities and a deleted presence-calculator test. The approved Git sync
flow refuses to include those changes without an explicit reconciliation
decision. The full status also lists extensive pre-existing configuration,
runtime-data, system-state and development-directory changes/deletions; these
were not investigated or modified. The local PV logger and service-data
watchdog edits already match `origin/main`, while four other code paths differ.
Blindly including all dirty files would therefore be inappropriate. A temporary
sparse checkout of the same `main` branch, excluding data and publishing only
the reviewed PV additions through the approved flow, was subsequently authorized
and used. No unrelated edits were discarded, committed or pushed.
