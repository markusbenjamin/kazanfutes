"""Exploratory hourly whole-array replay with an independent radiation reference.

This is a follow-up to the failed string-relative March 2026 replay. It is not
enabled in the shadow service. ERA5 is retrospective, delayed, gridded weather;
an apparent shortfall is not proof of a particular hardware failure.
"""

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from statistics import median
from urllib.parse import urlencode
from urllib.request import urlopen

if __package__:
    from .pv_performance import Policy, day_epoch, quantile, solar_position
else:
    from pv_performance import Policy, day_epoch, quantile, solar_position


@dataclass(frozen=True)
class ArrayWeatherPolicy:
    min_hour_samples: int = 10
    min_ghi: float = 300.
    min_elevation: float = 20.
    max_azimuth_difference: float = 8.
    max_elevation_difference: float = 5.
    max_ghi_ratio: float = 1.25
    max_diffuse_fraction_difference: float = .20
    max_temperature_difference: float = 10.
    min_neighbors: int = 12
    min_reference_days: int = 5
    max_neighbors: int = 30
    max_neighbors_per_day: int = 2
    min_daily_hours: int = 3
    loss_threshold: float = .20
    persistence_days: int = 3
    evidence_window_days: int = 14


def fetch_era5(start, end_inclusive, site=None):
    """Explicit network operation; no files/cache. Returned times end mean hours.

    https://open-meteo.com/en/docs/historical-weather-api
    Radiation is the preceding hour's mean, not the instantaneous endpoint.
    """
    site = site or Policy()
    params = dict(latitude=site.latitude, longitude=site.longitude, start_date=start,
                  end_date=end_inclusive, models="era5", timezone="UTC", timeformat="unixtime",
                  hourly="shortwave_radiation,diffuse_radiation,temperature_2m")
    url = "https://archive-api.open-meteo.com/v1/archive?" + urlencode(params)
    with urlopen(url, timeout=45) as response:
        raw = response.read()
    payload = json.loads(raw)
    if payload.get("error"):
        raise ValueError(payload.get("reason", "Weather API error"))
    units = payload["hourly_units"]
    if units.get("shortwave_radiation") != "W/m²" or units.get("diffuse_radiation") != "W/m²":
        raise ValueError("Unexpected radiation units")
    if units.get("temperature_2m") != "°C" or units.get("time") != "unixtime":
        raise ValueError("Unexpected time/temperature units")
    hourly = payload["hourly"]
    keys = ("time", "shortwave_radiation", "diffuse_radiation", "temperature_2m")
    if len({len(hourly[key]) for key in keys}) != 1:
        raise ValueError("Weather arrays have different lengths")
    rows = {int(t): {"ghi": g, "diffuse": d, "temperature": temp}
            for t, g, d, temp in zip(*(hourly[key] for key in keys))}
    return rows, {"url": url, "sha256": hashlib.sha256(raw).hexdigest(),
                  "retrieved_at": datetime.now(timezone.utc).isoformat(), "hours": len(rows),
                  "grid_latitude": payload["latitude"], "grid_longitude": payload["longitude"],
                  "source": "Open-Meteo / ERA5", "point_in_time_weather": False}


def hourly_points(samples, weather, site=None, policy=None):
    """Join complete-enough PV hours to the same independent weather intervals.

    A sample at 10:00 belongs to the hour ending 11:00, never to 10:00. Missing
    target hours are not filled with zero; actual zero production is retained.
    """
    site, policy = site or Policy(), policy or ArrayWeatherPolicy()
    groups, excluded = defaultdict(dict), Counter()
    for sample in samples:
        if sample.usable and sample.ac_kw is not None:
            groups[(sample.epoch // 3600 + 1) * 3600][sample.epoch] = sample
    points = []
    for end, values in sorted(groups.items()):
        if len(values) < policy.min_hour_samples:
            excluded["incomplete_pv_hour"] += 1
            continue
        met = weather.get(end)
        if met is None or any(type(v) not in (float, int) or not math.isfinite(v) for v in met.values()):
            excluded["missing_weather"] += 1
            continue
        ghi, diffuse, temperature = met["ghi"], met["diffuse"], met["temperature"]
        if not policy.min_ghi <= ghi <= 1400 or not 0 <= diffuse <= ghi or not -40 <= temperature <= 60:
            excluded["weak_or_invalid_weather"] += 1
            continue
        epoch = end - 1800
        azimuth, elevation, solar_hour = solar_position(epoch, site)
        if elevation < policy.min_elevation:
            excluded["low_sun"] += 1
            continue
        points.append({"epoch": epoch, "day": next(iter(values.values())).day,
                       "azimuth": azimuth, "elevation": elevation, "solar_hour": solar_hour,
                       "ghi": ghi, "diffuse_fraction": diffuse / ghi, "temperature": temperature,
                       "actual_kw": sum(s.ac_kw for s in values.values()) / len(values),
                       "samples": len(values)})
    return points, dict(excluded)


def predict_hours(reference, evaluation, policy=None):
    """Fixed neighbor rules. No target output is used to choose evaluation hours."""
    policy = policy or ArrayWeatherPolicy()
    predictions, excluded = [], Counter()
    reference = [r for r in reference if .05 < r["actual_kw"] < 29.5]
    for row in evaluation:
        candidates = []
        for ref in reference:
            distances = (abs((row["azimuth"] - ref["azimuth"] + 180) % 360 - 180) / policy.max_azimuth_difference,
                         abs(row["elevation"] - ref["elevation"]) / policy.max_elevation_difference,
                         abs(math.log(row["ghi"] / ref["ghi"])) / math.log(policy.max_ghi_ratio),
                         abs(row["diffuse_fraction"] - ref["diffuse_fraction"]) / policy.max_diffuse_fraction_difference,
                         abs(row["temperature"] - ref["temperature"]) / policy.max_temperature_difference)
            if max(distances) <= 1:
                candidates.append((sum(d * d for d in distances), ref))
        groups, count = defaultdict(list), 0
        for _, ref in sorted(candidates, key=lambda pair: (pair[0], pair[1]["epoch"])):
            if len(groups[ref["day"]]) >= policy.max_neighbors_per_day:
                continue
            groups[ref["day"]].append(ref["actual_kw"] / ref["ghi"])
            count += 1
            if count >= policy.max_neighbors:
                break
        if count < policy.min_neighbors or len(groups) < policy.min_reference_days:
            excluded["insufficient_comparable_history"] += 1
            continue
        ratios = [median(values) for values in groups.values()]
        expected = median(ratios) * row["ghi"]
        if expected >= 28.5:
            excluded["expected_clipping"] += 1
            continue
        predictions.append({**row, "expected_kw": expected,
                            "lower_kw": quantile(ratios, .1) * row["ghi"],
                            "upper_kw": quantile(ratios, .9) * row["ghi"],
                            "reference_days": len(groups)})
    return predictions, dict(excluded)


def replay(reference_samples, evaluation_samples, weather, baseline_start, baseline_end,
           evaluation_start, evaluation_end, site=None, policy=None):
    site, policy = site or Policy(), policy or ArrayWeatherPolicy()
    if not baseline_start < baseline_end <= evaluation_start < evaluation_end:
        raise ValueError("Evaluation must follow the fixed reference period")
    r0, r1, e0, e1 = [day_epoch(day, site) for day in
                      (baseline_start, baseline_end, evaluation_start, evaluation_end)]
    reference, reference_quality = hourly_points([s for s in reference_samples if r0 <= s.epoch < r1], weather, site, policy)
    evaluation, evaluation_quality = hourly_points([s for s in evaluation_samples if e0 <= s.epoch < e1], weather, site, policy)
    predictions, exclusions = predict_hours(reference, evaluation, policy)
    groups = defaultdict(list)
    for row in predictions:
        groups[row["day"]].append(row)
    days, pending, episodes = [], [], []
    for day in sorted({s.day for s in evaluation_samples if e0 <= s.epoch < e1}):
        rows = groups[day]
        item = {"day": day, "hours": len(rows), "qualified": len(rows) >= policy.min_daily_hours}
        if rows:
            actual = sum(r["actual_kw"] for r in rows)
            item.update(deficit=1 - actual / sum(r["expected_kw"] for r in rows),
                        conservative_deficit=1 - actual / sum(r["lower_kw"] for r in rows))
        pending = [d for d in pending if (datetime.fromisoformat(day) - datetime.fromisoformat(d)).days < policy.evidence_window_days]
        if item["qualified"]:
            if item["conservative_deficit"] >= policy.loss_threshold:
                pending.append(day)
                if len(pending) == policy.persistence_days:
                    episodes.append({"first_evidence": pending[0], "opened": day})
            else:
                pending = []
        days.append(item)
    identity = {"policy": asdict(policy), "site": asdict(site), "reference": reference,
                "baseline_start": baseline_start, "baseline_end_exclusive": baseline_end}
    return {"model_id": hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest(),
            "policy": asdict(policy), "reference_hours": len(reference), "eligible_evaluation_hours": len(evaluation),
            "reference_quality": reference_quality, "evaluation_quality": evaluation_quality,
            "prediction_exclusions": exclusions, "daily": days, "candidate_episodes": episodes,
            "evaluation_start": evaluation_start, "evaluation_end_exclusive": evaluation_end,
            "baseline_start": baseline_start, "baseline_end_exclusive": baseline_end,
            "status": "posthoc_development_replay", "notifications_enabled": False,
            "limitations": ["ERA5 is a delayed regional estimate, not a roof irradiance measurement.",
                            "Bounds describe between-day spread, not calibrated confidence intervals.",
                            "Reference health is unknown; repair and cleaning effects are not isolated.",
                            "Design was chosen after the March event was inspected; this is not blind validation."]}
