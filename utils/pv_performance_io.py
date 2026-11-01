"""Explicit file I/O for PV replay/shadow mode; importing this module has no I/O."""

from collections import Counter, defaultdict
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import json
import math
import os
from pathlib import Path
from statistics import median
import tempfile
from zoneinfo import ZoneInfo

if __package__:
    from .pv_performance import Sample, day_epoch, number, solar_position
else:
    from pv_performance import Sample, day_epoch, number, solar_position


def parse_timestamp(value, policy):
    """Project timestamps are Budapest local time, independent of host timezone.

    Reject ambiguous/nonexistent offset-less DST times rather than inventing an
    ordering. Modern source timestamps carry offsets and do not have this issue.
    """
    if not isinstance(value, str):
        return None
    try:
        parsed = (datetime.strptime(value, "%Y-%m-%d-%H-%M-%S") if len(value) == 19 and value[10] == "-"
                  else datetime.fromisoformat(value.replace("Z", "+00:00")))
        if len(value) < 19:
            return None
        if parsed.tzinfo is None:
            zone = ZoneInfo(policy.timezone)
            early, late = parsed.replace(tzinfo=zone, fold=0), parsed.replace(tzinfo=zone, fold=1)
            if early.utcoffset() != late.utcoffset():
                return None
            if datetime.fromtimestamp(early.timestamp(), zone).replace(tzinfo=None) != parsed:
                return None
            parsed = early
        return parsed.timestamp()
    except (ValueError, OverflowError, OSError):
        return None


def log_paths(directory, basename, start, end):
    """Only the active file and dated rotations in the requested interval."""
    paths = []
    for path in Path(directory).glob(basename + "*"):
        if path.name == basename:
            paths.append(path)
        elif path.name.startswith(basename + "."):
            suffix = path.name[len(basename) + 1:]
            try:
                day = date.fromisoformat(suffix).isoformat()
            except ValueError:
                continue
            if start <= day <= end:
                paths.append(path)
    return sorted(paths)


def records(paths, quality, prefix):
    for path in paths:
        quality[prefix + "_files"] += 1
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                quality[prefix + "_rows"] += 1
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError("Not an object")
                except ValueError:
                    quality[prefix + "_malformed_rows"] += 1
                    continue
                yield row


def load_samples(log_root, start, end, policy, *, allow_legacy=False):
    """Read requested observations plus one context day; never write log files.

    Earliest observed usable version wins each source bucket. A future correction
    cannot rewrite past evidence. Observations received after the end boundary
    are excluded even if they claim older source times.
    """
    if start >= end:
        raise ValueError("Log end must follow start")
    context_start = (date.fromisoformat(start) - timedelta(days=1)).isoformat()
    lower, upper = day_epoch(context_start, policy), day_epoch(end, policy)
    quality = Counter()
    log_root = Path(log_root)
    if not log_root.is_dir():
        raise ValueError(f"Log root does not exist: {log_root}")
    pv_paths = log_paths(log_root / "electricity", "pv_inverter.json", context_start, end)
    if not pv_paths:
        raise ValueError("No PV log files found for the requested period")
    pv = {}
    for row in records(pv_paths, quality, "pv"):
        received = parse_timestamp(row.get("timestamp"), policy)
        if received is None:
            quality["pv_invalid_timestamp"] += 1
            continue
        if not lower <= received < upper:
            continue
        explicit = row.get("source_timestamp") is not None
        if explicit:
            observed = parse_timestamp(row["source_timestamp"], policy)
            if observed is None or not -60 <= received - observed <= policy.source_max_age_seconds:
                quality["pv_invalid_or_stale_source"] += 1
                continue
        elif allow_legacy:
            observed = received
        else:
            quality["pv_legacy_rejected"] += 1
            continue
        epoch = int(math.floor((observed + 150) / 300) * 300)
        if not lower <= epoch < upper:
            continue
        currents = tuple(number(row.get(f"pv{c}_input_current_a"), 0, 100) for c in range(1, 9))
        voltages = tuple(number(row.get(f"pv{c}_input_voltage_v"), 0, 1500) for c in range(1, 9))
        ac, dc = number(row.get("active_power_kw"), 0, 100), number(row.get("total_input_power_kw"), 0, 100)
        if ac is None and not any(i is not None and v is not None for i, v in zip(currents, voltages)):
            quality["pv_missing_measurements"] += 1
            continue
        usable = (row.get("inverter_connected") is not False and row.get("telemetry_state") != "missing"
                  and row.get("inverter_operating_state_code") != 40960)
        consistent = True
        if dc is not None and all(i is not None and v is not None for i, v in zip(currents, voltages)):
            measured = sum(i * v / 1000 for i, v in zip(currents, voltages))
            consistent = abs(measured - dc) <= max(.3, .05 * dc)
        azimuth, elevation, solar_hour = solar_position(epoch, policy)
        sample = Sample(epoch, datetime.fromtimestamp(epoch, ZoneInfo(policy.timezone)).date().isoformat(),
                        azimuth, elevation, solar_hour, currents, voltages, ac, dc,
                        usable=usable, source_kind="source" if explicit else "legacy", dc_consistent=consistent)
        priority = (not explicit, received)
        if epoch in pv:
            quality["pv_duplicate_buckets"] += 1
            if sample.currents != pv[epoch][1].currents or sample.ac_kw != pv[epoch][1].ac_kw:
                quality["pv_revised_buckets"] += 1
            if priority >= pv[epoch][0]:
                continue
        pv[epoch] = (priority, sample)

    weather = {}
    weather_paths = log_paths(log_root / "weather_station", "weather_station.json", context_start, end)
    for row in records(weather_paths, quality, "weather"):
        received = parse_timestamp(row.get("timestamp"), policy)
        updated = parse_timestamp(row.get("last_updated"), policy)
        if received is None or not lower <= received < upper:
            continue
        if updated is None or not -5 <= received - updated <= 120:
            quality["weather_stale_or_invalid_timestamp"] += 1
            continue
        state = row.get("state")
        if not isinstance(state, dict):
            quality["weather_missing_state"] += 1
            continue
        lux = number(state.get("illuminance_lux"), 0, 200000)
        temperature = number(state.get("temperature_c"), -40, 60)
        if lux is None or temperature is None:
            quality["weather_invalid_measurements"] += 1
            continue
        minute = int(received // 60)
        if minute not in weather or received < weather[minute][0]:
            weather[minute] = (received, lux, temperature)
    bins = defaultdict(list)
    for received, lux, temperature in weather.values():
        # Trailing five-minute bins: never use weather observed after the PV time.
        bins[int(math.ceil(received / 300) * 300)].append((lux, temperature))
    samples = []
    for _, sample in sorted(pv.values(), key=lambda pair: pair[1].epoch):
        values = bins.get(sample.epoch, [])
        if len(values) >= 3:
            from dataclasses import replace
            sample = replace(sample, lux=median(v[0] for v in values), temperature=median(v[1] for v in values))
            quality["weather_matched_samples"] += 1
        quality["pv_accepted_" + sample.source_kind] += 1
        if not sample.dc_consistent:
            quality["pv_dc_power_mismatches"] += 1
        samples.append(sample)
    quality["pv_unique_samples"] = len(samples)
    return samples, dict(quality)


def read_json(path):
    # Corrupt model/state files fail visibly; silently resetting would lose incidents.
    with Path(path).open(encoding="utf-8") as handle:
        return json.load(handle)


def atomic_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix="." + path.name, delete=False) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def state_lock(path):
    """Cross-process lock for a shadow run; the file may persist after release."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                if handle.tell() == 0:
                    handle.write(b"0")
                    handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            yield
        finally:
            if locked:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
