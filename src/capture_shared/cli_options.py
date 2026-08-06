"""Camera options shared by the standalone and unified commands."""

from __future__ import annotations

import argparse
from pathlib import Path

from camera_capture.models import CaptureConfig


def add_common_camera_args(parser: argparse.ArgumentParser) -> None:
    """Add camera runtime flags used by camera and parallel CLIs."""

    parser.add_argument(
        "-v",
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Report camera settings before and after configuration.",
    )
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
    parser.add_argument("--contrast", type=float, default=None, help="Optional contrast value.")
    parser.add_argument("--saturation", type=float, default=None, help="Optional saturation value.")
    parser.add_argument("--hue", type=float, default=None, help="Optional hue value.")
    parser.add_argument("--gamma", type=float, default=None, help="Optional gamma value.")
    parser.add_argument("--sharpness", type=float, default=None, help="Optional sharpness value.")
    parser.add_argument(
        "--backlight", type=float, default=None, help="Optional backlight compensation value."
    )
    parser.add_argument(
        "--auto-white-balance",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable automatic white balance.",
    )
    parser.add_argument(
        "--white-balance-temperature",
        type=float,
        default=None,
        help="Optional white balance color temperature.",
    )
    parser.add_argument(
        "--white-balance-blue",
        type=float,
        default=None,
        help="Optional blue-channel white balance value.",
    )
    parser.add_argument(
        "--white-balance-red",
        type=float,
        default=None,
        help="Optional red-channel white balance value.",
    )
    parser.add_argument(
        "--autofocus",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable or disable autofocus.",
    )
    parser.add_argument("--focus", type=float, default=None, help="Optional manual focus value.")
    parser.add_argument("--zoom", type=float, default=None, help="Optional zoom value.")
    parser.add_argument("--pan", type=float, default=None, help="Optional pan value.")
    parser.add_argument("--tilt", type=float, default=None, help="Optional tilt value.")
    parser.add_argument("--roll", type=float, default=None, help="Optional roll value.")
    parser.add_argument(
        "--buffer-size",
        type=int,
        default=None,
        help="Optional capture buffer size.",
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
    capture_backend: str | None = None,
    gstreamer_source: str | None = None,
    frame_width: int | None = None,
    frame_height: int | None = None,
) -> CaptureConfig:
    """Build a capture configuration, optionally overriding benchmark fields."""

    return CaptureConfig(
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
        frame_width=frame_width if frame_width is not None else args.width,
        frame_height=frame_height if frame_height is not None else args.height,
        fourcc=args.fourcc,
        auto_exposure=args.auto_exposure,
        exposure=args.exposure,
        gain=args.gain,
        brightness=args.brightness,
        contrast=args.contrast,
        saturation=args.saturation,
        hue=args.hue,
        gamma=args.gamma,
        sharpness=args.sharpness,
        backlight=args.backlight,
        auto_white_balance=args.auto_white_balance,
        white_balance_temperature=args.white_balance_temperature,
        white_balance_blue=args.white_balance_blue,
        white_balance_red=args.white_balance_red,
        autofocus=args.autofocus,
        focus=args.focus,
        zoom=args.zoom,
        pan=args.pan,
        tilt=args.tilt,
        roll=args.roll,
        buffer_size=args.buffer_size,
        capture_backend=capture_backend or args.capture_backend,
        gstreamer_source=gstreamer_source or args.gstreamer_source,
        gstreamer_pipeline=args.gstreamer_pipeline,
        verbose=args.verbose,
        log_file=log_file,
    )
