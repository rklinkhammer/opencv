"""Camera capture orchestration built from session, clock, and writer services.

Architecture:
- `CameraSession` owns backend open/configure/release semantics.
- `Clock` separates wall-time stamping from monotonic deadline control.
- `AsyncFrameWriter` decouples frame ingestion from disk IO and EXIF writes.
- This module coordinates those components into one linear capture lifecycle:
    prepare -> warmup -> enqueue -> close writer -> surface failures.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Callable
from uuid import uuid4

from capture_shared.clocks import Clock, SystemClock
from capture_shared.errors import WriterTimeoutError
from capture_shared.output import recover_stale_outputs

from . import backends
from .models import CaptureConfig, CaptureMetrics, CaptureResult, FrameRecord, WriterMetrics
from .pipeline import FrameTransform, IdentityFrameTransform
from .probe import probe_camera_modes as probe_camera_modes
from .session import CameraSession, CaptureHandle
from .validators import validate_capture_config
from .writer import AsyncFrameWriter, WriterCloseResult, write_exif_timestamp

_READ_RETRY_SECONDS = 0.01


def _create_logger(log_file: Path | None) -> logging.Logger:
    """Create a run-scoped logger that never propagates to the root logger.

    The capture pipeline uses a unique logger per invocation so concurrent runs
    do not share handlers or duplicate records.
    """

    logger = logging.getLogger(f"camera_capture.run.{uuid4().hex}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler: logging.Handler = logging.NullHandler()
    if log_file is not None:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def _close_logger(logger: logging.Logger) -> None:
    """Detach and close all handlers associated with a run logger."""

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _warmup(capture: CaptureHandle, frames: int, sleep: Callable[[float], None]) -> int:
    """Read and discard startup frames before normal capture begins.

    Returns the number of successful warmup frames observed within a bounded
    retry window.
    """

    successful = 0
    for _ in range(max(frames * 20, 20)):
        if successful >= frames:
            break
        ok, _ = capture.read()
        if ok:
            successful += 1
        else:
            sleep(_READ_RETRY_SECONDS)
    return successful


def _log_close(
    logger: logging.Logger,
    result: WriterCloseResult,
    enqueued: int,
    saved: int,
) -> None:
    """Emit end-of-run telemetry for queue drain and writer shutdown status."""

    logger.info("Capture completed: enqueued=%d saved_images=%d", enqueued, saved)
    logger.info(
        "Writer shutdown: mode=%s pending=%d alive=%s",
        result.mode,
        result.pending_items,
        result.thread_alive,
    )


def _log_metrics(
    logger: logging.Logger,
    capture_metrics: CaptureMetrics,
    writer_metrics: WriterMetrics,
) -> None:
    """Emit structured end-of-run counters without changing CLI presentation."""

    logger.info(
        "Capture metrics: read=%d enqueued=%d saved=%d read_failures=%d "
        "warmup=%d/%d queue_full=%d elapsed_s=%.6f",
        capture_metrics.frames_read,
        capture_metrics.frames_enqueued,
        capture_metrics.frames_saved,
        capture_metrics.read_failures,
        capture_metrics.warmup_completed,
        capture_metrics.warmup_requested,
        capture_metrics.queue_full_events,
        capture_metrics.elapsed_seconds,
    )
    logger.info(
        "Writer metrics: submitted=%d written=%d failures=%d close_mode=%s pending=%d",
        writer_metrics.frames_submitted,
        writer_metrics.frames_written,
        writer_metrics.write_failures,
        writer_metrics.close_mode,
        writer_metrics.pending_items_at_close,
    )


def capture_images(
    config: CaptureConfig,
    *,
    clock: Clock | None = None,
    sleep_provider: Callable[[float], None] = time.sleep,
    exif_writer: Callable[[Path, float], None] = write_exif_timestamp,
    cv2_module: object | None = None,
    frame_transform: FrameTransform | None = None,
) -> list[Path]:
    """Capture images for a fixed duration and return durable output paths."""

    result = capture_images_with_result(
        config,
        clock=clock,
        sleep_provider=sleep_provider,
        exif_writer=exif_writer,
        cv2_module=cv2_module,
        frame_transform=frame_transform,
    )
    return list(result.images)


def capture_images_with_result(
    config: CaptureConfig,
    *,
    clock: Clock | None = None,
    sleep_provider: Callable[[float], None] = time.sleep,
    exif_writer: Callable[[Path, float], None] = write_exif_timestamp,
    cv2_module: object | None = None,
    frame_transform: FrameTransform | None = None,
) -> CaptureResult:
    """Capture images and return durable paths with structured runtime metrics.

    Execution flow:
    1. Validate config and initialize runtime dependencies.
    2. Open/configure a camera session.
    3. Warm up camera reads to skip startup instability.
    4. Apply the injected frame transform and enqueue records until deadline.
    5. Close writer, surface writer/session failures, return committed files.
    """

    backend, extension = validate_capture_config(config)
    if cv2_module is None:
        import cv2 as cv2_module  # type: ignore[no-redef]

    active_clock = clock or SystemClock()
    active_transform = frame_transform if frame_transform is not None else IdentityFrameTransform()
    logger = _create_logger(config.log_file)
    writer: AsyncFrameWriter | None = None
    close_result: WriterCloseResult | None = None
    capture_metrics: CaptureMetrics | None = None
    writer_metrics: WriterMetrics | None = None
    enqueued = 0
    frames_read = 0
    read_failures = 0
    warmed = 0
    capture_started = 0.0
    last_loop_time = 0.0

    try:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        recover_stale_outputs(config.output_dir)
        logger.info("Starting capture: backend=%s duration=%.3fs", backend, config.duration_seconds)
        capture_backend = backends.create_capture_backend(backend)
        with CameraSession(config, cv2_module, capture_backend) as capture:
            writer = AsyncFrameWriter(
                config=config,
                cv2_module=cv2_module,
                extension=extension,
                logger=logger,
                exif_writer=exif_writer,
            )
            writer.start()
            warmed = _warmup(capture, config.warmup_frames, sleep_provider)
            if warmed < config.warmup_frames:
                logger.warning(
                    "Warmup partial: requested=%d actual=%d",
                    config.warmup_frames,
                    warmed,
                )

            capture_started = active_clock.monotonic()
            last_loop_time = capture_started
            end = capture_started + config.duration_seconds
            sequence = 0
            while True:
                elapsed_now = active_clock.monotonic()
                last_loop_time = elapsed_now
                if elapsed_now >= end:
                    break
                writer.raise_if_failed()
                ok, image = capture.read()
                if not ok:
                    read_failures += 1
                    sleep_provider(_READ_RETRY_SECONDS)
                    continue
                frames_read += 1
                captured_at = active_clock.wall_time()
                record = FrameRecord(sequence=sequence, captured_at=captured_at, image=image)
                record = active_transform.apply(record)
                if not writer.submit(record, deadline=end, monotonic=active_clock.monotonic):
                    break
                sequence += 1
                enqueued += 1
    finally:
        if writer is not None:
            close_result = writer.close()
            _log_close(logger, close_result, enqueued, len(writer.saved_images))
            capture_metrics = CaptureMetrics(
                frames_read=frames_read,
                frames_enqueued=enqueued,
                frames_saved=len(writer.saved_images),
                read_failures=read_failures,
                warmup_requested=config.warmup_frames,
                warmup_completed=warmed,
                queue_full_events=writer.queue_full_events,
                elapsed_seconds=max(0.0, last_loop_time - capture_started),
            )
            writer_metrics = writer.snapshot_metrics(close_result)
            _log_metrics(logger, capture_metrics, writer_metrics)
        _close_logger(logger)

    assert writer is not None and close_result is not None
    assert capture_metrics is not None and writer_metrics is not None
    writer.raise_if_failed()
    if close_result.mode == "timeout" or close_result.thread_alive:
        raise WriterTimeoutError("Writer thread did not terminate before the shutdown deadline")
    return CaptureResult(
        images=tuple(writer.saved_images),
        capture_metrics=capture_metrics,
        writer_metrics=writer_metrics,
    )
