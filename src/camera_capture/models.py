"""Camera configuration and results."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrameRecord:
    """A captured image paired with its sequence number and Unix timestamp."""

    sequence: int
    captured_at: float
    image: Any


@dataclass(frozen=True)
class CaptureConfig:
    """Immutable camera and output settings shared by CLI and library callers."""

    output_dir: Path
    duration_seconds: float = 5.0
    camera_index: int = 0
    fps: float = 30.0
    warmup_frames: int = 8
    overlay_timestamp: bool = False
    overlay_text: str = ""
    timestamp_in_filename: bool = True
    write_exif_timestamp: bool = True
    image_extension: str = "jpg"
    write_queue_size: int = 512
    frame_width: int | None = None
    frame_height: int | None = None
    fourcc: str | None = None
    auto_exposure: float | None = None
    exposure: float | None = None
    gain: float | None = None
    brightness: float | None = None
    contrast: float | None = None
    saturation: float | None = None
    hue: float | None = None
    gamma: float | None = None
    sharpness: float | None = None
    backlight: float | None = None
    auto_white_balance: bool | None = None
    white_balance_temperature: float | None = None
    white_balance_blue: float | None = None
    white_balance_red: float | None = None
    autofocus: bool | None = None
    focus: float | None = None
    zoom: float | None = None
    pan: float | None = None
    tilt: float | None = None
    roll: float | None = None
    buffer_size: int | None = None
    capture_backend: str = "opencv"
    gstreamer_source: str = "usb-v4l2"
    gstreamer_pipeline: str | None = None
    verbose: bool = False
    log_file: Path | None = None
