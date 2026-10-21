# Room metric selector

Ordinary room hover and ordinary click keep the existing heating/temperature
chart. Ctrl+click a room to pin a separate chart with plain-text choices:
`hőm.`, `páratart.`, `CO₂`, `lux`, `jelenl.`. Selecting a choice keeps
the chart pinned. An outside click unlocks it. The last choice is remembered
per room for the current page only; it never changes ordinary hover.

Temperature and humidity use the existing `room_N_measurements.json` stream
(°C and %). Temperature reuses the ordinary room chart's exact
`prepareRoomTemperatureForDisplay` series, moving-average window 10, and basis
curve. There is no separate temperature formatter or `control_temp` field, no
new sensor selection, and no averaging of extra Nous/Aqara temperature units.

All five curves use thickness 2. Other metrics use shape-preserving monotone
interpolation; temperature keeps the ordinary room chart's smoothing.
Temperature matches the ordinary room chart's exact bright
red; humidity is light blue; CO₂ is dark poison green; lux is golden yellow.
Unknown values and long gaps
break curves; missing data never become zero or vacant.

The `jelenl.` black curve plots `occupancy_average` as a percentage, read from
the scheduler's `config/scheduling/local_scheduling_files/occupancy.json` for
the plotted day's weekday. Hourly averages are centred in their hour bins.
No thresholding, weekly-plan blending, overrides, or fallback are applied.
Unknown learned averages stay unknown; if none exist, the chart shows
`Átlagos jelenlét nem elérhető.`
The scheduler and set-temperature calculation are not changed.

Light-gray background rectangles mark today's evaluated occupied periods
from heating-control logs (`occupancy` 0/1/null), independently of the learned
curve. Unknown states stop a rectangle, and missing observations are held for
at most 15 minutes. Rectangles do not extend into the future.

## Editable sensor assignments

`config/nous_and_aqara_mapping.json` is reread by the data formatter on every
run. Room keys are the existing numeric room IDs, not sensor numbers. For
example, room 1 uses `"co2": ["Nous6"]` and
`"lux": ["Aqara3", "Aqara4"]`. Multiple assigned units are averaged over
valid measurements. An invalid/missing member is excluded, not replaced with
zero; no valid members produce null. Duplicate sensor names count only once.
An empty list explicitly means no assigned sensor.

The initial assignments were joined from the owner's
`dev/db/sept_package/mappings.csv` and `locations.csv` on `location_id`, using
`legacy_room_number`. The formatter does not require or modify those
development database files. Database location labels can differ from legacy
dashboard labels; this feature does not rename or relocate dashboard rooms.
Unassigned rooms remain unassigned. `system/setup.json` is untouched.

The extra stream consumes the existing Aqara/Nous log plus heating-control
execution log. No device is polled, commissioned, reconfigured, or operated by
this feature. Normal formatter/uploader timers publish it through GitHub.
