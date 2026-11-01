"""Scheduled PV inspections with durable, change-only admin notifications."""

import argparse
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services import pv_accumulating_monitor as monitor
from pv_performance_io import atomic_json, read_json, state_lock


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--model", type=Path, default=ROOT / "services/pv_accumulation_model_2025.json")
    result.add_argument("--logs", type=Path, default=ROOT / "data/logs")
    result.add_argument("--runtime-dir", type=Path, default=Path("/var/lib/kazanfutes-pv-watchdog"))
    result.add_argument("--bootstrap-from", type=monitor.iso_day,
                        help="Initial catch-up start only; subsequent runs use persisted cursors")
    result.add_argument("--weather-lag-days", type=int, default=7)
    result.add_argument("--dry-run", action="store_true", help="No writes or emails; recompute a preview")
    return result


def event_key(event):
    return ":".join(str(event.get(key, "")) for key in ("target", "kind", "id", "recovered"))


def describe_event(event):
    target = "Whole array" if event["target"] == "array" else "Logged " + event["target"].upper()
    if event["kind"] == "inspection_recovered":
        return f"{target}: inspection closed on {event['recovered']} after sustained recovery."
    evidence = event["evidence"]
    return (f"{target}: inspect. Evidence crossed on {event['opened']}; "
            f"{evidence['score']:.1%} accumulated corrected shortfall over {evidence['days']} qualifying days "
            f"(threshold {evidence['threshold']:.1%}). Cause unconfirmed.")


def coverage(report):
    gaps = dict(report["monitoring_gaps"])
    if report["quality"].get("array_weather_error"):
        gaps["array_weather"] = "Weather download unavailable; array evidence waits, relative checks continue."
    return gaps


def queue_changes(delivery, report, now):
    """Reconcile the engine's persisted journal, including after a process crash."""
    if delivery.get("version") != 1 or delivery.get("model_id") != report["model_id"]:
        raise ValueError("Notification state/model mismatch")
    known = set(delivery["seen_events"])
    recent = report["state"].get("recent_events", [])
    first = not delivery["initialized"]
    if first:
        # On activation summarize only incidents still open, not old recoveries.
        events = [{"kind": "inspection_opened", "target": target, **summary["inspection"]}
                  for target, summary in report["summary"].items() if summary["inspection"]]
    else:
        events = [event for event in recent if event_key(event) not in known]
    gaps = coverage(report)
    changed_coverage = gaps != delivery.get("coverage")
    if first or events or changed_coverage:
        lines = ["PV performance watchdog enabled." if first else "PV performance watchdog update."]
        lines += ["", *[describe_event(event) for event in events]]
        if first and not events:
            lines.append("No open inspection at activation; this does not establish that the array is healthy.")
        lines += ["", "Latest qualifying evidence:"]
        for target, summary in report["summary"].items():
            lines.append(f"  {target.upper()}: {summary['last_evidence_day'] or 'none'}")
        lines += ["", "Monitoring limitations:"]
        lines += [f"  {target.upper()}: {reason}" for target, reason in sorted(gaps.items())]
        lines += ["  Array evidence uses delayed regional weather. Relative input checks do not need that weather.",
                  "  Shared loss can be soiling or another common cause; relative loss can be a local fault.",
                  "  These patterns do not identify a defective panel or a physical string label.",
                  "", f"Report generated: {now.isoformat()}", f"Frozen model: {report['model_id']}"]
        subject = ("[PV] Watchdog enabled - inspection recommended" if first and events else
                   "[PV] Watchdog enabled" if first else
                   "[PV] Inspection recommended" if any(e["kind"] == "inspection_opened" for e in events) else
                   "[PV] Inspection / monitoring update")
        body = "\n".join(lines)
        delivery["outbox"].append({"id": hashlib.sha256(body.encode()).hexdigest(), "subject": subject,
                                   "body": body, "queued_at": now.isoformat()})
    delivery["seen_events"] = list(dict.fromkeys(delivery["seen_events"] + [event_key(e) for e in recent]))[-2000:]
    delivery["coverage"] = gaps
    delivery["initialized"] = True


def send_admin(subject, body):
    # Import the existing notification route only when an actual email is due.
    from utils.project import notify_admin
    return notify_admin(subject, body)


def run(args, now=None, sender=None):
    now = now or datetime.now(timezone.utc)
    runtime = args.runtime_dir.resolve()
    logs = args.logs.resolve()
    model_path = args.model.resolve()
    if runtime == logs or logs in runtime.parents or model_path == runtime or runtime in model_path.parents:
        raise ValueError("Runtime must be separate from inputs and model")
    state_path = runtime / "evidence_state.json"
    delivery_path = runtime / "notifications.json"
    report_path = runtime / "latest_report.json"
    arguments = ["shadow", "--model", str(model_path), "--logs", str(logs),
                 "--allow-legacy-timestamps", "--weather-lag-days", str(args.weather_lag_days)]
    if args.bootstrap_from and (args.dry_run or not state_path.exists()):
        arguments += ["--from", args.bootstrap_from]
    if not args.dry_run:
        arguments += ["--state", str(state_path), "--output", str(report_path)]
    with nullcontext() if args.dry_run else state_lock(runtime / "watchdog.lock"):
        delivery = read_json(delivery_path) if delivery_path.exists() else None
        if delivery and delivery.get("model_id") != read_json(model_path)["model_id"]:
            raise ValueError("Notification state/model mismatch; keep prior runtime or choose a new directory")
        report = monitor.execute(monitor.parser().parse_args(arguments), now)
        if delivery is None:
            delivery = {"version": 1, "model_id": report["model_id"], "initialized": False,
                        "seen_events": [], "coverage": {}, "outbox": [], "sent_count": 0}
        queue_changes(delivery, report, now)
        pending = len(delivery["outbox"])
        if not args.dry_run:
            # Persist before sending. A crash after SMTP acceptance but before this
            # acknowledgement can duplicate a message; losing an alert is worse.
            atomic_json(delivery_path, delivery)
            try:
                for message in list(delivery["outbox"]):
                    accepted = (sender or send_admin)(message["subject"], message["body"])
                    if not accepted:
                        raise RuntimeError("Admin notification was not accepted; retained for retry")
                    delivery["outbox"].remove(message)
                    delivery["sent_count"] += 1
                    delivery["last_sent_at"] = now.isoformat()
                    atomic_json(delivery_path, delivery)
            finally:
                report["notifications_enabled"] = True
                report["delivery"] = {"pending": len(delivery["outbox"]), "sent_count": delivery["sent_count"],
                                      "last_sent_at": delivery.get("last_sent_at"), "checked_at": now.isoformat()}
                atomic_json(report_path, report)
        return {"model_id": report["model_id"], "notifications_enabled": not args.dry_run,
                "messages_sent": 0 if args.dry_run else pending, "messages_pending": len(delivery["outbox"]),
                "summary": report["summary"], "pattern": report["pattern"], "monitoring_gaps": report["monitoring_gaps"],
                "report_path": str(report_path) if not args.dry_run else None}


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        print(json.dumps(run(args), indent=2, allow_nan=False))
        return 0
    except Exception as error:
        print(json.dumps({"error": str(error), "notifications_enabled": not args.dry_run}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
