# Boiler-plug dashboard hooks

The dashboard is prepared for two future power displays. No SVG geometry is
created or modified by this feature, and no new hardware polling or relay control
is introduced.

| Plug source | Future SVG display ID | Optional border ID | Daily power file |
| --- | --- | --- | --- |
| `boiler_1_plug` | `boiler1_marker` | `boiler1_marker_border` | `boiler_1_plug_power.json` |
| `boiler_2_plug` | `boiler2_marker` | `boiler2_marker_border` | `boiler_2_plug_power.json` |

Copy the dimensions/structure of a pump-power marker and use the IDs above.
Generated text is click-through. Each display shows its own latest instantaneous
electrical power in watts and selects only its own history when hovered. The
existing click-to-lock plot behavior also applies.

The existing `boiler_power_monitor` observation is published to
`system/state/boiler_plugs/<plug_source>` on Firebase. It contains `timestamp`,
`reachable`, and `power_w`. Missing, invalid, unreachable, or older-than-three-
minute readings display `— W`; a confirmed zero-watt reading displays `0 W`.
There is no historical-data fallback for the instantaneous value.

`data_formatter` reads the existing `data/logs/boilers_power/boiler_plugs.json`
NDJSON and emits both daily power files under `data/formatted/YYYY-MM-DD/`.
Each record contains `timestamp` and `power_w`. Unavailable samples are retained
as JSON null, not converted into zero; the curve breaks at these samples and at
gaps longer than three minutes. An absent/uncommissioned source produces an
empty array, which the plot handles normally.

The shared daily `boiler_commands.json` overlay is derived from executed
`device == "boiler"` entries in `data/heating_control/commands_archive.json`,
using `execution_timestamp` and `setting`. It is not inferred from pump demand,
power consumption, plug output, or unexecuted/future commands. Both plugs use
the existing shared boiler command. The last known state carries across
midnight; missing command history is left unknown rather than assumed OFF.
Shaded intervals indicate an ON command. This does not imply that either
uncommissioned plug is already supplying a boiler.

With no matching SVG IDs, initialization and live updates are no-ops. No visual
placeholder is added, and no plot request is made until an element is activated.
