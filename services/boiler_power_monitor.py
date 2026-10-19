"""Read and log boiler plug power; never control the relay output."""

from __future__ import annotations

import argparse
import os

from services.device_watchdog import CONFIG_RELATIVE_PATH, run
from utils.device_watchdog import read_json
from utils.project import get_project_root, JSONNodeAtURL, timestamp
from utils.boiler_power_formatter import boiler_power_snapshot


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = get_project_root()
    config = read_json(os.path.join(root, CONFIG_RELATIVE_PATH), {})
    result = run(config, dry_run=args.dry_run, boiler_only=True)
    if not args.dry_run:
        # Reuse the observation already collected above; no extra hardware query.
        JSONNodeAtURL(node_relative_path='system').write(
            boiler_power_snapshot(result['devices'], timestamp()), 'state/boiler_plugs'
        )
    for device in result["devices"]:
        facts = device["facts"]
        print(
            f"{device['name']}: output={facts.get('output_on')} "
            f"power_w={facts.get('measurements', {}).get('power_w')} "
            f"error={facts.get('collection_error')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
