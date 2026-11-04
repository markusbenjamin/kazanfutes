# Boiler details

Ctrl+click the boiler body (or select `részletes` on touch) opens a daily
selector with `instant hőigény` and `átlagos fűtővíz hőm.`. Ordinary hover still shows cycle
switching; Alt+click / `analitika` still shows the energy KPI. Metric selection
is remembered and date navigation preserves it.
Both views use the gas plot's pale-red cycle-on background, including stacked
shading where multiple cycles are on. The same period extractor is used;
current open periods end at now, historical ones at midnight. Shading is drawn
once behind the curves and spans the current plot's full vertical range.

Demand reads `demand_kw` directly from the Pi's `heating_demand.json`.
It uses borderless stacked bars from the same row's `cycle_demand_kw`, with a
compact four-cycle colour legend and HH:MM/component/net-demand tooltips.
Positive contributions stack above zero and negative contributions below it.
A black tick marks the unchanged `demand_kw = max(0, sum(cycle_demand_kw))`, and
the latest net value is labelled. Demand is not measured delivered heat.
All four components must be finite and reconcile to the logged total; old files
without a breakdown (or inconsistent breakdowns) retain an orange total bar.
An unavailable total remains a gap, even if some components are known.
Display bars are time-weighted ten-minute means, 90% of the bin width, without
borders. Holds stop at unknown readings or after three minutes; empty bins stay
empty. The final isolated observation contributes at most one minute, and today's
last bin stops at now. Each raw breakdown is validated before averaging. The net
is averaged separately because clipping and averaging do not commute. Incomplete
breakdown coverage keeps an orange total bar. No daily energy totals or backend
demand calculations are changed.

The temperature view averages the existing `cycle_N_water_temps.json` supply
and return series across circuits with at least one pump-on command in the
selected day's `heating_state.json` (`cycle_states[N] === 1`). This is a daily
membership rule: those circuits contribute throughout the day, including when
their pumps are off. It does not use today's switch setting or the demand
file's instantaneous flow-based `active_cycles`. Historical dates use their
own archived commands. Missing command history is unknown, not an idle day.

The mean is arithmetic, not flow-weighted. Asynchronous circuit observations
are held causally for at most three minutes. All enabled circuits must have a
valid reading for a channel; no partial means or zero-filled missing values.
Supply and return can independently be unavailable. Supply is red, return
deep blue, both with curve tooltips and final-value markers. No backend,
controller, device mapping or SVG changes are required. Fresh, timestamped live
heatmeter endpoints are applied before these means are calculated; historical
days still use archived observations only.

Each circuit's supply/return value must be a finite number within 0–100 °C
before averaging. A corrupt value makes only that channel unknown, not a
partial mean. This also protects historical dates: an erroneous 60,044,000 °C
return reading otherwise caused millions of axis ticks and froze the entire
page. No logged/cached values are changed; valid readings resume afterward.
