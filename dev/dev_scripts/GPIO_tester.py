#!/usr/bin/env python3
"""
gpio_tester.py  –  quick sanity-check for the GPIO wrapper in utils/project.py

usage examples
  python3 gpio_tester.py --pin 17
  python3 gpio_tester.py --pin 17 --cycles 5 --interval 0.5
  python3 gpio_tester.py --pin 5 --input       # read-only

The script will:
1. set the chosen pin to OUTPUT and toggle HIGH / LOW `cycles` times
2. read the level back after every change to confirm wiring
3. optionally leave the pin as INPUT and print its steady state
"""

import argparse
import time
from utils.project import (
    set_pin_mode,
    set_pin_state,
    read_pin_state,
    release_pin,
    GPIO,                     # re-exported by the wrapper
)

def toggle_test(pin: int, cycles: int, interval: float) -> None:
    """Drive pin HIGH/LOW and verify loop-back through read_pin_state()."""
    set_pin_mode(pin, GPIO.OUT)

    for i in range(cycles):
        for level in (1, 0):
            set_pin_state(pin, level)
            time.sleep(interval)
            readback = read_pin_state(pin)
            status = "OK" if readback == level else "MISMATCH!"
            print(f"cycle {i+1}/{cycles}  set {level}  read {readback}  → {status}")
            time.sleep(interval)

def input_check(pin: int) -> None:
    """Leave the pin as INPUT (floating) and show the sensed level once."""
    set_pin_mode(pin, GPIO.IN, GPIO.PUD_OFF)
    level = read_pin_state(pin)
    print(f"pin {pin} now INPUT, immediate read = {level}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="GPIO wrapper sanity tester (uses utils.project)"
    )
    parser.add_argument("--pin", type=int, required=True, help="BCM pin number")
    parser.add_argument("--cycles", type=int, default=3, help="on/off pairs")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between toggles")
    parser.add_argument(
        "--input", action="store_true",
        help="after toggling, switch pin to INPUT and print final level"
    )
    args = parser.parse_args()

    try:
        toggle_test(args.pin, args.cycles, args.interval)
        if args.input:
            input_check(args.pin)
    finally:
        # always clean up so the pin is left safe
        release_pin(args.pin)
        print("pin released, test complete.")

if __name__ == "__main__":
    main()