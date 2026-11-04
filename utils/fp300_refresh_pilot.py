"""Install an Aqara15-only FP300 environmental refresh pilot.

Preview: python -m utils.fp300_refresh_pilot
Install: python -m utils.fp300_refresh_pilot --install

Requires the existing user-local, presence-corrected FP300 definition. Split
it into mutually exclusive MAC matches: other FP300s retain their definition;
only Aqara15 gains 900-second temperature/humidity attribute reads when awake.
No timestamps, parsers, reporting bindings, or device settings are changed.

This utility never calls deCONZ or operates a service. Activation is separate:
deCONZ 2.33.2's /devices/<MAC>/ddf/reload reinitializes ALL devices of that
model, despite its device-specific URL. It also retains previously loaded raw
definitions in memory, which can shadow these files: on the deployed 2.33.2
gateway a separately approved service restart is needed for activation.
Backups contain exact pre-install bytes. To roll back the first installation,
restore the common backup and move the new pilot outside the .json scan before
another approved restart. Do not rerun the older presence
installer against the pilot file (it is a separate MAC-specific definition).
"""
from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid

from utils.fp300_ddf_patch import USER_DESTINATION, inline_scripts, patch_document

PILOT_MAC = "54:ef:44:10:01:59:b9:2e"
INTERVAL_SECONDS = 900
PILOT_DESTINATION = USER_DESTINATION.with_name("kazanfutes_aqara15_refresh.json")
PILOT_MATCH = f"R.item('attr/uniqueid').val == '{PILOT_MAC}'"
COMMON_MATCH = f"R.item('attr/uniqueid').val != '{PILOT_MAC}'"
PILOT_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, f"kazanfutes:fp300-refresh:{PILOT_MAC}"))
CLUSTERS = {"state/temperature": "0x0402", "state/humidity": "0x0405"}


def build_documents(common: dict) -> tuple[dict, dict]:
    """Preserve existing behavior and isolate refresh by physical IEEE address."""
    if patch_document(common) != common:
        raise ValueError("Install/review the existing presence fix before this pilot")
    if common.get("matchexpr") not in (None, COMMON_MATCH):
        raise ValueError("Unknown device match expression; review before replacing it")
    baseline = copy.deepcopy(common)
    baseline.pop("matchexpr", None)
    for name, cluster in CLUSTERS.items():
        matches = [(sub, item) for sub in baseline.get("subdevices", [])
                   for item in sub.get("items", []) if item.get("name") == name]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one {name} item")
        sub, item = matches[0]
        fingerprint = sub.get("fingerprint", {})
        if (fingerprint.get("endpoint") != "0x01"
                or cluster not in fingerprint.get("in", [])
                or item.get("awake") is not True):
            raise ValueError(f"Unexpected {name} endpoint/awake mapping")
        if "read" in item or "refresh.interval" in item:
            raise ValueError(f"Custom {name} refresh found; review before installing")
    ordinary = copy.deepcopy(baseline)
    ordinary["matchexpr"] = COMMON_MATCH
    pilot = copy.deepcopy(baseline)
    pilot["matchexpr"] = PILOT_MATCH
    pilot["uuid"] = PILOT_UUID
    for sub in pilot["subdevices"]:
        for item in sub["items"]:
            cluster = CLUSTERS.get(item.get("name"))
            if cluster:
                item["read"] = {"fn": "zcl:attr", "ep": 1, "cl": cluster, "at": "0x0000"}
                item["refresh.interval"] = INTERVAL_SECONDS
    return ordinary, pilot


def prepare(common_path: Path, pilot_path: Path) -> tuple[dict, dict]:
    """Validate both files before any write; never replace unknown overrides."""
    if common_path.resolve() == pilot_path.resolve() or common_path.parent.resolve() != pilot_path.parent.resolve():
        raise ValueError("Definitions must be distinct files in the same directory")
    if common_path.suffix != ".json" or pilot_path.suffix != ".json":
        raise ValueError("Definitions must have .json filenames")
    if common_path.is_symlink() or pilot_path.is_symlink():
        raise ValueError("Refusing to replace a symlink")
    original = json.loads(common_path.read_text(encoding="utf-8"))
    ordinary, pilot = build_documents(inline_scripts(original, common_path.parent))
    if pilot_path.exists() and json.loads(pilot_path.read_text(encoding="utf-8")) != pilot:
        raise ValueError("Existing pilot differs; review custom/upstream changes first")
    return ordinary, pilot


def atomic_write(path: Path, content: bytes) -> None:
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".fp300-refresh-",
                                         suffix=".tmp", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o644)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def install(common_path: Path, pilot_path: Path) -> tuple[bool, list[Path]]:
    ordinary, pilot = prepare(common_path, pilot_path)
    documents = [(pilot_path, pilot), (common_path, ordinary)]
    previous = {path: path.read_bytes() if path.exists() else None for path, _ in documents}
    changed = [(path, document) for path, document in documents
               if previous[path] is None or json.loads(previous[path]) != document]
    if not changed:
        return False, []
    stamp = datetime.now().strftime(".before-fp300-refresh-%Y%m%d-%H%M%S-%f.bak")
    backups = []
    for path, _ in changed:
        if previous[path] is not None:
            backup = path.with_name(path.name + stamp)
            shutil.copy2(path, backup)
            backups.append(backup)
    completed = []
    try:
        # Install the pilot before excluding it from the shared definition.
        for path, document in changed:
            atomic_write(path, (json.dumps(document, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
            completed.append(path)
    except Exception:
        for path in reversed(completed):
            if previous[path] is None:
                path.unlink()
            else:
                atomic_write(path, previous[path])
        raise
    return True, backups


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--common", type=Path, default=USER_DESTINATION)
    parser.add_argument("--pilot", type=Path, default=PILOT_DESTINATION)
    parser.add_argument("--install", action="store_true")
    args = parser.parse_args()
    prepare(args.common, args.pilot)
    print(f"Pilot: Aqara15 ({PILOT_MAC}); temperature/humidity reads every {INTERVAL_SECONDS}s when awake.")
    print("Other FP300s: unchanged measurement/presence behavior, including after restart.")
    if not args.install:
        print("Preview only; no files changed.")
        return 0
    changed, backups = install(args.common, args.pilot)
    print("Installed." if changed else "Already installed; no change.")
    for backup in backups:
        print(f"Exact original backup: {backup}")
    print(f"Definitions: {args.common} and {args.pilot}")
    print("No gateway/API/service operation performed. Activation on deCONZ 2.33.2 requires a separately approved restart.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
