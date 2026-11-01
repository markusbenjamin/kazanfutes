"""Explicit retrospective whole-array experiment; never sends notifications.

Requires existing notebook history exports and existing Pi logs. Downloads
public hourly ERA5 radiation/temperature into memory. No cache or input writes.
Run --help for required paths and end-exclusive reference/evaluation dates.
This method was designed after inspection of the March 2026 event.
"""

import argparse
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "utils"))
from pv_performance import Policy
from pv_performance_io import atomic_json, load_samples
from pv_history_export import load_history_exports
from pv_array_weather import fetch_era5, replay


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--history-exports", type=Path, required=True)
    parser.add_argument("--logs", type=Path, required=True)
    parser.add_argument("--reference-from", required=True)
    parser.add_argument("--reference-until", required=True)
    parser.add_argument("--from", dest="start", required=True)
    parser.add_argument("--until", dest="end", required=True)
    parser.add_argument("--allow-legacy-timestamps", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        boundaries = [date.fromisoformat(d).isoformat() for d in
                      (args.reference_from, args.reference_until, args.start, args.end)]
        first, cutoff, start, end = boundaries
        site = Policy()
        if not first < cutoff <= start < end <= datetime.now(ZoneInfo(site.timezone)).date().isoformat():
            raise ValueError("Use completed days, with reference preceding evaluation")
        if args.output:
            destination = args.output.resolve()
            for root in (args.logs.resolve(), args.history_exports.resolve()):
                if destination == root or root in destination.parents:
                    raise ValueError("Output must be outside both input trees")
            if args.output.exists():
                raise ValueError("Output already exists; preserve earlier runs with a new path")
        reference, training_quality = load_history_exports(args.history_exports, first, cutoff, site)
        samples, evaluation_quality = load_samples(args.logs, start, end, site,
                                                    allow_legacy=args.allow_legacy_timestamps)
        weather, provenance = fetch_era5(first, (date.fromisoformat(end) - timedelta(days=1)).isoformat(), site)
        result = replay(reference, samples, weather, first, cutoff, start, end, site)
        result.update(weather_provenance=provenance, training_quality=training_quality,
                      evaluation_quality_logs=evaluation_quality)
        result["source_hashes"] = {name: hashlib.sha256((ROOT / "utils" / (name + ".py"))
                                                       .read_text(encoding="utf-8").encode()).hexdigest()
                                   for name in ("pv_performance", "pv_performance_io", "pv_array_weather")}
        if args.output:
            atomic_json(args.output, result)
        print(json.dumps(result, indent=2, allow_nan=False))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
