# Live chart endpoints

`live_plot_data.js` overlays fresh Firebase readings on today's main chart
payload without editing the cached/archive arrays. The most recent raw payload
is retained so the existing five-second Firebase poll can redraw its endpoint
without another GitHub download. Date/view changes invalidate that reuse.

Numbers must be finite actual numbers, not null/string/boolean conversions.
Snapshot timestamps must parse, be within the source's freshness limit and no
more than 30 seconds in the future. A live endpoint must follow the archived
series; a newer logged observation is never overwritten by an older snapshot.

- Room temperature/humidity: controller snapshot at most 180 seconds old, plus
  the actual sensor timestamp at most two hours old (the existing room freshness
  policy). Temperature uses the same control `measured_temps` value in ordinary,
  overview and detailed charts. Room valve opening remains the mean of known
  mapped TRVs, using the filtered radiator-valve snapshot where available.
- Radiator probes: timestamped `radiator_probes`, at most 300 seconds old;
  TRVs: filtered `radiator_valves`, at most 600 seconds old.
- Heating water, flow and thermal power: heatmeter snapshot at most 180 seconds
  old. Positive power additionally needs flow >0.005 m³/h, supply > return,
  and agreement with 1.163*flow*(supply-return), within max(2 kW, 30%). This is
  the same physical cross-check used by the formatter. Zero is valid.
- Pump/boiler-plug electrical power: own timestamp at most 180 seconds old;
  boiler plugs must also report reachable. Change-only pump logs can become too
  old to extend safely; no timestamp is silently refreshed by the frontend.
- Weather/outdoor temperature: validated WS90 snapshot, actual sensor timestamp
  at most 300 seconds old. Wind histograms and rain accumulation/rates are not
  given synthetic observations.

Historical plots, phase/statistical analytics, gas rates without a source
timestamp, demand calculations and cumulative energy sums remain log-derived.
Unknown/unpublished room CO₂/lux and learned occupancy are not guessed.

The heatmeter logger now publishes `return_temp` and corroborated `power` beside
its existing supply/flow fields. The weather logger publishes a validated
`weather_station` snapshot beside the existing `external_temp`. These service
changes need the normal GitHub-to-Pi deployment before those additional live
channels become available; old snapshots remain safe (unverifiable positive
power is skipped). No hardware setup, commands or SVG mappings are changed.
