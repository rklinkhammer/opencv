"""Camera mode probing utilities for selecting practical capture settings."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, cast

from capture_shared.clocks import Clock, SystemClock

from .backends import create_capture_backend
from .models import CaptureConfig, ProbeResult
from .session import CameraSession
from .validators import validate_capture_config


class CapturePropertyReader(Protocol):
    """OpenCV capture surface used only for querying reported properties."""

    def get(self, property_id: int) -> float:
        """Return the backend-reported value for an OpenCV property identifier."""

        ...


def probe_camera_modes(
    *,
    camera_index: int,
    duration_seconds: float = 5.0,
    cv2_module: object | None = None,
    clock: Clock | None = None,
) -> tuple[list[ProbeResult], ProbeResult | None]:
    """Probe common camera modes and report measured read FPS.

    Args:
        camera_index: Camera index passed to OpenCV VideoCapture.
        duration_seconds: Probe duration per candidate mode.
        cv2_module: Optional OpenCV-like module override for tests.

    Returns:
        Pair of (all_results, best_result).
    """
    base_config = CaptureConfig(
        output_dir=Path("."),
        duration_seconds=duration_seconds,
        camera_index=camera_index,
    )
    backend_name, _ = validate_capture_config(base_config)

    if cv2_module is None:
        import cv2 as cv2_module  # type: ignore[no-redef]
    active_clock = clock or SystemClock()

    candidates: list[tuple[str, int, int, float]] = [
        ("MJPG", 640, 480, 30.0),
        ("YUYV", 640, 480, 30.0),
        ("MJPG", 1280, 720, 30.0),
        ("YUYV", 1280, 720, 30.0),
        ("MJPG", 640, 480, 15.0),
        ("YUYV", 640, 480, 15.0),
    ]

    results: list[ProbeResult] = []
    for fourcc, width, height, requested_fps in candidates:
        config = CaptureConfig(
            output_dir=Path("."),
            duration_seconds=duration_seconds,
            camera_index=camera_index,
            fourcc=fourcc,
            frame_width=width,
            frame_height=height,
            fps=requested_fps,
        )
        capture_backend = create_capture_backend(backend_name)
        with CameraSession(config, cv2_module, capture_backend) as capture:
            start = active_clock.monotonic()
            end = start + duration_seconds
            frames = 0
            while active_clock.monotonic() < end:
                ok, _ = capture.read()
                if ok:
                    frames += 1

            elapsed = max(active_clock.monotonic() - start, 1e-9)
            measured_fps = frames / elapsed
            reported_fps = 0.0
            if hasattr(cv2_module, "CAP_PROP_FPS"):
                property_reader = cast(CapturePropertyReader, capture)
                reported_fps = float(property_reader.get(cv2_module.CAP_PROP_FPS))

            results.append(
                ProbeResult(
                    fourcc=fourcc,
                    width=width,
                    height=height,
                    requested_fps=requested_fps,
                    measured_fps=measured_fps,
                    measured_frames=frames,
                    reported_fps=reported_fps,
                )
            )

    best = max(results, key=lambda result: result.measured_fps) if results else None
    return results, best
