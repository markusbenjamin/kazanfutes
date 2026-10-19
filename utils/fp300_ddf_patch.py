"""Install a guarded, user-local fix for deCONZ's FP300 presence parser.

Developed against xiaomi_fp300_presence_multi_sensor.json. Combined/mmwave
mode must use the device's authoritative presence attribute (0x0142), not OR
its previous combined value with PIR events (0x014D). PIR-only mode continues
to use PIR. An hourly/wake-time read also repairs previously cached latches.

Preview: python -m utils.fp300_ddf_patch
Install: python -m utils.fp300_ddf_patch --install
Activation may require a separately approved deCONZ restart. This utility
never operates the service, changes sensor settings, or edits the database.
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

MODEL = "lumi.sensor_occupy.agl8"
FILENAME = "xiaomi_fp300_presence_multi_sensor.json"
SYSTEM_SOURCE = Path("/usr/share/deCONZ/devices/xiaomi") / FILENAME
USER_DESTINATION = Path.home() / ".local/share/dresden-elektronik/deCONZ/devices/xiaomi" / FILENAME

OLD_EVAL = (
    "if (R.item('config/devicemode').val == 'pir' && Attr.id == '0x014D') { "
    "Item.val = Number(R.item('state/presenceevent').val); } "
    "else if (R.item('config/devicemode').val == 'combined' && Attr.id == '0x014D') { "
    "Item.val = Item.val || Attr.val; } "
    "else if (R.item('config/devicemode').val == 'combined' && Attr.id == '0x0142') { "
    "Item.val = Number(R.item('state/presenceevent').val) || Attr.val; } "
    "else { Item.val = Attr.val; }"
)
PRESENCE_EVAL = (
    "var pirOnly = R.item('config/devicemode').val == 'pir'; "
    "if (((pirOnly && Attr.id == '0x014D') || (!pirOnly && Attr.id == '0x0142')) "
    "&& (Attr.val == 0 || Attr.val == 1)) { Item.val = Attr.val == 1; }"
)
PRESENCE_READ = {
    "cl": "0xFCC0", "cmd": "0x00", "ep": 1,
    "eval": "R.item('config/devicemode').val == 'pir' ? '4D01' : '4201'",
    "fc": "0x04", "fn": "zcl:cmd", "mf": "0x115F",
}


def patch_document(document: dict) -> dict:
    """Change only the known FP300 presence parser and its state read."""
    if document.get("modelid") != MODEL:
        raise ValueError("Refusing to modify a DDF for another model")
    result = copy.deepcopy(document)
    items = [item for sub in result.get("subdevices", [])
             for item in sub.get("items", []) if item.get("name") == "state/presence"]
    if len(items) != 1:
        raise ValueError("Expected exactly one FP300 state/presence item")
    item = items[0]
    parser = item.get("parse", {})
    normalize = lambda value: " ".join(value.split())
    if normalize(parser.get("eval", "")) not in {normalize(OLD_EVAL), normalize(PRESENCE_EVAL)}:
        raise ValueError("Unrecognized presence parser; review upstream/custom changes first")
    if (parser.get("fn") != "zcl:attr" or parser.get("cl") != "0xFCC0"
            or parser.get("mf") != "0x115F" or parser.get("ep") != 1
            or set(parser.get("at", [])) != {"0x0142", "0x014D"}):
        raise ValueError("Unexpected presence attribute mapping; refusing to overwrite it")
    if item.get("read") not in ({"fn": "none"}, PRESENCE_READ):
        raise ValueError("Custom presence reader found; review before replacing it")
    if item.get("refresh.interval") != 3600:
        raise ValueError("Unexpected refresh interval; review before installing")
    parser["eval"] = PRESENCE_EVAL
    item["read"] = copy.deepcopy(PRESENCE_READ)
    return result


def install(source: Path, destination: Path) -> tuple[bool, Path | None]:
    """Preserve an existing override, then atomically install the corrected DDF."""
    if source.resolve() == destination.resolve():
        raise ValueError("Source must not be the installation destination")
    if destination.is_symlink():
        raise ValueError("Refusing to replace a symlink")
    original_path = destination if destination.exists() else source
    original = json.loads(original_path.read_text(encoding="utf-8"))
    corrected = patch_document(original)
    if corrected == original:
        return False, None
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Back up the exact source bytes, including any existing user customizations.
    backup = destination.with_name(destination.name + datetime.now().strftime(".before-fp300-fix-%Y%m%d-%H%M%S-%f.bak"))
    shutil.copy2(original_path, backup)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
                                         prefix=".fp300-", suffix=".tmp", delete=False) as handle:
            temporary_path = Path(handle.name)
            json.dump(corrected, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o644)
        os.replace(temporary_path, destination)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return True, backup


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SYSTEM_SOURCE)
    parser.add_argument("--destination", type=Path, default=USER_DESTINATION)
    parser.add_argument("--install", action="store_true", help="Install the override; default is read-only preview")
    args = parser.parse_args()
    candidate = args.destination if args.destination.exists() else args.source
    original = json.loads(candidate.read_text(encoding="utf-8"))
    corrected = patch_document(original)
    print(f"Source: {candidate}")
    print(f"Destination: {args.destination}")
    print("Scope: all FP300 units using this DDF; other device models are untouched.")
    print("Presence: 0x0142 in combined/mmwave mode; 0x014D in PIR-only mode.")
    print("Refresh: read the authoritative presence attribute when the device wakes/is due.")
    if not args.install:
        print("Preview only: " + ("fix needed" if corrected != original else "already corrected"))
        return 0
    changed, backup = install(args.source, args.destination)
    print("Installed." if changed else "Already installed; no change.")
    if backup:
        print(f"Original backup: {backup}")
    print("No service restart or sensor operation was performed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
