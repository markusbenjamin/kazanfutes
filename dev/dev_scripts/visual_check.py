"""Capture one timestamped JPEG from each configured visual-check webcam."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "logs" / "visual"

# Each control name must match the name reported by:
# fswebcam -d /dev/videoN --list-controls
#
# For example, a fixed-focus camera can use:
# "Focus, Automatic Continuous": "False",
# "Focus, Absolute": 100,
CAMERAS = (
    {
        "device": "/dev/video0",
        "save_name": "pressure",
        "resolution": "1920x1080",
        "delay_seconds": 2,
        "skip_frames": 30,
        "controls": {
            "Gain": 0,
            "Power Line Frequency": "50 Hz",
            "Auto Exposure": "Manual Mode",
            "Exposure Time, Absolute": 100,
        },
    },
    {
        "device": "/dev/video2",
        "save_name": "boiler_display",
        "resolution": "1920x1080",
        "delay_seconds": 2,
        "skip_frames": 30,
        "controls": {
            "Gain": 100,
            "Power Line Frequency": "50 Hz",
            "Auto Exposure": "Manual Mode",
            "Exposure Time, Absolute": 1000,
        },
    },
)


def capture_image(camera: dict, destination: Path) -> None:
    """Capture one image with the settings configured for this camera."""
    command = [
        "fswebcam",
        "-d",
        camera["device"],
    ]
    for control_name, value in camera["controls"].items():
        command.extend(["--set", f"{control_name}={value}"])
    command.extend(
        [
            "--delay",
            str(camera["delay_seconds"]),
            "--skip",
            str(camera["skip_frames"]),
            "-r",
            camera["resolution"],
            "--no-banner",
            str(destination),
        ]
    )
    subprocess.run(command, check=True)


def main() -> int:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
    captures = [
        (
            camera,
            OUTPUT_DIRECTORY / f"{timestamp}_{camera['save_name']}.jpg",
            OUTPUT_DIRECTORY / f".{timestamp}_{camera['save_name']}.tmp.jpg",
        )
        for camera in CAMERAS
    ]

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    try:
        for camera, _, temporary_image in captures:
            capture_image(camera, temporary_image)

        for _, image, temporary_image in captures:
            temporary_image.replace(image)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"Visual check failed: {error}", file=sys.stderr)
        return 1
    finally:
        for _, _, temporary_image in captures:
            temporary_image.unlink(missing_ok=True)

    for camera, image, _ in captures:
        print(f"Captured {camera['device']}: {image.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
