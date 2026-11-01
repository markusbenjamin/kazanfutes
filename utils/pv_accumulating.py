"""Whole-array reference, earlier calibration and multi-day inspection evidence.

Old replay implementations remain unchanged. Good-day selection uses independent
weather and data coverage, never the target's production level.
"""

from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import date, timedelta

if __package__:
    from .pv_array_weather import ArrayWeatherPolicy, hourly_points, predict_hours
    from .pv_performance import Policy, Predictor, PEERS, build_baseline, day_epoch, score_days
    from .pv_evidence import EvidencePolicy, calibrate, identity, validate_model as validate_evidence
else:
    from pv_array_weather import ArrayWeatherPolicy, hourly_points, predict_hours
    from pv_performance import Policy, Predictor, PEERS, build_baseline, day_epoch, score_days
    from pv_evidence import EvidencePolicy, calibrate, identity, validate_model as validate_evidence


MAX_DIFFUSE_FRACTION = .35


def make_reference(samples, weather, start, end, site=None, weather_policy=None):
    site, weather_policy = site or Policy(), weather_policy or ArrayWeatherPolicy()
    if start >= end:
        raise ValueError("Reference end must follow start")
    lower, upper = day_epoch(start, site), day_epoch(end, site)
    points, quality = hourly_points([s for s in samples if lower <= s.epoch < upper], weather, site, weather_policy)
    clear = [point for point in points if point["diffuse_fraction"] <= MAX_DIFFUSE_FRACTION]
    quality["diffuse_weather_hours"] = len(points) - len(clear)
    if not clear:
        raise ValueError("No usable independent-weather reference hours")
    reference = {"version": 1, "start": start, "end_exclusive": end,
                 "site": asdict(site), "weather_policy": asdict(weather_policy),
                 "max_diffuse_fraction": MAX_DIFFUSE_FRACTION, "points": clear, "quality": quality}
    reference["model_id"] = identity(reference)
    return reference


def daily_residuals(reference, samples, weather, start, end):
    if reference.get("version") != 1 or reference.get("model_id") != identity(reference):
        raise ValueError("Modified or unsupported array reference")
    if not reference["end_exclusive"] <= start < end:
        raise ValueError("Scoring must follow the frozen reference")
    site, policy = Policy(**reference["site"]), ArrayWeatherPolicy(**reference["weather_policy"])
    lower, upper = day_epoch(start, site), day_epoch(end, site)
    points, quality = hourly_points([s for s in samples if lower <= s.epoch < upper], weather, site, policy)
    clear = [p for p in points if p["diffuse_fraction"] <= reference["max_diffuse_fraction"]]
    quality["diffuse_weather_hours"] = len(points) - len(clear)
    predictions, excluded = predict_hours(reference["points"], clear, policy)
    by_day = defaultdict(list)
    eligible = Counter(point["day"] for point in clear)
    for point in predictions:
        by_day[point["day"]].append(point)
    output, day = [], date.fromisoformat(start)
    while day < date.fromisoformat(end):
        key = day.isoformat()
        values = by_day[key]
        row = {"day": key, "qualified": len(values) >= policy.min_daily_hours,
               "matched_hours": len(values), "eligible_weather_hours": eligible[key]}
        if values:
            actual, expected = (sum(p[field] for p in values) for field in ("actual_kw", "expected_kw"))
            row.update(actual_kwh=actual, expected_kwh=expected, deficit=1 - actual / expected,
                       minimum_reference_days=min(p["reference_days"] for p in values))
        output.append(row)
        day += timedelta(days=1)
    return output, {"hour_quality": quality, "prediction_exclusions": excluded}


def build_model(reference_samples, calibration_samples, weather, reference_start, reference_end,
                calibration_start, calibration_end, evidence_policy=None):
    if not reference_start < reference_end <= calibration_start < calibration_end:
        raise ValueError("Calibration must follow a separate earlier reference interval")
    reference = make_reference(reference_samples, weather, reference_start, reference_end)
    daily, quality = daily_residuals(reference, calibration_samples, weather, calibration_start, calibration_end)
    evidence = calibrate(daily, calibration_start, calibration_end, reference["model_id"],
                         evidence_policy or EvidencePolicy())
    differential_reference = build_baseline(reference_samples, reference_start, reference_end)
    differential_days = score_days(Predictor(differential_reference), calibration_samples,
                                  calibration_start, calibration_end)
    differential_evidence, unavailable = {}, {}
    calibration_daily = {"array": daily}
    for target in PEERS:
        target_days = [row for row in differential_days if row["target"] == target]
        calibration_daily[target] = target_days
        reference_id = identity({"reference": differential_reference["model_id"], "target": target})
        try:
            differential_evidence[target] = calibrate(target_days, calibration_start, calibration_end,
                                                       reference_id, evidence_policy or EvidencePolicy())
        except ValueError as error:
            unavailable[target] = str(error)
    model = {"version": 1, "kind": "accumulating_array_inspection", "reference": reference,
             "evidence": evidence, "calibration_quality": quality,
             "differential_reference": differential_reference, "differential_evidence": differential_evidence,
             "unavailable_targets": unavailable,
             "limitations": ["Reference and calibration periods are not certified healthy.",
                             "ERA5 weather is retrospective and regional; it is not measured roof irradiance.",
                             "An inspection recommendation does not confirm defective panels.",
                             "The March event influenced development; it is not a blind validation set."]}
    model["model_id"] = identity(model)
    return model, calibration_daily


def validate_model(model):
    if model.get("version") != 1 or model.get("kind") != "accumulating_array_inspection" or model.get("model_id") != identity(model):
        raise ValueError("Modified or unsupported accumulating model")
    if model["reference"].get("model_id") != identity(model["reference"]):
        raise ValueError("Reference hash mismatch")
    validate_evidence(model["evidence"])
    if model["evidence"]["reference_id"] != model["reference"]["model_id"]:
        raise ValueError("Evidence was calibrated for another reference")
    Predictor(model["differential_reference"])
    for target, evidence in model["differential_evidence"].items():
        validate_evidence(evidence)
        if evidence["reference_id"] != identity({"reference": model["differential_reference"]["model_id"], "target": target}):
            raise ValueError("Differential evidence/reference mismatch")
    return model


def evidence_models(model):
    return {"array": model["evidence"], **model["differential_evidence"]}


def describe_pattern(states):
    """Describe evidence without assuming that one pattern proves one cause."""
    whole = bool(states.get("array", {}).get("incident"))
    differential = sorted(target for target, state in states.items() if target != "array" and state.get("incident"))
    if whole and differential:
        pattern = "whole_array_loss_with_relative_imbalance"
    elif whole:
        pattern = "whole_array_loss_without_detected_relative_imbalance"
    elif differential:
        pattern = "relative_input_loss"
    else:
        pattern = "no_open_inspection"
    return {"pattern": pattern, "whole_array_inspection": whole, "relative_inputs": differential,
            "cause_confirmed": False, "physical_string_mapping": None,
            "interpretation": "Shared loss is compatible with soiling; relative loss is compatible with a local fault. Neither pattern uniquely identifies the cause."}
