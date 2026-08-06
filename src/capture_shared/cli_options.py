"""Camera options shared by the standalone and unified commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from camera_capture.models import CaptureConfig


def add_common_camera_args(parser: argparse.ArgumentParser) -> None:
    """Add camera runtime flags used by camera and parallel CLIs."""

    parser.add_argument(
        "--camera-index",
        type=int,
        default=0,
        help="OpenCV camera index (default: 0).",
    )
    parser.add_argument(
        "--capture-backend",
        type=str,
        choices=["opencv", "gstreamer"],
        default="opencv",
        help="Capture backend to use (default: opencv).",
    )
    parser.add_argument(
        "--gstreamer-pipeline",
        type=str,
        default=None,
        help=(
            "Optional explicit GStreamer pipeline string used when "
            "--capture-backend gstreamer; include an appsink named 'appsink'."
        ),
    )
    parser.add_argument(
        "--gstreamer-source",
        type=str,
        choices=["usb-v4l2", "jetson-csi"],
        default="usb-v4l2",
        help="GStreamer source preset when using gstreamer backend (default: usb-v4l2).",
    )
    parser.add_argument(
        "--fps",
        type=float,
        default=30.0,
        help="Requested camera frame rate (default: 30).",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Optional requested camera frame width.",
    )
    parser.add_argument(
        "--height",
        type=int,
        default=None,
        help="Optional requested camera frame height.",
    )
    parser.add_argument(
        "--fourcc",
        type=str,
        default=None,
        help="Optional FOURCC pixel format (for example: MJPG, YUYV).",
    )
    parser.add_argument(
        "--auto-exposure",
        type=float,
        default=None,
        help="Optional camera auto-exposure value.",
    )
    parser.add_argument(
        "--exposure",
        type=float,
        default=None,
        help="Optional manual exposure value.",
    )
    parser.add_argument(
        "--gain",
        type=float,
        default=None,
        help="Optional camera gain value.",
    )
    parser.add_argument(
        "--brightness",
        type=float,
        default=None,
        help="Optional camera brightness value.",
    )
    parser.add_argument(
        "--warmup-frames",
        type=int,
        default=8,
        help="Number of startup frames to skip before saving (default: 8).",
    )
    parser.add_argument(
        "--overlay-timestamp",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Draw timestamp text onto each saved frame.",
    )
    parser.add_argument(
        "--overlay-text",
        type=str,
        default="",
        help="Optional user text prefix for timestamp overlay.",
    )
    parser.add_argument(
        "--timestamp-in-filename",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Include capture timestamp in output filename.",
    )
    parser.add_argument(
        "--write-exif-timestamp",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write capture timestamp into JPEG EXIF metadata.",
    )
    parser.add_argument(
        "--image-type",
        type=str,
        choices=["jpg", "jpeg", "png", "bmp"],
        default="jpg",
        help="Output image type/extension (default: jpg).",
    )
    parser.add_argument(
        "--write-queue-size",
        type=int,
        default=512,
        help="Frame queue size for asynchronous image writing (default: 512).",
    )


def build_capture_config(
    *,
    args: argparse.Namespace,
    output_dir: Path,
    duration_seconds: float,
    log_file: Path | None,
    **overrides: object,
) -> CaptureConfig:
    """Build CaptureConfig from args with optional overrides.

    Return a fully typed immutable capture configuration.
    """

    values: dict[str, object] = dict(
        output_dir=output_dir,
        duration_seconds=duration_seconds,
        camera_index=args.camera_index,
        fps=args.fps,
        warmup_frames=args.warmup_frames,
        overlay_timestamp=args.overlay_timestamp,
        overlay_text=args.overlay_text,
        timestamp_in_filename=args.timestamp_in_filename,
        write_exif_timestamp=args.write_exif_timestamp,
        image_extension=args.image_type,
        write_queue_size=args.write_queue_size,
        frame_width=args.width,
        frame_height=args.height,
        fourcc=args.fourcc,
        auto_exposure=args.auto_exposure,
        exposure=args.exposure,
        gain=args.gain,
        brightness=args.brightness,
        capture_backend=args.capture_backend,
        gstreamer_source=args.gstreamer_source,
        gstreamer_pipeline=args.gstreamer_pipeline,
        log_file=log_file,
    )
    values.update(overrides)
    return CaptureConfig(**values)  # type: ignore[arg-type]
