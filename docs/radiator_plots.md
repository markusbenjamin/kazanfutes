# Radiator views

`system/radiator_mapping.json` owns probe-to-unit assignments, not drawing
groups or TRV identities. SVG targets use `<location_id>_radiator_<n>` IDs.
`data-location-id` can override the unit inferred from that ID. Optional
`data-display-label` overrides only the plot's display name (Diós Edit for
`merce_targyalo`), without changing physical location or probe ownership.
Optional
`data-probes` is a JSON array of exact `device/probe` source strings; omission
uses the unit's probes, while `[]` explicitly means no probe association.
`data-trvs` is an array of raw thermostat IDs. These frontend associations are
provisional and do not change heating control or the physical unit mapping.

Gólyafészek target 1 uses probes 100/101 and TRV 71; target 2 uses probes
102/103 and TRV 75. Oktopusz target 1 uses its known probe and TRV 77; target 2
has only TRV 79. Single-target units use their mapped probes. Mérce/GÉPműhely
use the raw device identities 57/63 respectively, without changing the existing
room-plot averages or system/setup.json. Unmapped WC/szitamosó targets and
other targets without actual probe/TRV readings do not intercept pointer events.
The decommissioned kerámia radiator drawing is not recreated.

Piping and radiators share a clamped blue-to-red 22–50 °C scale: at or below
22 °C is blue, at or above 50 °C is red. Room colours retain their separate
scale. Probe-associated targets use
the mean of valid associated probes from Firebase. Missing or stale probe
temperatures first fall back to the mean of known associated TRV opening
percentages (blue at 0%, red at 100%). Only when neither temperature nor valve
readings are available do targets use the cycle's piping colour: pump off is
blue; pump on uses that cycle's fresh supply-water
temperature. If the supply temperature is unavailable too, a running cycle
falls back to red. Radiators and piping never use grey for missing readings.

Hover displays only known °C and percent values, with no name, and shows the
mean probe-temperature history. A valve-only target shows opening instead.
Ctrl+click pins a selector for mean temperature, individual probes, and
individual TRV openings. Click-away releases it. Date navigation is shared
with other plots. Valve curves stay rectangular; missing observations are
never turned into zero. Each temperature probe retains its own last valid
reading for at most five minutes through missing samples. An average always
requires all associated probes within that limit; otherwise the curve has a
gap rather than switching to a different subset of probes. Nothing is carried
across days. Individual valve curves still break on explicitly missing data.

`utils/radiator_formatter.py` prepares `radiator_temps.json` and
`radiator_valves.json` per day. Probe sources remain separate, including the
unassigned probe. Valve readings use actual raw percent values and require
last-seen freshness within one hour. The existing room-valve formatter is
unchanged. The radiator logger publishes `system/state/radiator_probes` with
collection timestamp and raw device/probe nesting; the formatter publishes
`system/state/radiator_valves`. Firebase snapshots are primary, with bounded
formatted-data fallback before those new publishers are deployed. Live probe
snapshots expire at five minutes, valves at ten minutes, fallback at twenty.
Cycle heatmeter state expires at ten minutes. There is no hardware operation
or controller configuration change in this feature.

Today's detailed room presence view also includes a faint dotted pink current-
time line; archived days do not show it.
