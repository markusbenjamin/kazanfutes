"""Extend the Aqara15 environmental-refresh pilot to the remaining FP300s.

Preview: python -m utils.fp300_refresh_rollout
Install: python -m utils.fp300_refresh_rollout --install

Only the shared FP300 definition's temperature/humidity readers change. The
existing MAC filters and Aqara15 pilot file remain untouched, so the pilot
keeps working and other device models are unaffected. Reads are due after
900 seconds, subject to device wakefulness; this is not a guaranteed reporting
interval. No measurement timestamps, presence behavior, bindings or physical
device settings are changed.

Requires the known, matching pair of presence-corrected pilot definitions.
Unknown customizations are refused. Installation makes an exact shared-file
backup and an atomic replacement. Restore that backup to roll back. Activation
on the deployed deCONZ 2.33.2 requires a separately approved service restart;
this utility performs no API or service operations itself.
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
from pathlib import Path
import shutil

from utils.fp300_refresh_pilot import (
    CLUSTERS, COMMON_MATCH, INTERVAL_SECONDS, PILOT_DESTINATION,
    USER_DESTINATION, atomic_write, build_documents,
)


def reader(cluster: str) -> dict:
    return {"fn": "zcl:attr", "ep": 1, "cl": cluster, "at": "0x0000"}


def rollout_document(common: dict, pilot: dict) -> dict:
    """Add only the validated pilot readers to the existing non-pilot match."""
    if common.get("matchexpr") != COMMON_MATCH:
        raise ValueError("Expected the existing MAC-scoped common definition; review deployment first")
    baseline = copy.deepcopy(common)
    for sub in baseline.get("subdevices", []):
        for item in sub.get("items", []):
            cluster = CLUSTERS.get(item.get("name"))
            if not cluster:
                continue
            if "read" in item or "refresh.interval" in item:
                if (item.get("read") != reader(cluster)
                        or item.get("refresh.interval") != INTERVAL_SECONDS):
                    raise ValueError("Custom environmental reader/interval; review before replacing it")
                # Remove only our known rollout to validate repeat installations.
                del item["read"]
                del item["refresh.interval"]
    # Reuse the pilot's strict model, presence, endpoint and item-count guards.
    ordinary, expected_pilot = build_documents(baseline)
    if pilot != expected_pilot:
        raise ValueError("Pilot/shared definitions differ; review custom/upstream changes first")
    result = ordinary
    for sub in result["subdevices"]:
        for item in sub["items"]:
            cluster = CLUSTERS.get(item.get("name"))
            if cluster:
                item["read"] = reader(cluster)
                item["refresh.interval"] = INTERVAL_SECONDS
    return result


def prepare(common_path: Path, pilot_path: Path) -> tuple[dict, dict]:
    if (common_path.resolve() == pilot_path.resolve()
            or common_path.parent.resolve() != pilot_path.parent.resolve()):
        raise ValueError("Definitions must be distinct files in the same directory")
    if common_path.suffix != ".json" or pilot_path.suffix != ".json":
        raise ValueError("Definitions must have .json filenames")
    if common_path.is_symlink() or pilot_path.is_symlink():
        raise ValueError("Refusing to install through a symlink")
    common = json.loads(common_path.read_text(encoding="utf-8"))
    pilot = json.loads(pilot_path.read_text(encoding="utf-8"))
    return common, rollout_document(common, pilot)


def install(common_path: Path, pilot_path: Path) -> tuple[bool, Path | None]:
    common, corrected = prepare(common_path, pilot_path)
    if common == corrected:
        return False, None
    stamp = datetime.now().strftime(".before-fp300-refresh-rollout-%Y%m%d-%H%M%S-%f.bak")
    backup = common_path.with_name(common_path.name + stamp)
    shutil.copy2(common_path, backup)
    atomic_write(common_path, (json.dumps(corrected, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    return True, backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common", type=Path, default=USER_DESTINATION)
    parser.add_argument("--pilot", type=Path, default=PILOT_DESTINATION)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    original, corrected = prepare(args.common, args.pilot)
    print("Scope: the remaining FP300s only; Aqara15's existing pilot file is unchanged.")
    print(f"Temperature/humidity: reads due after {INTERVAL_SECONDS}s, when the device permits them.")
    print("Presence, parsers, timestamps, MAC filters and other settings are unchanged.")
    if not args.install:
        print("Preview only: " + ("rollout needed" if original != corrected else "already installed"))
        return 0
    changed, backup = install(args.common, args.pilot)
    print("Installed." if changed else "Already installed; no change.")
    if backup:
        print(f"Exact original backup: {backup}")
    print("No API/service operation performed. Obtain approval immediately before restarting deCONZ to activate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
