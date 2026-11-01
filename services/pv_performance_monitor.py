r"""Build a frozen PV baseline, replay it, or run a persistent shadow monitor.

Examples (run at the repository root; dates are end-exclusive):

  python -m services.pv_performance_monitor baseline --from 2026-04-01 \
      --until 2026-07-01 --allow-legacy-timestamps --output /tmp/pv-baseline.json
  python -m services.pv_performance_monitor baseline --history-exports /path/to/exports \
      --from 2025-01-01 --until 2026-01-01 --output /tmp/pv-2025.json
  python -m services.pv_performance_monitor replay --model /tmp/pv-baseline.json \
      --from 2026-07-01 --until 2026-11-01 --allow-legacy-timestamps
  python -m services.pv_performance_monitor shadow --model /tmp/pv-baseline.json \
      --state /var/lib/kazanfutes/pv_performance/state.json

The baseline dates above are examples, not certified healthy periods. Baseline
selection and seasonal coverage need review before operational notifications.
Only complete local days are evaluated. Without --state/--output, replay and
shadow commands only read logs and print JSON. No command sends notifications,
controls devices, registers a timer, or automatically updates a baseline.
An external scheduler can invoke shadow once daily after midnight.

Use replay --simulate-loss pv1:0.10 for an explicitly labelled residual-only
sensitivity screen. It does not simulate electrical coupling or panel failures.
Small-input candidates (PV6/PV8) are always marked exploratory.
History exports have no weather measurements: an export-only baseline cannot
evaluate whole-array performance. See pv_performance_validation.md for the
failed March 2026 event replay and the distinction from total-production loss.
"""

from __future__ import annotations

import argparse
from contextlib import nullcontext
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
# utils.__init__ eagerly imports device/cloud dependencies. This standalone
# read-only monitor loads its pure siblings directly, without those side effects.
sys.path.insert(0, str(ROOT / "utils"))

from pv_performance import (
    Policy, Predictor, TARGETS, advance, build_baseline, new_state, render_event, score_days,
)
from pv_performance_io import atomic_json, load_samples, read_json, state_lock


def iso_day(value):
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise argparse.ArgumentTypeError("Expected a calendar date YYYY-MM-DD") from error


def parser():
    result = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("baseline", "replay", "shadow"):
        command = commands.add_parser(name)
        command.add_argument("--logs", type=Path, default=ROOT / "data/logs", help="Existing Pi log root; read-only")
        command.add_argument("--allow-legacy-timestamps", action="store_true",
                             help="Opt in to pre-source-timestamp records with lower provenance confidence")
        command.add_argument("--from", dest="start", type=iso_day, required=name != "shadow")
        command.add_argument("--output", type=Path, required=name == "baseline",
                             help="Explicit JSON destination outside the input log tree")
        if name == "baseline":
            command.add_argument("--policy", type=Path, help="Optional JSON overrides for Policy fields")
            command.add_argument("--history-exports", type=Path,
                                 help="Use notebook history CSV exports instead of logger files; exports must predate --until")
        else:
            command.add_argument("--model", type=Path, required=True)
        if name != "shadow":
            command.add_argument("--until", dest="end", type=iso_day, required=True, help="Exclusive local date")
        if name == "replay":
            command.add_argument("--simulate-loss", action="append", default=[], metavar="TARGET:FRACTION",
                                 help="Residual-only loss on the evaluation period, e.g. pv1:0.10")
        if name == "shadow":
            command.add_argument("--state", type=Path, help="Persist closed-day incident state; omitted means preview")
    return result


def validate_destinations(args):
    log_root = args.logs.resolve()
    history_root = getattr(args, "history_exports", None)
    destinations = [p.resolve() for p in (args.output, getattr(args, "state", None)) if p is not None]
    model = getattr(args, "model", None)
    for destination in destinations:
        if destination == log_root or log_root in destination.parents:
            raise ValueError("Outputs must be outside the input log tree")
        if history_root is not None and (destination == history_root.resolve() or history_root.resolve() in destination.parents):
            raise ValueError("Outputs must be outside the input export tree")
        if model is not None and destination == model.resolve():
            raise ValueError("A report/state must not overwrite its frozen baseline")
    if len(destinations) != len(set(destinations)):
        raise ValueError("Report and state must use different destinations")


def report(predictor, daily, state, events, quality, start, end, mode, simulation):
    for event in events:
        event["message"] = render_event(event)
    summary = {}
    for target in TARGETS:
        rows = [row for row in daily if row["target"] == target]
        item = state["targets"].get(target, {})
        last = item.get("last_evidence_day")
        age = (date.fromisoformat(end) - date.fromisoformat(last)).days if last else None
        summary[target] = {
            "qualified_days": sum(row["qualified"] for row in rows),
            "evaluated_calendar_days": len(rows), "matched_hours": sum(row["matched_hours"] for row in rows),
            "active_candidate": item.get("incident"), "last_evidence_day": last,
            "evidence_stale": age is None or age > predictor.policy.evidence_window_days,
            "latest_status": item.get("latest", {}).get("status", "insufficient_evidence"),
        }
    return {"mode": mode, "notifications_enabled": False, "model_id": predictor.model["model_id"],
            "baseline_start": predictor.model["baseline_start"], "baseline_end": predictor.model["baseline_end"],
            "evaluation_start": start, "evaluation_end_exclusive": end,
            "simulation": simulation or None, "quality": quality, "summary": summary,
            "daily": daily, "events": events, "state": state,
            "limitations": [
                "Energy and shortfall refer only to matched five-minute windows, not full-day yield.",
                "Prediction bounds describe historical between-day spread, not a calibrated confidence interval.",
                "Reference periods are operator-selected and are not automatically certified healthy.",
                "Logged input labels do not identify physical strings or individual defective panels.",
                "PV6/PV8 candidates and all simulated losses are exploratory.",
                "The weather device timestamp does not prove individual lux-field freshness.",
            ]}


def execute(args, now=None):
    validate_destinations(args)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now must include a timezone")
    if args.command == "baseline":
        overrides = read_json(args.policy) if args.policy else {}
        policy = Policy(**overrides)
        today = now.astimezone(ZoneInfo(policy.timezone)).date().isoformat()
        if args.end > today:
            raise ValueError("Baseline may contain only completed local days")
        with state_lock(str(args.output) + ".lock"):
            if args.output.exists():
                raise ValueError("Baseline destination already exists; choose a new versioned path")
            if args.history_exports:
                from pv_history_export import load_history_exports
                samples, quality = load_history_exports(args.history_exports, args.start, args.end, policy)
            else:
                samples, quality = load_samples(args.logs, args.start, args.end, policy,
                                                allow_legacy=args.allow_legacy_timestamps)
            model = build_baseline(samples, args.start, args.end, policy)
            atomic_json(args.output, model)
        return {"mode": "baseline", "model_id": model["model_id"], "output": str(args.output),
                "points": {target: len(points) for target, points in model["points"].items()},
                "quality": quality, "notifications_enabled": False}

    predictor = Predictor(read_json(args.model))
    today = now.astimezone(ZoneInfo(predictor.policy.timezone)).date().isoformat()
    end = today if args.command == "shadow" else args.end
    if end > today:
        raise ValueError("Evaluation may contain only completed local days")
    simulation = {}
    for spec in getattr(args, "simulate_loss", []):
        target, loss = spec.split(":")
        if target in simulation:
            raise ValueError("Specify each simulated target once")
        simulation[target] = float(loss)
    state_path = getattr(args, "state", None)
    lock = state_lock(str(state_path) + ".lock") if state_path else nullcontext()
    with lock:
        state = read_json(state_path) if state_path and state_path.exists() else new_state(predictor.model["model_id"])
        if state.get("version") != 1 or state.get("model_id") != predictor.model["model_id"]:
            raise ValueError("State/baseline mismatch; use a separate state file")
        if state.get("last_day"):
            start = (date.fromisoformat(state["last_day"]) + timedelta(days=1)).isoformat()
            if args.start and args.start != start:
                raise ValueError("--from cannot skip or rewrite persisted days; use a separate state file")
        else:
            start = args.start or max(predictor.model["baseline_end"],
                                      (date.fromisoformat(end) - timedelta(days=30)).isoformat())
        if start < predictor.model["baseline_end"]:
            raise ValueError("Evaluation must start after the frozen baseline")
        if start > end or (start == end and args.command != "shadow"):
            raise ValueError("Invalid evaluation interval or state from the future")
        if start == end:
            daily, quality = [], {}
        else:
            samples, quality = load_samples(args.logs, start, end, predictor.policy,
                                            allow_legacy=args.allow_legacy_timestamps)
            daily = score_days(predictor, samples, start, end, simulation=simulation)
        events = advance(state, daily, predictor)
        state["last_run"] = now.isoformat()
        payload = report(predictor, daily, state, events, quality, start, end, args.command, simulation)
        if state_path:
            state["recent_events"] = (state.get("recent_events", []) + events)[-200:]
            state["last_quality"] = quality
            atomic_json(state_path, state)
        if args.output:
            atomic_json(args.output, payload)
    return payload


def main(argv=None):
    arguments = parser().parse_args(argv)
    try:
        payload = execute(arguments)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error), "notifications_enabled": False}), file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, allow_nan=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
