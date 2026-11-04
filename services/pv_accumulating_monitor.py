r"""Calibrate, replay or persist sensitive PV inspection evidence.

Shared output loss and relative-input loss are separate tracks. This command
never sends notifications or controls devices. Without --output/--state, replay
and shadow only read inputs, fetch public weather, and print a report.

Examples (end-exclusive dates; choose explicit reference/calibration periods):
  python -m services.pv_accumulating_monitor calibrate --history-exports EXPORTS \
      --reference-from 2024-04-04 --reference-until 2025-07-01 \
      --from 2025-07-01 --until 2026-01-01 --output MODEL.json
  python -m services.pv_accumulating_monitor replay --model MODEL.json \
      --logs LOGS --allow-legacy-timestamps --from 2026-01-01 --until 2026-10-27
  python -m services.pv_accumulating_monitor shadow --model MODEL.json \
      --state STATE.json --allow-legacy-timestamps

Shadow checks relative inputs through yesterday. Independent ERA5-based array
evidence uses a configurable seven-day lag by default; its latest observation
date is reported separately. No completed reference or calibration is adapted.
"""

import argparse
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "utils"))
from pv_accumulating import build_model, daily_residuals, describe_pattern, evidence_models, validate_model
from pv_array_weather import fetch_era5
from pv_evidence import advance, identity, new_state
from pv_history_export import load_history_exports
from pv_inspections import evidence_after_inspection, inspection_details
from pv_performance import Policy, Predictor, day_epoch, score_days
from pv_performance_io import atomic_json, load_samples, read_json, state_lock


def iso_day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD") from error


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("calibrate", "replay", "shadow"):
        command = commands.add_parser(name)
        command.add_argument("--from", dest="start", type=iso_day, required=name != "shadow")
        command.add_argument("--output", type=Path, required=name == "calibrate")
        command.add_argument("--history-exports", type=Path, required=name == "calibrate")
        command.add_argument("--logs", type=Path, default=ROOT / "data/logs")
        command.add_argument("--allow-legacy-timestamps", action="store_true")
        if name != "shadow":
            command.add_argument("--until", dest="end", type=iso_day, required=True)
        if name == "calibrate":
            command.add_argument("--reference-from", type=iso_day, required=True)
            command.add_argument("--reference-until", type=iso_day, required=True)
        else:
            command.add_argument("--model", type=Path, required=True)
        if name == "replay":
            command.add_argument("--simulate-loss", action="append", default=[], metavar="TARGET:FRACTION",
                                 help="Explicit residual-only sensitivity check; does not simulate electrical coupling")
        if name == "shadow":
            command.add_argument("--state", type=Path)
            command.add_argument("--weather-lag-days", type=int, default=7)
    return result


def validate_destinations(args):
    roots = [args.logs.resolve()]
    if args.history_exports:
        roots.append(args.history_exports.resolve())
    destinations = [path.resolve() for path in (args.output, getattr(args, "state", None)) if path]
    if len(set(destinations)) != len(destinations):
        raise ValueError("Report and state must have different paths")
    for destination in destinations:
        if any(destination == root or root in destination.parents for root in roots):
            raise ValueError("Outputs must be outside the input trees")
        if getattr(args, "model", None) and destination == args.model.resolve():
            raise ValueError("Do not overwrite the frozen model")


def last_complete_weather_end(weather, start, end, site):
    """Do not advance the array cursor over weather that has not arrived yet."""
    latest, day = start, date.fromisoformat(start)
    while day.isoformat() < end:
        tomorrow = (day + timedelta(days=1)).isoformat()
        first, last = day_epoch(day.isoformat(), site), day_epoch(tomorrow, site)
        required = range(first + 3600, last + 1, 3600)
        if all(t in weather and all(type(weather[t].get(k)) in (float, int) and math.isfinite(weather[t][k])
                                    for k in ("ghi", "diffuse", "temperature")) for t in required):
            latest = tomorrow
        day += timedelta(days=1)
    return latest


def execute(args, now=None):
    validate_destinations(args)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    site = Policy()
    today = now.astimezone(ZoneInfo(site.timezone)).date().isoformat()
    if args.command == "calibrate":
        if not args.reference_from < args.reference_until <= args.start < args.end <= today:
            raise ValueError("Use separate completed reference and calibration intervals")
        with state_lock(str(args.output) + ".lock"):
            if args.output.exists():
                raise ValueError("Model destination exists; choose a new versioned path")
            reference, reference_quality = load_history_exports(args.history_exports, args.reference_from,
                                                                 args.reference_until, site)
            calibration, calibration_quality = load_history_exports(args.history_exports, args.start, args.end, site)
            weather, provenance = fetch_era5(args.reference_from, args.end, site)
            model, _ = build_model(reference, calibration, weather, args.reference_from, args.reference_until,
                                   args.start, args.end)
            model.update(weather_provenance=provenance,
                         training_quality={"reference": reference_quality, "calibration": calibration_quality})
            model["model_id"] = identity(model)
            atomic_json(args.output, model)
        return {"mode": "calibrate", "model_id": model["model_id"], "output": str(args.output),
                "targets": {t: {"days": e["calibration_days"], "thresholds": e["thresholds"]}
                            for t, e in evidence_models(model).items()}, "unavailable_targets": model["unavailable_targets"],
                "notifications_enabled": False}

    model = validate_model(read_json(args.model))
    site = Policy(**model["reference"]["site"])
    today = now.astimezone(ZoneInfo(site.timezone)).date().isoformat()
    end = today if args.command == "shadow" else args.end
    if end > today:
        raise ValueError("Only completed local days may be evaluated")
    if args.command == "replay" and args.start >= end:
        raise ValueError("Replay end must follow start")
    if args.command == "shadow" and (args.weather_lag_days < 1 or args.history_exports):
        raise ValueError("Shadow requires a positive weather lag and logger inputs")
    array_end = ((date.fromisoformat(today) - timedelta(days=args.weather_lag_days - 1)).isoformat()
                 if args.command == "shadow" else end)
    calibrations = evidence_models(model)
    simulation = {}
    for item in getattr(args, "simulate_loss", []):
        target, fraction = item.split(":")
        value = float(fraction)
        if target in simulation or target not in calibrations or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError("Use each available target once with a loss between zero and one")
        simulation[target] = value
    state_path = getattr(args, "state", None)
    with state_lock(str(state_path) + ".lock") if state_path else nullcontext():
        state = (read_json(state_path) if state_path and state_path.exists() else
                 {"version": 1, "model_id": model["model_id"], "targets": {t: new_state(e) for t, e in calibrations.items()}})
        if state.get("version") != 1 or state.get("model_id") != model["model_id"] or set(state["targets"]) != set(calibrations):
            raise ValueError("State/model mismatch; use separate state")
        default_start = max(model["evidence"]["calibration_end_exclusive"],
                            (date.fromisoformat(end) - timedelta(days=45)).isoformat())
        starts = {}
        for target, evidence in calibrations.items():
            last = state["targets"][target]["last_day"]
            initial = state["targets"][target].get("initial_start")
            start = ((date.fromisoformat(last) + timedelta(days=1)).isoformat() if last else
                     (initial or args.start or default_start))
            if (last or initial) and args.start and args.start != start:
                raise ValueError("--from cannot rewrite or skip persisted days")
            if start < evidence["calibration_end_exclusive"] or start > end:
                raise ValueError("Invalid evaluation interval")
            starts[target] = start
            state["targets"][target].setdefault("initial_start", start)
        start = min(starts.values())
        if start >= end:
            samples, input_quality = [], {}
        elif args.history_exports:
            samples, input_quality = load_history_exports(args.history_exports, start, end, site)
        else:
            samples, input_quality = load_samples(args.logs, start, end, site, allow_legacy=args.allow_legacy_timestamps)
        daily, quality, provenance = {}, {}, None
        if starts["array"] < array_end:
            weather_start = (date.fromisoformat(starts["array"]) - timedelta(days=1)).isoformat()
            try:
                weather, provenance = fetch_era5(weather_start, array_end, site)
            except (OSError, ValueError, KeyError, TypeError) as error:
                if args.command != "shadow":
                    raise
                weather = {}
                quality["array_weather_error"] = str(error)
            array_end = last_complete_weather_end(weather, starts["array"], array_end, site)
            if starts["array"] < array_end:
                daily["array"], quality["array"] = daily_residuals(model["reference"], samples, weather, starts["array"], array_end)
        relative_start = min((starts[t] for t in calibrations if t != "array"), default=end)
        if relative_start < end:
            relative = score_days(Predictor(model["differential_reference"]), samples, relative_start, end)
            for target in calibrations:
                if target != "array":
                    daily[target] = [r for r in relative if r["target"] == target and r["day"] >= starts[target]]
        events, decisions = [], {}
        for target, evidence in calibrations.items():
            target_days = evidence_after_inspection(daily.get(target, []), state["targets"][target])
            if target in simulation:
                target_days = [{**row, "deficit": 1 - (1 - row["deficit"]) * (1 - simulation[target])}
                               if "deficit" in row else row for row in target_days]
            scored, changes = advance(state["targets"][target], target_days, evidence)
            decisions[target] = scored
            events.extend({**event, "target": target} for event in changes)
        events.sort(key=lambda event: (event.get("recovered", event["opened"]), event["target"]))
        state["last_run"] = now.isoformat()
        state["recent_events"] = (state.get("recent_events", []) + events)[-200:]
        summary = {}
        gaps = dict(model["unavailable_targets"])
        for target, target_state in state["targets"].items():
            last = target_state.get("last_evidence_day")
            age = (date.fromisoformat(today) - date.fromisoformat(last)).days if last else None
            summary[target] = {"qualified_days": sum(row["qualified"] for row in decisions[target]),
                               "last_processed_day": target_state["last_day"], "last_evidence_day": last,
                               "evidence_age_days": age,
                               "inspection": target_state["incident"], "latest_status": target_state.get("latest", {}).get("status")}
            summary[target].update(inspection_details(target_state))
            if last is None or age >= calibrations[target]["policy"]["calendar_window_days"]:
                gaps[target] = "No recent qualifying evidence; absence of an inspection is not a health assessment"
        report = {"mode": args.command, "model_id": model["model_id"], "notifications_enabled": False,
                  "evaluation_start_by_target": starts, "relative_end_exclusive": end,
                  "array_end_exclusive": array_end, "simulation": simulation or None,
                  "summary": summary, "pattern": describe_pattern(state["targets"]), "events": events,
                  "daily": decisions, "input_quality": input_quality, "quality": quality,
                  "weather_provenance": provenance, "unavailable_targets": model["unavailable_targets"],
                  "monitoring_gaps": gaps,
                  "limitations": model["limitations"], "state": state}
        if state_path:
            atomic_json(state_path, state)
        if args.output:
            atomic_json(args.output, report)
        return report


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        print(json.dumps(execute(args), indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error), "notifications_enabled": False}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
