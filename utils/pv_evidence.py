"""Frozen calibration and persistent accumulation of daily PV shortfalls.

This module has no I/O. Thresholds come only from the declared earlier
calibration interval. They are empirical inspection thresholds, not p-values or
guarantees about false alarms. The reference period is not certified healthy.
"""

from dataclasses import asdict, dataclass
from datetime import date
import hashlib
import json
import math
from statistics import median

if __package__:
    from .pv_performance import quantile
else:
    from pv_performance import quantile


@dataclass(frozen=True)
class EvidencePolicy:
    min_days: int = 3
    max_days: int = 10
    calendar_window_days: int = 21
    minimum_loss: float = .03
    calibration_quantile: float = .90
    daily_cap: float = .25
    minimum_support_fraction: float = 2 / 3
    recovery_days: int = 3
    min_calibration_days: int = 40
    min_calibration_windows: int = 20

    def __post_init__(self):
        for name in ("min_days", "max_days", "calendar_window_days", "recovery_days",
                     "min_calibration_days", "min_calibration_windows"):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"Invalid positive integer: {name}")
        if not 2 <= self.min_days <= self.max_days <= self.calendar_window_days:
            raise ValueError("Invalid evidence windows")
        for name in ("minimum_loss", "calibration_quantile", "daily_cap", "minimum_support_fraction"):
            value = getattr(self, name)
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value < 1:
                raise ValueError(f"Invalid fraction: {name}")
        if self.daily_cap <= self.minimum_loss:
            raise ValueError("Daily cap must exceed minimum loss")


def identity(payload):
    return hashlib.sha256(json.dumps({k: v for k, v in payload.items() if k != "model_id"},
                                    sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def validate_rows(rows):
    previous = None
    for row in rows:
        day = date.fromisoformat(row["day"]).isoformat()
        if previous is not None and day <= previous:
            raise ValueError("Daily evidence must be unique and chronological")
        previous = day
        if type(row["qualified"]) is not bool:
            raise ValueError("Qualified must be a boolean")
        if row["qualified"]:
            value = row.get("deficit")
            if type(value) not in (int, float) or not math.isfinite(value) or value > 1:
                raise ValueError("Invalid daily shortfall")


def corrected_deficit(deficit, normal_ratio):
    return 1 - (1 - deficit) / normal_ratio


def clip(value, policy):
    return min(policy.daily_cap, max(-policy.daily_cap, value))


def recent_windows(history, policy):
    if not history:
        return
    today = date.fromisoformat(history[-1]["day"])
    valid = [r for r in history if (today - date.fromisoformat(r["day"])).days < policy.calendar_window_days]
    for count in range(policy.min_days, min(policy.max_days, len(valid)) + 1):
        yield count, valid[-count:]


def calibrate(rows, start, end, reference_id, policy=None):
    """Fit using only earlier rows; reject out-of-period input instead of hiding it."""
    policy = policy or EvidencePolicy()
    validate_rows(rows)
    if not start < end or any(not start <= row["day"] < end for row in rows):
        raise ValueError("Calibration rows must lie inside the declared interval")
    qualified = [row for row in rows if row["qualified"]]
    if len(qualified) < policy.min_calibration_days:
        raise ValueError(f"Insufficient calibration: {len(qualified)} qualifying days; need {policy.min_calibration_days}")
    normal_ratio = median(1 - row["deficit"] for row in qualified)
    if not .25 <= normal_ratio <= 4:
        raise ValueError("Reference/calibration mismatch is too large")
    history, statistics = [], {n: [] for n in range(policy.min_days, policy.max_days + 1)}
    for row in qualified:
        value = corrected_deficit(row["deficit"], normal_ratio)
        history.append({"day": row["day"], "score": clip(value, policy)})
        for count, window in recent_windows(history, policy):
            statistics[count].append(sum(r["score"] for r in window) / count)
    thresholds = {str(n): max(policy.minimum_loss, quantile(values, policy.calibration_quantile))
                  for n, values in statistics.items() if len(values) >= policy.min_calibration_windows}
    if str(policy.min_days) not in thresholds:
        raise ValueError("Insufficient contiguous calibration windows")
    model = {"version": 1, "reference_id": reference_id, "policy": asdict(policy),
             "calibration_start": start, "calibration_end_exclusive": end,
             "normal_output_ratio": normal_ratio, "thresholds": thresholds,
             "calibration_days": len(qualified),
             "calibration_windows": {str(n): len(values) for n, values in statistics.items()},
             "calibration_input_hash": identity({"rows": rows}),
             "interpretation": "Empirical inspection thresholds; reference health unknown; not confidence levels"}
    model["model_id"] = identity(model)
    return model


def validate_model(model):
    if model.get("version") != 1 or model.get("model_id") != identity(model):
        raise ValueError("Modified or unsupported evidence calibration")
    return EvidencePolicy(**model["policy"])


def new_state(model):
    validate_model(model)
    return {"version": 1, "model_id": model["model_id"], "last_day": None,
            "history": [], "recovery": [], "incident": None}


def advance(state, rows, model):
    """Update closed days once. Missing days cannot count toward recovery."""
    policy = validate_model(model)
    validate_rows(rows)
    if state.get("version") != 1 or state.get("model_id") != model["model_id"]:
        raise ValueError("Evidence state/calibration mismatch")
    if any(row["day"] < model["calibration_end_exclusive"] for row in rows):
        raise ValueError("Evaluation must follow calibration")
    output, events = [], []
    for row in rows:
        day = row["day"]
        if state["last_day"] and day <= state["last_day"]:
            continue
        today = date.fromisoformat(day)
        state["history"] = [r for r in state["history"]
                            if (today - date.fromisoformat(r["day"])).days < policy.calendar_window_days]
        state["recovery"] = [d for d in state["recovery"]
                             if (today - date.fromisoformat(d)).days < policy.calendar_window_days]
        item = {**row, "status": "insufficient_evidence", "inspection_open": state["incident"] is not None}
        if row["qualified"]:
            corrected = corrected_deficit(row["deficit"], model["normal_output_ratio"])
            state["history"].append({"day": day, "score": clip(corrected, policy),
                                      "deficit": row["deficit"], "corrected_deficit": corrected})
            state["history"] = state["history"][-policy.max_days:]
            candidates = []
            for count, window in recent_windows(state["history"], policy):
                threshold = model["thresholds"].get(str(count))
                if threshold is None:
                    continue
                score = sum(r["score"] for r in window) / count
                support = sum(r["corrected_deficit"] >= policy.minimum_loss / 2 for r in window)
                candidates.append({"days": count, "first_evidence": window[0]["day"], "score": score,
                                   "threshold": threshold, "supporting_days": support,
                                   "crossed": score >= threshold and support >= math.ceil(count * policy.minimum_support_fraction)})
            item.update(corrected_deficit=corrected, windows=candidates, status="collecting_evidence")
            crossed = [c for c in candidates if c["crossed"]]
            recovering = (state["recovery"] + [day]) if corrected < policy.minimum_loss / 2 else []
            sustained_recovery = len(recovering) >= policy.recovery_days
            if crossed and not sustained_recovery:
                strongest = max(crossed, key=lambda c: (c["score"] / c["threshold"], c["days"]))
                item["status"] = "inspection_recommended"
                if state["incident"] is None:
                    incident = {"id": f"{model['model_id'][:12]}:array:{day}", "opened": day,
                                "first_evidence": strongest["first_evidence"], "evidence": strongest,
                                "classification": "inspection_recommended", "cause": "unconfirmed"}
                    state["incident"] = incident
                    events.append({"kind": "inspection_opened", **incident})
            elif candidates:
                item["status"] = "below_inspection_threshold"

            if corrected < policy.minimum_loss / 2:
                state["recovery"] = recovering[-policy.recovery_days:]
                if state["incident"] is not None and len(state["recovery"]) >= policy.recovery_days:
                    events.append({"kind": "inspection_recovered", **state["incident"], "recovered": day,
                                   "recovery_evidence_days": list(state["recovery"])})
                    state["incident"] = None
                    state["history"] = []
                    state["recovery"] = []
                    item["status"] = "recovered"
            else:
                state["recovery"] = []
            item["inspection_open"] = state["incident"] is not None
            state["last_evidence_day"] = day
        state["latest"] = item
        state["last_day"] = day
        output.append(item)
    return output, events
