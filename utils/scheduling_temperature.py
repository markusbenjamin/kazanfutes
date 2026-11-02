"""Choose the scheduler's outdoor temperature without polling the station."""

from datetime import datetime
import math
from pathlib import Path

from utils.device_watchdog import last_ndjson_record
from utils.external_temperature_formatter import (
    STAMP_FORMAT, WS90_MAX_AGE_SECONDS, ws90_external_temperature,
)


def get_scheduling_external_temperature(project_root, fallback, *, now=None):
    """Prefer a WS90 observation at most five minutes old, then call fallback.

    Check sensor time against both logger time and the current local time: a
    stopped logger must not leave an old, apparently fresh observation in use.
    If neither source supplies a valid temperature, let scheduling fail rather
    than substitute a made-up zero.
    """
    path = Path(project_root) / 'data/logs/weather_station/weather_station.json'
    entry = last_ndjson_record(str(path))
    temperature = ws90_external_temperature(entry)
    if temperature is not None:
        observed = datetime.strptime(entry['last_updated'], STAMP_FORMAT).astimezone()
        current = (now or datetime.now()).astimezone()
        age = (current - observed).total_seconds()
        if -30 <= age <= WS90_MAX_AGE_SECONDS:
            return temperature, 'WS90'

    temperature = fallback()
    if (isinstance(temperature, bool) or not isinstance(temperature, (int, float))
            or not math.isfinite(temperature)):
        raise ValueError('Open-Meteo returned no finite outdoor temperature')
    return temperature, 'Open-Meteo'
