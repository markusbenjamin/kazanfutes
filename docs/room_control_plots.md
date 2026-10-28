# Room tracking diagnostics

Ordinary room hover, ordinary click and Ctrl+click retain their existing
behaviour. Alt+click a room pins its phase-plane plot by default, with the
control summary available as the second selector option. Main and cycle
infobox Alt+clicks likewise default to the phase plane, with daily error second.
An explicitly selected alternative is remembered for that room or infobox.
Clicking away restores the ordinary plot. Date arrows sit in the plot frame's
top corners. Past dates appear beside `rögzítve` above the dotted frame; today's date is omitted.
No future days can be selected.

The primary metric is mean absolute temperature error weighted by the room's
associated cycle's commanded circulation multiplied by mean valve opening
(0–1). Rooms without smart valves use opening 1. It is not electrical power,
room demand, measured heat delivery, or a verdict on controller quality.
The main-infobox secondary `napi hiba` view shows a single-day error curve for
each controlled room. Error is exactly zero for a known room heat-demand vote of zero, and
`set_temps - measured_temps` while that room demands heat. Positive K means
below target, negative K means above. Room demand is not inferred from cycle
pumps or valve opening. Each curve uses the existing room colour and has a
room-name tooltip. Coloured room names wrap below the title in the same font
family at a smaller 4.5-unit size (title: 7), without numerical error readouts.
Up to six room names share one line; the all-room legend uses two balanced
lines, never three, leaving more room for the chart.
The former right-hand value list is
removed, restoring the full chart width. A cycle infobox's secondary `napi hiba`
view is filtered to controlled rooms assigned to that cycle by the existing
room metadata. Date navigation preserves this cycle filter. Main-infobox
Alt+click still shows all controlled rooms. Corner arrows change days; missing demand and unavailable or
stale temperatures during demand are gaps, never false zero. Curves are steps,
not smoothed, and gaps longer than three minutes break them.
Small 8-unit, 6%-opacity reddish `alulfűtés` and bluish `túlfűtés` watermarks sit
at the upper-left and lower-left edges of the positive and negative ranges.
They sit behind the curves and do not intercept
pointer events.

The former overview grid is frozen in `drawRoomControlOverview`, no longer
bound to Alt+click. Its implementation and KPI definitions are preserved:
one room per row, one calendar day per
column. A four-state selector switches below/above target crossed with heating
on/off, preserving the selected end date. Each cell shows mean absolute error
in K only during that case: `quadrant_error_kh / (quadrant_seconds / 3600)`.
No observed duration in a case means a dash, not zero error. Subtle gray in-cell bars use
one shared linear scale (zero to the maximum visible MAE), so larger errors
remain easy to spot without crossing curves or overlapping labels. Missing
days or days without observed heating show a dash rather than false zero.
Cell tooltips show that case's error, valve-weighted duration, share within its
heating-on/off state, and data coverage. Room labels start at the frame's small
left inset; their measured text widths reserve only the needed name column.

The room summary compares its anchor day with the preceding seven calendar
days. It shows valve-weighted heating MAE and occupied-only comfort: the share
of confirmed occupied time with valid temperatures within ±0.5 K of the
requested temperature. Unoccupied, unknown-presence and stale-presence periods
are excluded. Comfort has its own occupied-temperature denominator, independent
of whether pump/valve state is known. No valid occupied time means unknown, not
zero comfort. Presence observations are step-held for at most 180 seconds.
Rolling MAE and percentages are weighted by their matching observed durations,
not unweighted daily means. Today is partial.

Separate heating-on/off stacked bars replace the four-spoke diamond. Each
state is normalized to its own observed, valve-weighted duration, so a long
heating-off day cannot visually swamp the heating-on distribution. Both
show below-target, within ±0.5 K, and above-target shares. The heating-on area
is lightly pink; heating-off is lightly blue. Segments are green for below/on
and above/off, red for above/on and below/off, and white within the band.
Each bar is labelled `ma` (or its selected date) or `7 nap` on the left;
all outlines are identical. Durations appear at the right: hours for the
selected day, hours/day for the previous seven days, divided by the count of
days with valid observations rather than treating missing days as zero.
These are observed daily averages, not extrapolations to full 24-hour coverage.
Tooltips state the number of observed days. The corresponding durations include
very short nonzero heating periods. A state with no observations shows a dash,
not a false zero-error distribution.

A 25% mean opening while circulation is on allocates 25% of that interval
to heating on, 75% to off. These are equivalent weighted durations, not measured
heat delivery. The requested red/green combinations distinguish the four
cases, not a causal verdict on controller faults. In particular, off-state
above-target time may simply be cooldown or setback. For the stacked bars,
in-band durations are the state's duration minus its two out-of-band durations.
All displayed temperature differences use kelvin. Existing `_c` data-field
names are retained for compatibility; difference values are numerically unchanged.

## Data pipeline

`utils/room_control_kpi_formatter.py` reads the control execution log's already
calculated `measured_temps`, the ordinary room plot's `set_temps`, and
`pump_votes`, `valve_states`, and observed `occupancy`. It neither generates
`control_temp` nor changes sensor selection.
The recorded targets and commands are step-held, never linearly interpolated.

Source observations are held for at most 180 seconds. Sensor timestamps older
than one hour, future sensor timestamps beyond 30 seconds, explicit unknown
values and incomplete snapshots are excluded. Smart-valve rooms require all
configured valve openings to be known and held at most 180 seconds when their
cycle is circulating. These limits are exported in
the result. Unknown coverage never counts as comfort or zero tracking error.
Uncontrolled rooms are excluded using `system/setup.json` read-only.

The normal data formatter writes schema-version-3 daily `room_control_kpis.json`
with additive durations and error integrals plus MAE, signed bias, comfort and
coverage. `occupied_seconds` is the comfort denominator; `comfort_seconds` is
its in-band subset. `quadrant_error_kh` stores each of the four cases' absolute
error integral, alongside `quadrant_seconds`. The dashboard refuses older
schemas rather than displaying all-time comfort as occupied-only comfort.
The old `room_KPIs.json` stream is unchanged. There is no new device polling,
relay operation, Firebase write, or scheduler/control change.

The same formatter also publishes daily `room_control_errors.json` from complete
end-of-run control snapshots, keeping room demand, setpoint and measured
temperature together instead of mixing independently timestamped log records.
It uses the existing calculated `measured_temps`, logged `set_temps_interp`
and `room_states`. The logged target is used directly, with no nominal-target
fallback or dashboard reconstruction; no `control_temp` or alternate sensor
calculation is introduced. Sensor-age
validation during demand matches the one-hour KPI limit. No-demand periods
are zero by definition even if their temperatures are unavailable. Uncontrolled
rooms are excluded. The existing daily KPI schema and room Alt+click views are
unchanged.

## Boiler energy KPI

Alt+click `boiler_body` displays daily heat/gas energy ratios and a seven-day
ratio of summed energies (not an average of percentages). It reuses
`gas_usage.json` and all four `cycle_N_heat_delivery.json` streams. Missing
cycle totals or gas data are unknown, never zero; zero gas gives no ratio.
Each day's totals are taken at the latest common cycle observation horizon,
with heat observations aligned to within the existing three-minute gap limit.
The gas denominator uses the last cumulative pulse volume at/before that horizon.

The editable constant `BOILER_GAS_HEATING_VALUE_MJ_M3` in `boiler_kpi_plots.js`
is 34 MJ/m³ = 9.444… kWh/m³, the typical lower heating value published by
[MVM Hálózat](https://www.mvmhalozat.hu/gaz/oldalak/2376), retrieved 2026-10-21.
The ratio is not capped at 100%. No device source, control or Firebase changes.

## Ordinary plot dates

All main plot foundations share the corner date controls, not only selectors.
Historical room plots use the archived requested temperatures and valve data,
without today's live valve append, schedule forecast, overrides or rolling
temperature baseline. Historical open circulation periods end at midnight.
Empty days keep the date controls and show a no-data message.
