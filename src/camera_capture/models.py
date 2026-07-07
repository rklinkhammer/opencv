"""Core data models shared across camera capture runtime and tooling.

Architecture:
- `CaptureConfig` defines the canonical runtime contract consumed by CLI,
    session management, and writer orchestration.
- `FrameRecord` carries immutable per-frame payloads between capture and writer
    stages.
- Probe/benchmark dataclasses capture measurement outputs used by reporting and
    command-line summaries.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class FrameRecord:
    """A captured frame with stable identity and wall-clock timestamp."""

    sequence: int
    captured_at: float
    image: Any


@dataclass(frozen=True)
class CaptureConfig:
    """Immutable camera runtime contract shared by CLIs and capture services.

    Fields cover timing, camera controls, output policy, writer capacity, backend
    selection, and optional logging. Canonical validation lives in `validators.py`.
    """

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
    capture_backend: str = "opencv"
    gstreamer_source: str = "usb-v4l2"
    gstreamer_pipeline: str | None = None
    log_file: Path | None = None


@dataclass(frozen=True)
class WriterMetrics:
    """Structured counters describing asynchronous writer activity."""

    frames_submitted: int
    frames_written: int
    write_failures: int
    close_mode: str
    pending_items_at_close: int


@dataclass(frozen=True)
class CaptureMetrics:
    """Structured counters describing one camera capture run."""

    frames_read: int
    frames_enqueued: int
    frames_saved: int
    read_failures: int
    warmup_requested: int
    warmup_completed: int
    queue_full_events: int
    elapsed_seconds: float


@dataclass(frozen=True)
class CaptureResult:
    """Durable image paths and metrics returned by the richer capture API."""

    images: tuple[Path, ...]
    capture_metrics: CaptureMetrics
    writer_metrics: WriterMetrics


@dataclass(frozen=True)
class ProbeResult:
    """Measured result for one probed camera mode candidate."""

    fourcc: str
    width: int
    height: int
    requested_fps: float
    measured_fps: float
    measured_frames: int
    reported_fps: float
