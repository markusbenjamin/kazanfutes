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
It uses borderless orange bars, one per logged instantaneous kW value, with
HH:MM/value tooltips and the latest valid value label. It shares the detailed
cycle-power bar renderer: widths follow nearby timestamps, capped at three
minutes (one minute for an isolated reading). No averaging or smoothing.
Unknown values remain gaps, and real zero demand remains zero. No alternative
demand calculation is performed by the dashboard.

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
controller, device mapping or SVG changes are required.
