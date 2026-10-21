# Outdoor weather selector

Ordinary hover over the external thermometer keeps the outdoor temperature
plot. Ctrl+click opens the pinned WS90 selector. Its date line navigates daily
files, retaining the chosen metric; future days are disabled.

The formatter reads the existing weather-station raw log and writes
`weather_station.json` alongside each day's other formatted files. It uses
the sensor observation timestamp, rejects stale and invalid observations,
preserves valid zero, and leaves missing measurements unknown. The existing
outdoor-temperature formatter and Firebase source are unchanged.

Available metrics are temperature, humidity, dew point, wind speed, gust
speed, wind direction, illuminance, UV index, cumulative precipitation,
rain status and pressure. Battery measurements are deliberately excluded.
The light plot displays kilolux (`klux`); its stored lux measurements remain
unchanged.
Wind speed and gust curves use a five-observation moving average and basis
interpolation within each valid segment; missing intervals still break them.
Precipitation is the device's cumulative millimetre counter, not a calculated
daily rainfall total.

Wind direction uses a 16-sector circular histogram, horizontally centred in
the plot area and nudged slightly down to balance the negative space below
the selector. Sector area represents the
number of observations, with west at the top to match the building diagram
(north right, east bottom, south left). Calm observations and unknown
wind speed/direction are excluded; an empty day keeps the compass and shows
that no direction data are available.
