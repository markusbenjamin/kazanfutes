"""Capture timestamped visual-check images from the pressure and boiler cameras."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "logs" / "visual"
DEFAULT_RESOLUTION = "1280x720"


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Capture one image from the pressure gauge camera and one from the "
            "boiler-display camera. Both files share a timestamp."
        )
    )
    parser.add_argument(
        "--pressure-device",
        required=True,
        help="V4L2 device for the pressure-gauge camera, for example /dev/video0.",
    )
    parser.add_argument(
        "--boiler-device",
        required=True,
        help="V4L2 device for the boiler-display camera, for example /dev/video2.",
    )
    parser.add_argument(
        "--resolution",
        default=DEFAULT_RESOLUTION,
        help=f"Capture resolution passed to fswebcam (default: {DEFAULT_RESOLUTION}).",
    )
    return parser.parse_args()


def capture_image(device: str, destination: Path, resolution: str) -> None:
    """Capture one JPEG from a specified V4L2 device using fswebcam."""
    subprocess.run(
        [
            "fswebcam",
            "-d",
            device,
            "-r",
            resolution,
            "--no-banner",
            str(destination),
        ],
        check=True,
    )


def main() -> int:
    arguments = parse_arguments()

    if arguments.pressure_device == arguments.boiler_device:
        print("The pressure and boiler cameras must use different video devices.", file=sys.stderr)
        return 2

    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
    pressure_image = OUTPUT_DIRECTORY / f"{timestamp}_pressure_gauge.jpg"
    boiler_image = OUTPUT_DIRECTORY / f"{timestamp}_boiler_displays.jpg"
    pressure_temporary_image = OUTPUT_DIRECTORY / f".{timestamp}_pressure_gauge.tmp.jpg"
    boiler_temporary_image = OUTPUT_DIRECTORY / f".{timestamp}_boiler_displays.tmp.jpg"

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    try:
        capture_image(arguments.pressure_device, pressure_temporary_image, arguments.resolution)
        capture_image(arguments.boiler_device, boiler_temporary_image, arguments.resolution)
        pressure_temporary_image.replace(pressure_image)
        boiler_temporary_image.replace(boiler_image)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"Visual check failed: {error}", file=sys.stderr)
        return 1
    finally:
        for temporary_image in (pressure_temporary_image, boiler_temporary_image):
            temporary_image.unlink(missing_ok=True)

    print(f"Pressure gauge image: {pressure_image.relative_to(PROJECT_ROOT)}")
    print(f"Boiler displays image: {boiler_image.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
