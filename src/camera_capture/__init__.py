"""@package camera_capture
Public package exports for camera capture, probing, and benchmarking.

Public API index:
- `CaptureConfig`, `CaptureResult`, `CaptureMetrics`, `WriterMetrics`
- `FrameRecord`, `ProbeResult`
- `FrameTransform`, `IdentityFrameTransform`
- `capture_images(config, ...)`, `capture_images_with_result(config, ...)`
- `probe_camera_modes(...)`
- `benchmark_capture_only(...)`

Execution notes:
- `capture_images` is the primary runtime entrypoint and coordinates camera
        session, timing, and asynchronous writer lifecycle.
- Probe and benchmark helpers are read-only/measurement-oriented and do not
        replace the main capture pipeline.
"""

from .benchmarks import benchmark_capture_only
from .capture import capture_images, capture_images_with_result
from .models import (
    CaptureConfig,
    CaptureMetrics,
    CaptureResult,
    FrameRecord,
    ProbeResult,
    WriterMetrics,
)
from .pipeline import FrameTransform, IdentityFrameTransform
from .probe import probe_camera_modes

__all__ = [
    "CaptureConfig",
    "CaptureMetrics",
    "CaptureResult",
    "FrameRecord",
    "FrameTransform",
    "IdentityFrameTransform",
    "ProbeResult",
    "WriterMetrics",
    "benchmark_capture_only",
    "capture_images",
    "capture_images_with_result",
    "probe_camera_modes",
]
