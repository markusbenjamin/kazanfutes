"""Read the dashboard's external temperature exclusively from raw WS90 data."""

from datetime import datetime
import math

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
WS90_MAX_AGE_SECONDS = 300
WS90_PLOT_FIELDS = {
    'temperature_c': (None, None), 'humidity_pct': (0, 100), 'dewpoint_c': (None, None),
    'wind_speed_m_s': (0, None), 'gust_speed_m_s': (0, None), 'wind_direction_deg': (0, 360),
    'illuminance_lux': (0, None), 'uv_index': (0, None), 'precipitation_mm': (0, None),
    'pressure_hpa': (0, None)
}


def _observed_at(entry):
    try:
        logged = datetime.strptime(entry.get('timestamp'), STAMP_FORMAT)
        observed = datetime.strptime(entry.get('last_updated'), STAMP_FORMAT)
    except (TypeError, ValueError):
        return None
    age = (logged - observed).total_seconds()
    return observed if -30 <= age <= WS90_MAX_AGE_SECONDS else None


def ws90_external_temperature(entry):
    """Return a finite, fresh WS90 temperature, including zero and negatives."""
    if not isinstance(entry, dict) or _observed_at(entry) is None:
        return None
    state = entry.get('state')
    if not isinstance(state, dict):
        return None
    value = state.get('temperature_c')
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value if math.isfinite(value) else None


def format_ws90_external_temperatures(entries, daystamp):
    """Keep the existing timestamp/external_temp output, using sensor timestamps."""
    day = datetime.strptime(daystamp, '%Y-%m-%d').date()
    rows = {}
    for entry in entries:
        temperature = ws90_external_temperature(entry)
        if temperature is None:
            continue
        observed = _observed_at(entry)
        if observed.date() != day:
            continue
        stamp = observed.strftime(STAMP_FORMAT)
        rows[stamp] = {'timestamp': stamp, 'external_temp': temperature}
    return [rows[stamp] for stamp in sorted(rows)]


def format_ws90_weather(entries, daystamp):
    """Publish existing WS90 observations only; never poll or infer new values."""
    day = datetime.strptime(daystamp, '%Y-%m-%d').date()
    rows = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        observed = _observed_at(entry)
        state = entry.get('state')
        if observed is None or observed.date() != day or not isinstance(state, dict):
            continue
        stamp = observed.strftime(STAMP_FORMAT)
        row = {'timestamp': stamp}
        for field, (minimum, maximum) in WS90_PLOT_FIELDS.items():
            value = state.get(field)
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
            valid = valid and (minimum is None or value >= minimum) and (maximum is None or value <= maximum)
            row[field] = value if valid else None
        rain = state.get('rain_status')
        row['rain_status'] = int(rain) if isinstance(rain, bool) else rain if type(rain) in (int, float) and rain in (0, 1) else None
        rows[stamp] = row
    return [rows[stamp] for stamp in sorted(rows)]
