"""Pure, dependency-free PV performance models and shadow incident tracking.

Physical string counts remain 14/14/25/25/5/5; no physical-to-telemetry
permutation is assumed. Comparisons use empirical logged-input relationships.
Reference periods are explicitly selected and frozen, never updated by scoring.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import math
from statistics import median
from zoneinfo import ZoneInfo


VERSION = 1
PEERS = {"pv1": 4, "pv2": 3, "pv3": 2, "pv4": 1, "pv6": 8, "pv8": 6}
TARGETS = tuple(PEERS) + ("array",)


@dataclass(frozen=True)
class Policy:
    timezone: str = "Europe/Budapest"
    latitude: float = 47.4879
    longitude: float = 19.0929
    min_elevation: float = 20.0
    max_azimuth_difference: float = 5.0
    max_elevation_difference: float = 3.0
    max_reference_ratio: float = 1.25
    max_temperature_difference: float = 10.0
    max_reference_spread: float = 0.15
    max_prediction_spread: float = 0.40
    min_neighbors: int = 20
    min_reference_days: int = 5
    max_neighbors: int = 40
    max_neighbors_per_day: int = 4
    min_daily_samples: int = 12
    min_daily_solar_hours: int = 2
    persistence_days: int = 3
    evidence_window_days: int = 14
    recovery_days: int = 2
    main_loss_threshold: float = 0.10
    pv6_loss_threshold: float = 0.20
    pv8_loss_threshold: float = 0.30
    array_loss_threshold: float = 0.20
    clipping_kw: float = 29.5
    source_max_age_seconds: int = 1200

    def __post_init__(self):
        ZoneInfo(self.timezone)
        for name, value in asdict(self).items():
            if name != "timezone" and (isinstance(value, bool) or not math.isfinite(value)):
                raise ValueError(f"Invalid policy value: {name}")
        if not -90 < self.latitude < 90 or not -180 <= self.longitude <= 180:
            raise ValueError("Invalid site coordinates")
        for name in ("main_loss_threshold", "pv6_loss_threshold", "pv8_loss_threshold", "array_loss_threshold"):
            if not 0 < getattr(self, name) < 1:
                raise ValueError(f"Invalid loss threshold: {name}")
        for name in ("min_neighbors", "min_reference_days", "max_neighbors", "max_neighbors_per_day",
                     "min_daily_samples", "min_daily_solar_hours", "persistence_days",
                     "evidence_window_days", "recovery_days", "source_max_age_seconds"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"Expected positive integer: {name}")
        if self.min_neighbors > self.max_neighbors or self.min_reference_days > self.max_neighbors:
            raise ValueError("Impossible neighbor requirements")
        if self.max_reference_ratio <= 1 or not 0 < self.min_elevation < 90:
            raise ValueError("Invalid reference ratio or elevation")
        for name in ("max_azimuth_difference", "max_elevation_difference", "max_temperature_difference",
                     "max_reference_spread", "max_prediction_spread", "clipping_kw"):
            if getattr(self, name) <= 0:
                raise ValueError(f"Expected positive value: {name}")

    def threshold(self, target):
        return getattr(self, target + "_loss_threshold", self.main_loss_threshold)


@dataclass(frozen=True)
class Sample:
    epoch: int
    day: str
    azimuth: float
    elevation: float
    solar_hour: float
    currents: tuple
    voltages: tuple
    ac_kw: float | None
    dc_kw: float | None
    lux: float | None = None
    temperature: float | None = None
    usable: bool = True
    source_kind: str = "source"
    dc_consistent: bool = True

    def power(self, channel):
        current, voltage = self.currents[channel - 1], self.voltages[channel - 1]
        return None if current is None or voltage is None else current * voltage / 1000


def number(value, minimum=None, maximum=None):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(value) or (minimum is not None and value < minimum) or (maximum is not None and value > maximum):
        return None
    return value


def day_epoch(day, policy):
    return int(datetime.combine(date.fromisoformat(day), datetime.min.time(), ZoneInfo(policy.timezone)).timestamp())


def solar_position(epoch, policy):
    """NOAA approximate solar equations, UTC input; no PV-derived sun proxy.

    https://gml.noaa.gov/grad/solcalc/solareqns.PDF
    Angular matching deliberately tolerates the small approximation error.
    """
    dt = datetime.fromtimestamp(epoch, timezone.utc)
    hour = dt.hour + dt.minute / 60 + dt.second / 3600
    days = 366 if date(dt.year, 12, 31).timetuple().tm_yday == 366 else 365
    gamma = 2 * math.pi / days * (dt.timetuple().tm_yday - 1 + (hour - 12) / 24)
    equation = 229.18 * (.000075 + .001868 * math.cos(gamma) - .032077 * math.sin(gamma)
                         - .014615 * math.cos(2 * gamma) - .040849 * math.sin(2 * gamma))
    declination = (.006918 - .399912 * math.cos(gamma) + .070257 * math.sin(gamma)
                   - .006758 * math.cos(2 * gamma) + .000907 * math.sin(2 * gamma)
                   - .002697 * math.cos(3 * gamma) + .00148 * math.sin(3 * gamma))
    solar_hour = (hour + (equation + 4 * policy.longitude) / 60) % 24
    angle = math.radians((solar_hour - 12) * 15)
    latitude = math.radians(policy.latitude)
    sine = math.sin(latitude) * math.sin(declination) + math.cos(latitude) * math.cos(declination) * math.cos(angle)
    elevation = math.degrees(math.asin(max(-1, min(1, sine))))
    azimuth = (math.degrees(math.atan2(math.sin(angle), math.cos(angle) * math.sin(latitude)
                                     - math.tan(declination) * math.cos(latitude))) + 180) % 360
    return azimuth, elevation, solar_hour


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        raise ValueError("Empty quantile")
    position = (len(values) - 1) * fraction
    left = int(position)
    return values[left] + (values[min(left + 1, len(values) - 1)] - values[left]) * (position - left)


def context(samples, index, target, policy):
    """Eligibility depends on independent references, never low target output."""
    sample = samples[index]
    if not sample.usable:
        return None, "unusable_telemetry"
    if sample.elevation < policy.min_elevation:
        return None, "low_sun"
    if index < 2 or any(samples[k].epoch - samples[k - 1].epoch != 300 for k in (index - 1, index)):
        return None, "reference_gap"
    triple = samples[index - 2:index + 1]
    if any(not item.usable for item in triple):
        return None, "unusable_reference"
    if target == "array":
        values = [item.lux for item in triple]
        reference = sample.lux
        if sample.ac_kw is None:
            return None, "missing_target"
        if reference is None or reference < 10000 or sample.temperature is None:
            return None, "missing_or_dim_weather"
        scale = reference
    else:
        channel, peer = int(target[2:]), PEERS[target]
        if not sample.dc_consistent:
            return None, "dc_power_mismatch"
        if sample.power(channel) is None:
            return None, "missing_target"
        if sample.ac_kw is None:
            return None, "missing_clipping_status"
        if sample.ac_kw >= policy.clipping_kw:
            return None, "clipping"
        values = [item.currents[peer - 1] for item in triple]
        reference, scale = sample.currents[peer - 1], sample.power(peer)
        if reference is None or reference < 2 or scale is None or scale < .5:
            return None, "weak_or_missing_peer"
    if any(value is None for value in values):
        return None, "missing_reference"
    if (max(values) - min(values)) / max(sum(values) / len(values), .01) > policy.max_reference_spread:
        return None, "unstable_reference"
    return {"reference": reference, "scale": scale}, None


def model_identity(model):
    payload = {key: value for key, value in model.items() if key != "model_id"}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_baseline(samples, start, end, policy=None):
    policy = policy or Policy()
    first, last = day_epoch(start, policy), day_epoch(end, policy)
    if first >= last:
        raise ValueError("Baseline end must follow start (end is exclusive)")
    points = {target: [] for target in TARGETS}
    excluded = {target: Counter() for target in TARGETS}
    selected = set()
    for index, sample in enumerate(samples):
        if not first <= sample.epoch < last:
            continue
        for target in TARGETS:
            ctx, reason = context(samples, index, target, policy)
            if reason:
                excluded[target][reason] += 1
                continue
            actual = sample.ac_kw if target == "array" else sample.power(int(target[2:]))
            if actual is None or actual <= .05:
                excluded[target]["nonproducing_reference_period"] += 1
                continue
            slot = (target, sample.epoch // 900)
            if slot in selected:
                continue
            selected.add(slot)
            point = {"epoch": sample.epoch, "day": sample.day, "azimuth": sample.azimuth,
                     "elevation": sample.elevation, "reference": ctx["reference"],
                     "temperature": sample.temperature if target == "array" else None,
                     "power_ratio": actual / ctx["scale"]}
            if target != "array":
                channel, peer = int(target[2:]), PEERS[target]
                point["current_ratio"] = sample.currents[channel - 1] / sample.currents[peer - 1]
                point["voltage_ratio"] = sample.voltages[channel - 1] / sample.voltages[peer - 1]
            points[target].append(point)
    model = {"version": VERSION, "baseline_start": start, "baseline_end": end,
             "policy": asdict(policy), "points": points,
             "baseline_assumption": "Operator-selected reference period; health is not inferred or certified",
             "physical_string_panel_counts": [14, 14, 25, 25, 5, 5],
             "physical_string_mapping": None,
             "excluded": {target: dict(counts) for target, counts in excluded.items()},
             "legacy_samples": sum(first <= s.epoch < last and s.source_kind == "legacy" for s in samples)}
    if not any(points.values()):
        raise ValueError("No usable baseline points; inspect coverage, timestamps and reference dates")
    model["model_id"] = model_identity(model)
    return model


class Predictor:
    def __init__(self, model):
        if model.get("version") != VERSION or model.get("model_id") != model_identity(model):
            raise ValueError("Unsupported or modified baseline; rebuild it explicitly")
        self.model = model
        self.policy = Policy(**model["policy"])
        self.end = day_epoch(model["baseline_end"], self.policy)
        self.index = {target: defaultdict(list) for target in TARGETS}
        for target in TARGETS:
            for point in model["points"][target]:
                if not day_epoch(model["baseline_start"], self.policy) <= point["epoch"] < self.end:
                    raise ValueError("Baseline contains observations outside its declared period")
                # Fixed spatial bins bound the search cost; exact limits are checked below.
                self.index[target][(int(point["azimuth"] // 5), int(point["elevation"] // 3))].append(point)

    def predict(self, samples, index, target):
        sample, policy = samples[index], self.policy
        if sample.epoch < self.end:
            raise ValueError("Evaluation must follow the frozen baseline")
        ctx, reason = context(samples, index, target, policy)
        if reason:
            return None, reason
        nearby = []
        azbin, elbin = int(sample.azimuth // 5), int(sample.elevation // 3)
        azrange = math.ceil(policy.max_azimuth_difference / 5)
        elrange = math.ceil(policy.max_elevation_difference / 3)
        for a in range(azbin - azrange, azbin + azrange + 1):
            for e in range(elbin - elrange, elbin + elrange + 1):
                for point in self.index[target].get((a % 72, e), ()):
                    da = abs((point["azimuth"] - sample.azimuth + 180) % 360 - 180)
                    de = abs(point["elevation"] - sample.elevation)
                    dr = abs(math.log(point["reference"] / ctx["reference"]))
                    if da > policy.max_azimuth_difference or de > policy.max_elevation_difference or dr > math.log(policy.max_reference_ratio):
                        continue
                    dt = 0
                    if target == "array":
                        dt = abs(point["temperature"] - sample.temperature)
                        if dt > policy.max_temperature_difference:
                            continue
                    distance = (da / policy.max_azimuth_difference) ** 2 + (de / policy.max_elevation_difference) ** 2
                    distance += (dr / math.log(policy.max_reference_ratio)) ** 2 + (dt / policy.max_temperature_difference) ** 2
                    nearby.append((distance, point))
        selected, by_day = [], Counter()
        for _, point in sorted(nearby, key=lambda pair: (pair[0], pair[1]["epoch"])):
            if by_day[point["day"]] >= policy.max_neighbors_per_day:
                continue
            selected.append(point)
            by_day[point["day"]] += 1
            if len(selected) >= policy.max_neighbors:
                break
        if len(selected) < policy.min_neighbors or len(by_day) < policy.min_reference_days:
            return None, "insufficient_comparable_history"
        # Days, not correlated five-minute samples, have equal influence.
        ratios = defaultdict(list)
        for point in selected:
            ratios[point["day"]].append(point["power_ratio"])
        daily_ratios = [median(values) for values in ratios.values()]
        center = median(daily_ratios)
        low, high = quantile(daily_ratios, .1), quantile(daily_ratios, .9)
        if (high - low) / center > policy.max_prediction_spread:
            return None, "uncertain_reference"
        expected = ctx["scale"] * center
        if expected < (3 if target == "array" else .5):
            return None, "weak_expected_production"
        if target == "array" and expected >= policy.clipping_kw - 1:
            return None, "expected_clipping"
        result = {"epoch": sample.epoch, "day": sample.day, "solar_hour": sample.solar_hour,
                  "actual_kw": sample.ac_kw if target == "array" else sample.power(int(target[2:])),
                  "expected_kw": expected, "lower_kw": ctx["scale"] * low,
                  "upper_kw": ctx["scale"] * high, "reference_days": len(by_day),
                  "reference_samples": len(selected)}
        if target != "array":
            channel, peer = int(target[2:]), PEERS[target]
            for metric, actual, reference in (("current", sample.currents[channel - 1], sample.currents[peer - 1]),
                                               ("voltage", sample.voltages[channel - 1], sample.voltages[peer - 1])):
                groups = defaultdict(list)
                for point in selected:
                    groups[point["day"]].append(point[metric + "_ratio"])
                expected_value = reference * median([median(values) for values in groups.values()])
                result[metric + "_ratio"] = actual / expected_value if expected_value > 0 else None
        return result, None


def summarize_day(day, target, predictions, reasons, policy):
    n = len(predictions)
    hours = sorted({int(p["solar_hour"]) for p in predictions})
    qualified = n >= policy.min_daily_samples and len(hours) >= policy.min_daily_solar_hours
    result = {"day": day, "target": target, "qualified": qualified,
              "status": "qualified" if qualified else "insufficient_evidence",
              "samples": n, "matched_hours": n / 12, "solar_hour_bins": hours,
              "exclusions": dict(reasons), "exploratory": target in ("pv6", "pv8"),
              "threshold": policy.threshold(target)}
    if not n:
        return result
    actual = sum(p["actual_kw"] for p in predictions) / 12
    expected = sum(p["expected_kw"] for p in predictions) / 12
    lower = sum(p["lower_kw"] for p in predictions) / 12
    upper = sum(p["upper_kw"] for p in predictions) / 12
    result.update(actual_kwh=actual, expected_kwh=expected, lower_expected_kwh=lower,
                  upper_expected_kwh=upper, deficit=1 - actual / expected,
                  conservative_deficit=1 - actual / lower,
                  recovery_deficit=1 - actual / upper,
                  matched_shortfall_kwh=max(0, expected - actual),
                  minimum_reference_days=min(p["reference_days"] for p in predictions))
    if target != "array":
        for metric in ("current", "voltage"):
            values = [p[metric + "_ratio"] for p in predictions if p.get(metric + "_ratio") is not None]
            result[metric + "_ratio"] = median(values) if values else None
        current, voltage = result["current_ratio"], result["voltage_ratio"]
        result["signature"] = ("current_and_voltage" if current < .95 and voltage < .95 else
                               "current" if current < .95 else "voltage" if voltage < .95 else "power_only")
    else:
        result["signature"] = "weather_relative_array_output"
    return result


def score_days(predictor, samples, start, end, *, simulation=None):
    """End-exclusive, complete calendar days. Simulation changes residuals only.

    Simulated losses leave references/eligibility frozen and are a sensitivity
    screen, not an electrical fault simulation or independent accuracy estimate.
    """
    policy = predictor.policy
    first, last = day_epoch(start, policy), day_epoch(end, policy)
    if first < predictor.end or first >= last:
        raise ValueError("Evaluation must start after baseline and end after start")
    simulation = simulation or {}
    for target, loss in simulation.items():
        if target not in TARGETS or number(loss, 0, 1) is None:
            raise ValueError("Simulation needs a known target and loss between zero and one")
    rows, excluded = defaultdict(list), defaultdict(Counter)
    for index, sample in enumerate(samples):
        if not first <= sample.epoch < last:
            continue
        for target in TARGETS:
            prediction, reason = predictor.predict(samples, index, target)
            key = (sample.day, target)
            if reason:
                excluded[key][reason] += 1
            else:
                prediction["actual_kw"] *= 1 - simulation.get(target, 0)
                rows[key].append(prediction)
    output = []
    day = date.fromisoformat(start)
    while day < date.fromisoformat(end):
        for target in TARGETS:
            key = (day.isoformat(), target)
            reasons = excluded[key]
            if not rows[key] and not reasons:
                reasons["no_observations"] += 1
            output.append(summarize_day(key[0], target, rows[key], reasons, policy))
        day += timedelta(days=1)
    return output


def new_state(model_id):
    return {"version": VERSION, "model_id": model_id, "last_day": None, "targets": {}}


def advance(state, daily, predictor):
    """Idempotent closed-day transitions; missing evidence cannot clear incidents."""
    if state.get("version") != VERSION or state.get("model_id") != predictor.model["model_id"]:
        raise ValueError("State belongs to a different baseline; choose a separate state file")
    policy, events = predictor.policy, []
    grouped = defaultdict(list)
    for row in daily:
        grouped[row["day"]].append(row)
    for day, records in sorted(grouped.items()):
        if state["last_day"] and day <= state["last_day"]:
            continue
        if len(records) != len(TARGETS) or {r["target"] for r in records} != set(TARGETS):
            raise ValueError("State updates require one record per target per day")
        today = date.fromisoformat(day)
        for row in records:
            target = row["target"]
            item = state["targets"].setdefault(target, {"pending": [], "recovery": [], "incident": None})
            for key in ("pending", "recovery"):
                item[key] = [d for d in item[key] if (today - date.fromisoformat(d)).days < policy.evidence_window_days]
            item["latest"] = row
            if not row["qualified"]:
                continue
            item["last_evidence_day"] = day
            if row["conservative_deficit"] >= row["threshold"]:
                item["pending"].append(day)
                item["recovery"] = []
                if item["incident"] is None and len(item["pending"]) >= policy.persistence_days:
                    first = item["pending"][0]
                    incident = {"id": f"{state['model_id'][:12]}:{target}:{first}", "target": target,
                                "opened": day, "first_evidence": first, "evidence_days": list(item["pending"]),
                                "evidence": row, "exploratory": row["exploratory"]}
                    item["incident"] = incident
                    events.append({"kind": "candidate_opened", **incident})
            else:
                item["pending"] = []
                if row["recovery_deficit"] < row["threshold"] / 2:
                    item["recovery"].append(day)
                    if item["incident"] is not None and len(item["recovery"]) >= policy.recovery_days:
                        events.append({"kind": "candidate_recovered", **item["incident"],
                                       "recovered": day, "recovery_evidence": row})
                        item["incident"] = None
                        item["recovery"] = []
                else:
                    item["recovery"] = []
        state["last_day"] = day
    return events


def render_event(event):
    evidence = event.get("recovery_evidence", event["evidence"])
    target = "Whole array" if event["target"] == "array" else "Logged input " + event["target"].upper()
    if event["kind"] == "candidate_recovered":
        return f"{target}: sustained recovery on qualifying observations; shadow candidate closed."
    return (f"{target}: {evidence['deficit']:.1%} below its reference prediction on "
            f"{evidence['matched_hours']:.2f} matched hours on {evidence['day']}; "
            f"persistent evidence on {len(event['evidence_days'])} qualifying days. "
            f"Observed/expected energy in those windows: {evidence['actual_kwh']:.2f}/"
            f"{evidence['expected_kwh']:.2f} kWh. Signature: {evidence['signature']}. "
            "Cause unconfirmed; shadow candidate only.")
