#!/usr/bin/env python3
"""Linux camera smoke test for /dev/video* devices.

This script validates that a camera device exists and can return at least one frame.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys


def build_parser() -> argparse.ArgumentParser:
    """Create the Linux camera smoke-test argument parser."""

    parser = argparse.ArgumentParser(
        description="Smoke test a Linux camera by reading one frame using OpenCV."
    )
    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="OpenCV camera index to test (default: 0).",
    )
    parser.add_argument(
        "--require-device",
        action="store_true",
        help="Fail if the corresponding /dev/videoN node is missing.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Open one Linux camera, read a frame, and return a shell-friendly status."""

    parser = build_parser()
    args = parser.parse_args(argv)

    if not sys.platform.startswith("linux"):
        print("Smoke test skipped: this script is intended for Linux only.")
        return 0

    video_device = Path(f"/dev/video{args.camera_index}")
    if args.require_device and not video_device.exists():
        print(f"Smoke test failed: missing device node {video_device}")
        return 1

    try:
        import cv2
    except ImportError:
        print("Smoke test failed: opencv-python is not installed.")
        return 1

    capture = cv2.VideoCapture(args.camera_index)
    if not capture.isOpened():
        print(
            f"Smoke test failed: cannot open camera index {args.camera_index}. "
            "Check USB connection and permissions."
        )
        return 1

    ok, _frame = capture.read()
    capture.release()

    if not ok:
        print("Smoke test failed: camera opened but no frame was returned.")
        return 1

    print(f"Smoke test passed: camera index {args.camera_index} returned a frame.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
