#!/usr/bin/env python3
"""Independent fail-safe that forces the boiler relay OFF on a stale heartbeat.

This file is intentionally standalone: when installed to /usr/local/sbin it does
not import the USB-hosted repository, its virtualenv, Firebase, Deconz, or Git.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time


def _heartbeat_epoch(path: str) -> float:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    epoch = float(payload["epoch"])
    if epoch <= 0:
        raise ValueError("heartbeat epoch is not positive")
    return epoch


def _sync_gpio_state(path: str, pin: int) -> None:
    """Update project.py's GPIO shadow state under the same advisory lock."""
    import fcntl

    lock_path = f"{path}.lock"
    os.makedirs(os.path.dirname(path), exist_ok=True)
    deadline = time.monotonic() + 5.0
    with open(lock_path, "a+", encoding="utf-8") as lock_handle:
        while True:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"GPIO state lock remained busy: {lock_path}")
                time.sleep(0.1)

        try:
            with open(path, "r", encoding="utf-8") as state_handle:
                state = json.load(state_handle)
            if not isinstance(state, dict):
                raise ValueError("GPIO state is not a JSON object")
            state[str(pin)] = {"mode": "OUT", "pud": "OFF", "state": "LOW"}
            temporary_path: str | None = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    encoding="utf-8",
                    dir=os.path.dirname(path),
                    prefix=".GPIO_state.watchdog.",
                    suffix=".tmp",
                    delete=False,
                ) as temporary:
                    temporary_path = temporary.name
                    json.dump(state, temporary, indent=4)
                    temporary.write("\n")
                    temporary.flush()
                    os.fsync(temporary.fileno())
                os.replace(temporary_path, path)
                temporary_path = None
            finally:
                if temporary_path and os.path.exists(temporary_path):
                    os.remove(temporary_path)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)


def _force_boiler_off(pin: int, gpio_state_path: str) -> bool:
    import RPi.GPIO as GPIO

    # Force the physical output first even if the repository or its state file
    # is unavailable.  Then synchronize the shadow state and reassert LOW so a
    # later project.py read cannot restore a stale HIGH value.
    GPIO.setwarnings(False)
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(pin, GPIO.OUT)
    GPIO.output(pin, GPIO.LOW)
    _sync_gpio_state(gpio_state_path, pin)
    GPIO.output(pin, GPIO.LOW)
    return GPIO.input(pin) == GPIO.LOW


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--heartbeat-path",
        default="/run/kazanfutes/heating_control_v2.heartbeat",
    )
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--gpio-pin", type=int, default=6)
    parser.add_argument(
        "--gpio-state-path",
        default="/media/pi/program_stick/kazanfutes/system/GPIO_state.json",
    )
    args = parser.parse_args()

    try:
        heartbeat_epoch = _heartbeat_epoch(args.heartbeat_path)
        age = time.time() - heartbeat_epoch
        if -5.0 <= age <= args.timeout_seconds:
            print(f"Heating V2 heartbeat healthy: {age:.1f} seconds old.")
            return 0
        reason = f"heartbeat is {age:.1f} seconds old"
    except Exception as error:
        reason = f"heartbeat unavailable or invalid: {error}"

    try:
        success = _force_boiler_off(args.gpio_pin, args.gpio_state_path)
        if not success:
            raise RuntimeError("GPIO read-back did not confirm LOW")
        print(f"Heating V2 watchdog forced boiler GPIO {args.gpio_pin} OFF; {reason}.")
        return 0
    except Exception as error:
        print(
            f"CRITICAL: Heating V2 watchdog could not force boiler GPIO {args.gpio_pin} OFF; "
            f"{reason}; GPIO error: {error}.",
            file=sys.stderr,
        )
        return 3


if __name__ == "__main__":
    sys.exit(main())
