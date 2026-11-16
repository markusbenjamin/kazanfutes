# Boiler analytics

Alt+click the boiler, or use `analitika` on touch. The separate heading is
`kazán analitika`. The selector contains `hatásfok` and
`előremenő / visszatérő fázissík`; the old `napi pontok` view is retired.

`hatásfok` shows borderless daily bars over thirty calendar days ending on the
selected date. Daily efficiency is summed delivered circuit heat divided by gas
energy, using the existing 34 MJ/m³ conversion and common measurement cutoff.
The window statistic divides summed energies, rather than averaging daily
percentages. Missing circuit energy and zero/missing gas remain unavailable;
valid zeros and ratios above 100% are retained. Four daily fetches run in
parallel through the normal GitHub cache, with stale-view cancellation.

The phase-plane view has an `átlag`, `összes`, and individual-circuit selector.
X is return temperature; Y is supply temperature. Both scatter and the
continuous chronological trajectory use observations where the associated
pump's measured electrical power is positive. Power is held between actual
change-log entries; synthetic plot changepoints, flow and on/off commands do
not determine activity. Average-view observations require at least one member
pump drawing power. The trajectory uses five-minute-sigma Gaussian smoothing
in time (±15-minute support), then curved interpolation. Scatter is unsmoothed.
Dates, selected views and canonical circuit colours are retained when switching.
