#!/usr/bin/env python3
"""
Sequential smart-light blink tester for the kazanfutes deCONZ installation.

Each real bulb is toggled once, then restored to its original on/off state.
Brightness, color temperature, XY color, effects, etc. are left untouched.

Known non-bulb deCONZ light resources (such as SONOFF DONGLE-E_R routers) are
skipped.

Run from the repository root, for example:
    python dev/dev_scripts/lights_blink_tester.py

Optional:
    python dev/dev_scripts/lights_blink_tester.py --duration 1.0 --gap 1.0
"""

from __future__ import annotations

import argparse
import time
from typing import Any

from utils.project import *  # noqa: F401,F403 - project light/deCONZ helpers


settings["log"] = False
settings["verbosity"] = False


EXCLUDED_MODELS = {"DONGLE-E_R"}
EXCLUDED_NAME_PREFIXES = ("router_",)


def _is_real_light(raw: dict[str, Any]) -> tuple[bool, str | None]:
    """Reject deCONZ light resources that are known not to be physical bulbs."""
    model = str(raw.get("modelid") or "").strip()
    name = str(raw.get("name") or "").strip()

    if model.upper() in EXCLUDED_MODELS:
        return False, f"excluded model {model}"

    if name.lower().startswith(EXCLUDED_NAME_PREFIXES):
        return False, f"excluded name {name}"

    return True, None


def _command_light(light_id: Any, name: str, on: bool) -> None:
    """Set only the on/off field and treat an explicit False return as failure."""
    result = set_light_state(light_id, name, {"on": on})
    if result is False:
        raise RuntimeError("set_light_state() returned False")


def blink_light(light_id: Any, raw: dict[str, Any], duration: float) -> dict[str, Any]:
    """Toggle one light, wait, and restore its original on/off state."""
    name = str(raw.get("name") or f"light_{light_id}")
    state = raw.get("state") or {}
    original_on = state.get("on")

    result = {
        "id": str(light_id),
        "name": name,
        "model": raw.get("modelid"),
        "manufacturer": raw.get("manufacturername"),
        "reachable": state.get("reachable"),
        "original_on": original_on,
        "status": "pending",
        "error": None,
        "restore_error": None,
    }

    if not isinstance(original_on, bool):
        result["status"] = "skipped"
        result["error"] = "light has no boolean state['on'] value"
        return result

    test_on = not original_on
    changed = False

    try:
        _command_light(light_id, name, test_on)
        changed = True
        time.sleep(duration)
        result["status"] = "blink_commanded"
    except Exception as exc:
        result["status"] = "failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if changed:
            try:
                _command_light(light_id, name, original_on)
            except Exception as exc:
                result["status"] = "restore_failed"
                result["restore_error"] = f"{type(exc).__name__}: {exc}"

    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Blink each real deCONZ smart bulb once, sequentially."
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0.8,
        help="Seconds to hold the temporary opposite state (default: 0.8).",
    )
    parser.add_argument(
        "--gap",
        type=float,
        default=0.7,
        help="Seconds to wait between lights (default: 0.7).",
    )
    args = parser.parse_args()

    if args.duration <= 0:
        parser.error("--duration must be greater than 0")
    if args.gap < 0:
        parser.error("--gap must be 0 or greater")

    candidates = []
    excluded = []

    for light_id, info in read_lights():
        raw = info.raw
        include, reason = _is_real_light(raw)
        if include:
            candidates.append((light_id, raw))
        else:
            excluded.append(
                {
                    "id": str(light_id),
                    "name": raw.get("name"),
                    "model": raw.get("modelid"),
                    "reason": reason,
                }
            )

    candidates.sort(key=lambda item: str(item[1].get("name") or item[0]).lower())

    print(f"Found {len(candidates)} bulb candidate(s).")
    if excluded:
        print(f"Excluded {len(excluded)} non-bulb deCONZ light resource(s):")
        for item in excluded:
            print(
                f"  - {item['name']} (id={item['id']}, model={item['model']}): "
                f"{item['reason']}"
            )

    if not candidates:
        print("No bulbs to test.")
        return 1

    print()
    results = []

    for index, (light_id, raw) in enumerate(candidates, start=1):
        name = str(raw.get("name") or f"light_{light_id}")
        model = raw.get("modelid")
        reachable = (raw.get("state") or {}).get("reachable")
        original_on = (raw.get("state") or {}).get("on")

        print(
            f"[{index}/{len(candidates)}] BLINK {name} "
            f"(id={light_id}, model={model}, reachable={reachable}, on={original_on})"
        )

        result = blink_light(light_id, raw, args.duration)
        results.append(result)

        if result["status"] == "blink_commanded":
            print("  OK: toggle sent and original state restored.")
        elif result["status"] == "restore_failed":
            print(
                "  WARNING: blink was sent but restoring the original state failed: "
                f"{result['restore_error']}"
            )
        elif result["status"] == "skipped":
            print(f"  SKIP: {result['error']}")
        else:
            print(f"  FAIL: {result['error']}")

        if index < len(candidates):
            time.sleep(args.gap)

    ok = sum(result["status"] == "blink_commanded" for result in results)
    failed = sum(result["status"] in {"failed", "restore_failed"} for result in results)
    skipped = sum(result["status"] == "skipped" for result in results)

    print()
    print(
        f"RESULT: {ok} blinked/restored, {failed} failed, "
        f"{skipped} skipped, {len(excluded)} non-bulb resources excluded."
    )
    print(
        "Note: this confirms command/API success only. Visual confirmation is still "
        "needed to prove that each named physical lamp actually blinked."
    )

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
