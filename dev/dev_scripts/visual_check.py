"""Capture one timestamped JPEG from each connected visual-check webcam."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIRECTORY = PROJECT_ROOT / "data" / "logs" / "visual"
CAMERA_DEVICES = ("/dev/video0", "/dev/video2")
RESOLUTION = "1280x720"
PRE_CAPTURE_DELAY_SECONDS = 2
SKIPPED_FRAMES = 30
EXPOSURE_TIME_ABSOLUTE = 100
GAIN = 0


def capture_image(device: str, destination: Path) -> None:
    """Capture one focused, deliberately underexposed V4L2 image using fswebcam."""
    subprocess.run(
        [
            "fswebcam",
            "-d",
            device,
            "--set",
            f"Gain={GAIN}",
            "--set",
            "Power Line Frequency=50 Hz",
            "--set",
            "Auto Exposure=Manual Mode",
            "--set",
            f"Exposure Time, Absolute={EXPOSURE_TIME_ABSOLUTE}",
            "--delay",
            str(PRE_CAPTURE_DELAY_SECONDS),
            "--skip",
            str(SKIPPED_FRAMES),
            "-r",
            RESOLUTION,
            "--no-banner",
            str(destination),
        ],
        check=True,
    )


def main() -> int:
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d_%H-%M-%S_%f")[:-3]
    captures = [
        (
            device,
            OUTPUT_DIRECTORY / f"{timestamp}_{Path(device).name}.jpg",
            OUTPUT_DIRECTORY / f".{timestamp}_{Path(device).name}.tmp.jpg",
        )
        for device in CAMERA_DEVICES
    ]

    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    try:
        for device, _, temporary_image in captures:
            capture_image(device, temporary_image)

        for _, image, temporary_image in captures:
            temporary_image.replace(image)
    except (FileNotFoundError, subprocess.CalledProcessError) as error:
        print(f"Visual check failed: {error}", file=sys.stderr)
        return 1
    finally:
        for _, _, temporary_image in captures:
            temporary_image.unlink(missing_ok=True)

    for device, image, _ in captures:
        print(f"Captured {device}: {image.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
