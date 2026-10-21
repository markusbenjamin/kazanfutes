# Cycle piping plot trial

Hover a cycle's piping or numbered dial for the simple **fűtőteljesítmény**
curve. Ctrl+click either to pin the detailed selector with plain-text choices:
**fűtővíz hőm.**, **fűtőtelj.**, **átfolyás**, **szivattyú telj.** The active
choice is underlined: temperature red, thermal power orange, flow blue,
electrical pump power black. Ordinary click keeps its usual pin/unpin action.
Selecting a metric keeps the chart pinned; the existing outside-click unlock
still applies. Detailed choices are remembered per cycle for the current page
session only, shared by its dial and piping. They never change ordinary hover.
Detailed selectors also show the date with previous/next-day controls. The
metric and cycle stay selected while navigating; future days are disabled.
The ordinary hover title is `<n>. kör mai fűtőteljesítménye`.

All four views retain the selected cycle's pump-on shading and thin curves.
Period rectangles show their fill only, with no borders.
Pump power joins known observations even across time gaps; explicit unknown
values still break it. Its black curve is rectangular (step-after), with no
smoothing. Heatmeter curves retain their missing-interval breaks.
Metric selection replaces the setting object so a late response for the old
metric cannot overwrite the newly selected chart. Heading clicks/keyboard
activation do not bubble into the dashboard's outside-click unlock handler.

## Formatted data

- Temperature: existing `cycle_N_water_temps.json`, `water_temp` in °C.
- Thermal power and flow: new `cycle_N_heat_delivery.json`, `power_kw` in kW
  and `flow_m3h` in m³/h; also `energy_kwh` and `energy_partial` for the dials.
- Electrical pump power: existing `pumps_power.json`, only `pump_N_power` in W.
- Overlay: existing `heating_state.json`, selected cycle only.

The normal Pi `data_formatter` run ingests raw
`data/logs/heat_delivery/heatmeters_state.json`, using the authoritative meter
mapping from `config/heating_monitor.json`. It exports four daily heat/flow
files; the existing data uploader publishes them normally. There is no new
hardware polling, Firebase dependency, relay action, or collector change.

Thermal power is each heatmeter's instantaneous `power_w`, converted to kW by
dividing by 1000. It is not accumulated daily energy, net energy delivery, or
the boiler plug's electrical power. The raw `energy_kwh` counter is not used.

Flow is read directly from `volume_flow_m3h`. Valid zero is retained. Missing
values are null, never zero; rendered curves break across them and long gaps.

## Daily energy dials

The four numbered boxes show daily delivered thermal energy in kWh instead
of electrical pump watts. Energy is a trapezoidal integral of logged thermal
`power_w` over observed intervals no longer than three minutes. Missing or
long intervals are not filled. Late starts or missing coverage set
`energy_partial`; absent power stays unknown, not zero. Totals reset with each
day's formatted file. Dials show whole kWh without an approximation prefix or
tooltip.
Values and right-aligned kWh units share a baseline and scale with the dial
height. The units are larger for readability, with measured space reserved
before fitting long totals so the value and unit cannot overlap.
The raw energy counter is deliberately ignored because of observed unit/jump
inconsistencies. Heating-power plots remain instantaneous kW, not kWh.
