# Outdoor weather selector

Ordinary hover over the external thermometer keeps the outdoor temperature
plot. Ctrl+click opens the pinned WS90 selector. Corner date arrows navigate
daily files, retaining the chosen metric; future days are disabled. Past dates
sit beside `rögzítve` above the frame; today's date is omitted.

The formatter reads the existing weather-station raw log and writes
`weather_station.json` alongside each day's other formatted files. It uses
the sensor observation timestamp, rejects stale and invalid observations,
preserves valid zero, and leaves missing measurements unknown. The existing
outdoor-temperature formatter and Firebase source are unchanged.

Available metrics are temperature, humidity, dew point, wind speed, gust
speed, wind direction, illuminance, UV index, daily precipitation,
and pressure. Battery measurements are deliberately excluded.
The temperature and dew-point experiment uses one `hőm./harmatp.` selector,
overlaying both curves on a shared °C axis. The original blue temperature and
teal dew-point colours are retained; curve hovers identify `hőmérséklet` and
`harmatpont`. Each curve independently respects missing-data gaps. The selector
uses three columns and three rows, without a separate dew-point option.
`esőjel` has no separate selector: it is shown as very faint (5% opacity),
borderless background periods on the precipitation plot. Unknown
observations break a period; readings are held for at most 15 minutes, capped
at now for today or midnight for archived days. It uses the same WS90 stream.
The light plot displays kilolux (`klux`); its stored lux measurements remain
unchanged.
Wind speed and gust curves use a five-observation moving average and basis
interpolation within each valid segment; missing intervals still break them.
The precipitation plot subtracts the selected day's first valid cumulative
millimetre reading, so `csapadék össz.` starts at zero each day. Missing readings
remain unknown, and the stored device counter is unchanged.
For the local rainfall-rate experiment, `WEATHER_RAIN_RATE_PREVIEW` switches that
same selector to `csapadék` in mm/h: finite-difference rainfall rates smoothed
with a centred Gaussian kernel (5-minute standard deviation, truncated at
±15 minutes). Weights integrate the Gaussian over each measured interval,
so irregular sample spacing does not bias the result. Edge weights are
renormalized over the available observations. Missing observations, counter
resets and gaps longer than 15 minutes split the smoothing into separate segments.
Monotone interpolation rounds the joins without overshoot. Stored data
are unchanged. Set the flag to `false` to restore the daily total described above.

Wind direction uses a 16-sector circular histogram, horizontally centred in
the full dotted plot frame using symmetric horizontal margins in this axis-free
view. Its size and the other weather plots' axis margins are unchanged. It is
nudged slightly down to balance the negative space below
the selector. Sector area represents the
number of observations, with geographic azimuth 265° at the top to match the
building diagram. Both sectors and compass labels use that rotation: west
(270°) is 5° clockwise of up. Geographic data and bin assignments are unchanged.
Calm observations and unknown
wind speed/direction are excluded; an empty day keeps the compass and shows
that no direction data are available.
