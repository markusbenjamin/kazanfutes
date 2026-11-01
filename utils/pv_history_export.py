"""Read the notebook's 30-word inverter history exports without evaluating it.

The CSV files contain one unsigned 32-bit integer per row, a three-word header,
and 4,320 records. Voltage/current fields occupy interleaved 16-bit registers.
Stored Unix-looking timestamps encode LOCAL wall time, verified against the
logger's March 2026 overlap. Ambiguous DST wall times are rejected.

This adapter does not reconstruct a missing channel from total production.
DC total is unavailable here; it is not fabricated from the same inputs that
would subsequently be checked against it. Weather is also unavailable.
"""

from collections import Counter
import csv
from datetime import date, datetime, timezone
import math
from pathlib import Path
import re

if __package__:
    from .pv_performance import Sample, day_epoch, number, solar_position
    from .pv_performance_io import parse_timestamp
else:
    from pv_performance import Sample, day_epoch, number, solar_position
    from pv_performance_io import parse_timestamp


MAGIC = 858800461
FILE_PATTERN = re.compile(r"his_inv_extraction_(\d{14})(?:\d{3})?\.csv$")


def decode_record(words, policy):
    if len(words) != 30 or any(type(word) is not int or not 0 <= word <= 0xffffffff for word in words):
        raise ValueError("Expected 30 unsigned 32-bit words")
    if words[2] & 0xffff != 8:
        raise ValueError("Unsupported input count/history register layout")
    try:
        wall = datetime.fromtimestamp(words[0], timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError):
        return None
    observed = parse_timestamp(wall.isoformat(), policy)
    if observed is None:
        return None
    epoch = int(math.floor((observed + 150) / 300) * 300)
    registers = [half for word in words[2:] for half in (word & 0xffff, word >> 16)]
    voltages = tuple(number(value / 10, 0, 1500) for value in registers[1:9])
    currents = tuple(number(value / 100, 0, 100) for value in registers[9:17])
    ac_watts = (words[16] >> 16) | ((words[17] & 0xffff) << 16)
    ac_kw = number(ac_watts / 1000, 0, 100)
    azimuth, elevation, solar_hour = solar_position(epoch, policy)
    from zoneinfo import ZoneInfo
    day = datetime.fromtimestamp(epoch, ZoneInfo(policy.timezone)).date().isoformat()
    return Sample(epoch, day, azimuth, elevation, solar_hour,
                  currents, voltages, ac_kw, None, source_kind="historical_export")


def load_history_exports(directory, start, end, policy, *, available_before=None):
    """Use only exports created before the cutoff, then filter observation dates.

    Default availability cutoff is the end-exclusive reference boundary. Thus a
    2025 baseline cannot consume an export acquired during/after the 2026 event.
    Overlap is deduplicated by source bucket, preferring the earliest export.
    """
    if start >= end:
        raise ValueError("History end must follow start")
    lower, upper = day_epoch(start, policy), day_epoch(end, policy)
    cutoff = date.fromisoformat(available_before or end)
    quality, samples = Counter(), {}
    for path in sorted(Path(directory).glob("his_inv_extraction_*.csv")):
        match = FILE_PATTERN.fullmatch(path.name)
        if match is None:
            continue
        exported = datetime.strptime(match[1], "%Y%m%d%H%M%S")
        if exported.date() >= cutoff:
            quality["exports_after_availability_cutoff"] += 1
            continue
        with path.open(encoding="utf-8-sig", newline="") as handle:
            values = []
            for row in csv.reader(handle):
                if not row:
                    continue
                if len(row) != 1:
                    raise ValueError(f"Expected one integer column in {path.name}")
                values.append(int(row[0]))
        if values[:3] != [MAGIC, 4320, 4320] or len(values) != 3 + 4320 * 30:
            raise ValueError(f"Unsupported or incomplete history export: {path.name}")
        quality["exports_read"] += 1
        for offset in range(3, len(values), 30):
            quality["export_records"] += 1
            sample = decode_record(values[offset:offset + 30], policy)
            if sample is None:
                quality["invalid_or_ambiguous_timestamp"] += 1
                continue
            if not lower <= sample.epoch < upper:
                continue
            if sample.day > exported.date().isoformat():
                quality["observation_after_export"] += 1
                continue
            if sample.epoch in samples:
                quality["duplicate_buckets"] += 1
                continue
            samples[sample.epoch] = sample
    if not quality["exports_read"]:
        raise ValueError("No history exports available before the requested cutoff")
    quality["unique_samples"] = len(samples)
    return [samples[t] for t in sorted(samples)], dict(quality)
