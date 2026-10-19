"""Read the dashboard's external temperature exclusively from raw WS90 data."""

from datetime import datetime
import math

STAMP_FORMAT = '%Y-%m-%d-%H-%M-%S'
WS90_MAX_AGE_SECONDS = 300


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
