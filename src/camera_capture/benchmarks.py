"""Benchmark routines for capture throughput measurements."""

from __future__ import annotations

from typing import Callable
import time

from capture_shared.clocks import Clock, SystemClock

from .backends import create_capture_backend, open_camera
from .models import CaptureConfig
from .validators import validate_capture_config, validate_positive_duration

_WARMUP_RETRY_SECONDS = 0.01
_READ_RETRY_SECONDS = 0.001


def benchmark_capture_only(
    config: CaptureConfig,
    *,
    duration_seconds: float,
    clock: Clock | None = None,
    sleep_provider: Callable[[float], None] = time.sleep,
    cv2_module: object | None = None,
) -> tuple[int, float, float]:
    validate_positive_duration(duration_seconds)
    backend_name, _ = validate_capture_config(config)

    if cv2_module is None:
        import cv2 as cv2_module  # type: ignore[no-redef]

    frames = 0
    skipped_warmup_frames = 0
    warmup_attempt_limit = max(config.warmup_frames * 20, 20)

    active_clock = clock or SystemClock()

    capture_backend = create_capture_backend(backend_name)
    with open_camera(config, cv2_module, capture_backend) as capture:
        for _ in range(warmup_attempt_limit):
            if skipped_warmup_frames >= config.warmup_frames:
                break
            ok, _ = capture.read()
            if ok:
                skipped_warmup_frames += 1
            else:
                sleep_provider(_WARMUP_RETRY_SECONDS)

        start = active_clock.monotonic()
        end = start + duration_seconds
        while active_clock.monotonic() < end:
            ok, _ = capture.read()
            if ok:
                frames += 1
            else:
                sleep_provider(_READ_RETRY_SECONDS)

        elapsed = max(active_clock.monotonic() - start, 1e-9)
        return frames, elapsed, frames / elapsed
