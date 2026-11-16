# Plot history at midnight

Continuous time plots request up to four hours of the preceding day's published
measurements through the normal GitHub loader/cache. These remain display-only
context at negative fractional hours; source files and cached rows are unchanged.
Smoothing runs before this context is trimmed at midnight. The plotted day and
its endpoint labels remain on the selected date. Recent preceding room readings
can seed midnight during replay; stale readings cannot create a curve.

During replay, moving averages use trailing windows. Sparse-room resampling
holds the preceding measurement rather than interpolating towards a later one.
The replay cutoff is applied before either operation, so future readings cannot
move the already observed trajectory. Outside replay, centred display smoothing
is retained, with preceding-day context warming its midnight edge.

Daily energy/gas totals, demand and thermal-power bars, daily analytics,
rainfall accumulation, wind-direction histograms and learned weekday occupancy
profiles retain their calendar boundaries. Their daily statistics do not inherit
yesterday's values. No new logging, formatter stream or Pi deployment is needed.
