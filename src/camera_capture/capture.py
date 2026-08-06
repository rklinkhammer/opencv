"""Camera capture loop."""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Callable
from uuid import uuid4

from capture_shared.clocks import Clock, SystemClock
from capture_shared.errors import CaptureError
from capture_shared.output import recover_stale_outputs

from . import backends
from .backends import CaptureHandle, open_camera
from .models import CaptureConfig, FrameRecord
from .validators import validate_capture_config
from .writer import AsyncFrameWriter, WriterCloseResult, write_exif_timestamp

_READ_RETRY_SECONDS = 0.01
FrameTransform = Callable[[FrameRecord], FrameRecord]


def _create_logger(log_file: Path | None) -> logging.Logger:
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
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()


def _warmup(capture: CaptureHandle, frames: int, sleep: Callable[[float], None]) -> int:
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
    close: WriterCloseResult,
    enqueued: int,
    saved: int,
) -> None:
    logger.info("Capture completed: enqueued=%d saved_images=%d", enqueued, saved)
    logger.info(
        "Writer shutdown: mode=%s pending=%d alive=%s",
        close.mode,
        close.pending_items,
        close.thread_alive,
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
    """Capture frames for the configured duration and return committed image paths."""
    backend, extension = validate_capture_config(config)
    if cv2_module is None:
        import cv2 as cv2_module  # type: ignore[no-redef]

    active_clock = clock or SystemClock()
    logger = _create_logger(config.log_file)
    writer: AsyncFrameWriter | None = None
    close_result: WriterCloseResult | None = None
    enqueued = 0

    try:
        config.output_dir.mkdir(parents=True, exist_ok=True)
        recover_stale_outputs(config.output_dir)
        logger.info("Starting capture: backend=%s duration=%.3fs", backend, config.duration_seconds)
        capture_backend = backends.create_capture_backend(backend)
        reporter = print if config.verbose else None
        with open_camera(config, cv2_module, capture_backend, reporter) as capture:
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

            end = active_clock.monotonic() + config.duration_seconds
            sequence = 0
            while True:
                if active_clock.monotonic() >= end:
                    break
                writer.raise_if_failed()
                ok, image = capture.read()
                if not ok:
                    sleep_provider(_READ_RETRY_SECONDS)
                    continue
                captured_at = active_clock.wall_time()
                record = FrameRecord(sequence=sequence, captured_at=captured_at, image=image)
                if frame_transform is not None:
                    record = frame_transform(record)
                if not writer.submit(record, deadline=end, monotonic=active_clock.monotonic):
                    break
                sequence += 1
                enqueued += 1
    finally:
        if writer is not None:
            close_result = writer.close()
            _log_close(logger, close_result, enqueued, len(writer.saved_images))
        _close_logger(logger)

    assert writer is not None and close_result is not None
    writer.raise_if_failed()
    if close_result.mode == "timeout" or close_result.thread_alive:
        raise CaptureError("Writer thread did not terminate before the shutdown deadline")
    return list(writer.saved_images)
