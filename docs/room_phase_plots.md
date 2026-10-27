# Room phase-plane experiment

Alt+click a room, then choose `fázissík` beside `összegzés`. Touch uses the same
selector under `analitika`. The old summary, main/cycle daily error plots and
Ctrl+click sensor selector remain available. View selection is remembered per
room and dates are preserved when switching.

Alt+click the main infobox for all controlled rooms, or a cycle infobox for only
the rooms assigned to that cycle in the existing setup. Their analytics selector
switches between `napi hiba` and `fázissík`; touch uses `analitika` as before.
Selection is remembered separately for each room, each cycle and the main box.
The aggregate chart overlays separate room trajectories on shared axes (never
averaging rooms), with the same canonical room colours as the existing dashboard
and a compact coloured legend. Only the selected rooms' per-room files are loaded;
rooms without valid points are omitted, not plotted at zero. Marker tooltips in
aggregate views include the room name as well as HH:MM.

Y is the actual thermostatic room temperature minus logged `set_temps_interp`,
in K, without demand gating: overheating is positive and above zero. The
published `error_k` keeps its original set-minus-measured convention and is
negated only for this view. Sentinel/timed targets (-1, 0, 1) are not Celsius
targets. X is `max(effective_radiator_temp - room_temp, 0)`, in K, with no
reference offset. Zero means no radiator temperature excess above the room;
hotter radiators sit farther right. The view adds the payload's `offset_k` back
to its encoded `intensity_k`, so existing backfilled files need no regeneration.
Raw published values remain unchanged. The X axis starts at zero.
There is no watts claim or radiator-size normalization.

The raw-input formatter is `utils/room_phase_formatter.py`, invoked by the
normal `services/data_formatter.py` service. `--room-phase-days N` regenerates
only this stream for N calendar days including today, with no device polling,
control writes or broad upload trigger. The previous day warms the model and
causal fitting; day boundaries do not initialize every room cold.

Each day has a small `room_phase_points.json` coverage/model index and one
`room_N_phase_points.json` payload per controlled room. The chart fetches only
its room. Every control snapshot yields a point or an explicit unavailable
record, not an invented evenly sampled measurement.

Measured radiator temperature is the fixed-membership average of mapped unit
probes from `system/radiator_mapping.json`. No SVG dependency or individual
TRV/probe association is inferred. A missing mapped probe switches the whole
room to its thermal model rather than silently removing the coldest member.

The room-level model approaches a valve/circulation/water-dependent equilibrium
exponentially, with separate heating/cooling time constants. Water temperature
is the supply/return mean. Pump-off or a closed valve moves equilibrium to room
temperature, but stored radiator heat decays gradually. No-TRV rooms use 100%
opening. Mapped TRVs require all configured valves, bounded log age and device
last-seen freshness. Missing evidence is never a fully open valve.

Initial fallback parameters are heat tau 600 s, cool tau 1200 s, gain 1 and
valve exponent 0.7. Small causal candidate fits require at least 60 heating /
30 cooling intervals, at least 10 / 5 K accumulated observed movement and
one-step RMSE <= 2 K. Flat samples alone cannot calibrate. Unfitted parts may
use median parameters from already-calibrated rooms. Points explicitly report
measured/estimated/unavailable and fitted/partly-fitted/shared/default quality;
defaults and pooled estimates are not claimed as calibrated for that room.

Room sensor age is limited to one hour; probe/water/control gaps to three
minutes; valve device last-seen age to one hour. Probe-seeded estimates retain
their state. Unseeded models require five maximum time constants of continuous
input before being shown. Long model gaps reset warm-up. No future sample
interpolation, whole-day look-ahead fit or endless stale-data propagation.

A canonical-room-coloured Catmull–Rom trajectory preserves time order and loops, never sorting
by either axis. Before interpolation, both coordinates use a centered 30-minute
rolling mean (valid observations within ±15 minutes of each logged timestamp).
The actual first and latest positions anchor the ends. This is display-only:
raw payloads do not change. All valid observations are joined, including across unknown
records, source changes and long gaps; these connecting curves are visual
interpolation, not additional measurements. There are no intermediate markers.
Each trajectory starts with a large black arrowhead following its forward tangent
and ends with a large room-coloured dot plus the red current-direction arrow.
Start/end tooltips show actual HH:MM (and the room name in aggregate views).
A fully stationary trajectory has a black starting dot instead of an invented
direction. Curves have the main all-room plot's 1.25-unit base thickness (2.5 on
the explicit mobile layout). Hover or keyboard focus doubles line width, raises
the whole room trajectory/markers above the others, shows a translucent white
halo, and enlarges the start/end markers; leaving restores normal styling.
Both axes retain a visible zero
reference; Y fits the observed deviations rather than reserving an equally
large empty opposite side. Backend availability and freshness rules are unchanged.
