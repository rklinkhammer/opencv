"""Bounded asynchronous image writer.

Architecture:
- The writer owns a single bounded queue and one worker thread.
- Capture code submits `FrameRecord` instances and never writes files directly.
- The worker applies overlay/exif policies, commits via atomic output
    transactions, and records first failure for cooperative shutdown.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Lock, Thread
import time
from typing import Any, Callable

from capture_shared.output import OutputTransaction
from capture_shared.errors import WriterError
from capture_shared.timestamps import format_filename_timestamp, format_iso_timestamp

from .models import CaptureConfig, FrameRecord, WriterMetrics

_QUEUE_GET_TIMEOUT_SECONDS = 0.1
_QUEUE_PUT_TIMEOUT_SECONDS = 0.05


@dataclass(frozen=True)
class WriterCloseResult:
    """Outcome of writer shutdown coordination.

    Attributes:
    - mode: `normal`, `writer-error`, or `timeout`.
    - thread_alive: whether the worker thread was still running after join.
    - pending_items: queue items remaining after shutdown.
    """

    mode: str
    thread_alive: bool
    pending_items: int


class WriterState(Enum):
    """Explicit lifecycle states for the asynchronous frame writer."""

    NEW = "new"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


def write_exif_timestamp(image_path: Path, capture_time: float) -> None:
    """Insert timestamp EXIF fields without re-encoding JPEG pixels."""

    try:
        import piexif
    except ImportError as exc:
        raise WriterError("EXIF writing requires piexif") from exc

    from capture_shared.timestamps import capture_datetime

    dt = capture_datetime(capture_time)
    encoded_time = dt.strftime("%Y:%m:%d %H:%M:%S").encode("ascii")
    offset = dt.strftime("%z")
    encoded_offset = (f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else "+00:00").encode(
        "ascii"
    )
    exif = {
        "0th": {piexif.ImageIFD.DateTime: encoded_time},
        "Exif": {
            piexif.ExifIFD.DateTimeOriginal: encoded_time,
            piexif.ExifIFD.DateTimeDigitized: encoded_time,
            piexif.ExifIFD.OffsetTime: encoded_offset,
            piexif.ExifIFD.OffsetTimeOriginal: encoded_offset,
            piexif.ExifIFD.OffsetTimeDigitized: encoded_offset,
        },
    }
    piexif.insert(piexif.dump(exif), str(image_path))


class AsyncFrameWriter:
    """Own one writer thread, its bounded queue, and first failure."""

    def __init__(
        self,
        *,
        config: CaptureConfig,
        cv2_module: Any,
        extension: str,
        logger: logging.Logger,
        exif_writer: Callable[[Path, float], None] = write_exif_timestamp,
        shutdown_monotonic: Callable[[], float] = time.perf_counter,
    ) -> None:
        """Initialize queue, failure signaling, and writer-thread state."""

        self._config = config
        self._cv2 = cv2_module
        self._extension = extension
        self._logger = logger
        self._exif_writer = exif_writer
        self._shutdown_monotonic = shutdown_monotonic
        self._queue: Queue[FrameRecord | None] = Queue(config.write_queue_size)
        self._state_lock = Lock()
        self._submit_lock = Lock()
        self._close_lock = Lock()
        self._state = WriterState.NEW
        self._error: Exception | None = None
        self._stop_requested = False
        self._close_result: WriterCloseResult | None = None
        self._frames_submitted = 0
        self._frames_written = 0
        self._write_failures = 0
        self._queue_full_events = 0
        self.saved_images: list[Path] = []
        self._thread = Thread(target=self._run, name="camera-capture-writer", daemon=True)
        self._thread_started = False

    @property
    def state(self) -> WriterState:
        """Return a synchronized snapshot of the writer lifecycle state."""

        with self._state_lock:
            return self._state

    def start(self) -> None:
        """Transition from `NEW` to `RUNNING` and start the worker thread."""

        with self._state_lock:
            if self._state is not WriterState.NEW:
                raise WriterError(f"Writer cannot start while state is {self._state.value}")
            self._state = WriterState.RUNNING
            try:
                self._thread.start()
                self._thread_started = True
            except Exception as exc:
                error = WriterError(f"Unable to start writer thread: {exc}")
                self._error = error
                self._state = WriterState.FAILED
                raise error from exc

    def _set_error(self, error: Exception) -> None:
        """Record the first writer error and transition to failed state."""

        with self._state_lock:
            if self._error is None:
                self._error = error
                self._write_failures += 1
                self._state = WriterState.FAILED

    def raise_if_failed(self) -> None:
        """Raise the first writer failure if one has occurred."""

        with self._state_lock:
            error = self._error
        if error is not None:
            raise error

    def _ensure_accepting_locked(self) -> None:
        """Validate submission state while the caller holds the state lock."""

        if self._error is not None:
            raise self._error
        if self._state is not WriterState.RUNNING:
            raise WriterError(f"Writer cannot accept frames while state is {self._state.value}")

    def _mark_stopped(self) -> None:
        """Record normal worker termination without overwriting a failure."""

        with self._state_lock:
            if self._state is not WriterState.FAILED:
                self._state = WriterState.STOPPED

    def _save(self, frame: FrameRecord) -> Path:
        """Persist a single frame and return the committed output path."""

        image = frame.image
        if self._config.overlay_timestamp:
            timestamp = format_iso_timestamp(frame.captured_at)
            label = self._config.overlay_text.strip()
            text = f"{label} | {timestamp}" if label else timestamp
            image = self._cv2.putText(
                image,
                text,
                (10, 30),
                self._cv2.FONT_HERSHEY_SIMPLEX,
                0.7,
                (255, 255, 255),
                2,
                self._cv2.LINE_AA,
            )

        stem = f"frame_{frame.sequence:06d}"
        if self._config.timestamp_in_filename:
            stem += f"_{format_filename_timestamp(frame.captured_at)}"
        with OutputTransaction(self._config.output_dir, stem, self._extension) as output:
            if not self._cv2.imwrite(str(output.temporary), image):
                raise WriterError(f"Failed to save image: {output.destination}")
            if self._config.write_exif_timestamp and self._extension in {"jpg", "jpeg"}:
                self._exif_writer(output.temporary, frame.captured_at)
            return output.commit()

    def _run(self) -> None:
        """Consume queued frames until sentinel or unrecoverable write failure."""

        while True:
            try:
                frame = self._queue.get(timeout=_QUEUE_GET_TIMEOUT_SECONDS)
            except Empty:
                continue
            try:
                if frame is None:
                    self._mark_stopped()
                    return
                path = self._save(frame)
                self.saved_images.append(path)
                with self._state_lock:
                    self._frames_written += 1
                self._logger.info("Saved frame %d to %s", frame.sequence, path)
            except Exception as exc:
                self._set_error(exc)
                return
            finally:
                self._queue.task_done()

    def submit(
        self,
        frame: FrameRecord,
        *,
        deadline: float,
        monotonic: Callable[[], float],
    ) -> bool:
        """Submit a frame before deadline, respecting queue backpressure.

        Returns `True` when enqueued, `False` when deadline expires first.
        """

        if self._submit_once(frame, timeout=None):
            return True

        while monotonic() < deadline:
            if self._submit_once(frame, timeout=_QUEUE_PUT_TIMEOUT_SECONDS):
                return True
        return False

    def _submit_once(self, frame: FrameRecord, *, timeout: float | None) -> bool:
        """Attempt one ordered queue insertion without blocking the state lock."""

        with self._submit_lock:
            with self._state_lock:
                self._ensure_accepting_locked()
            try:
                if timeout is None:
                    self._queue.put_nowait(frame)
                else:
                    self._queue.put(frame, timeout=timeout)
            except Full:
                with self._state_lock:
                    self._queue_full_events += 1
                return False
            with self._state_lock:
                self._frames_submitted += 1
            return True

    @property
    def queue_full_events(self) -> int:
        """Return the number of bounded-queue backpressure events observed."""

        with self._state_lock:
            return self._queue_full_events

    def snapshot_metrics(self, close_result: WriterCloseResult) -> WriterMetrics:
        """Return immutable writer metrics associated with a close result."""

        with self._state_lock:
            return WriterMetrics(
                frames_submitted=self._frames_submitted,
                frames_written=self._frames_written,
                write_failures=self._write_failures,
                close_mode=close_result.mode,
                pending_items_at_close=close_result.pending_items,
            )

    def close(self, *, timeout: float = 5.0) -> WriterCloseResult:
        """Signal writer termination and return shutdown telemetry."""

        with self._close_lock:
            with self._submit_lock:
                with self._state_lock:
                    if self._close_result is not None:
                        return self._close_result
                    if self._state is WriterState.NEW:
                        self._state = WriterState.STOPPED
                        result = WriterCloseResult(
                            mode="normal", thread_alive=False, pending_items=self._queue.qsize()
                        )
                        self._close_result = result
                        return result
                    if self._state is WriterState.RUNNING:
                        self._state = WriterState.STOPPING
                    thread_started = self._thread_started

            deadline = self._shutdown_monotonic() + max(0.0, timeout)
            self._request_stop(deadline)
            if thread_started:
                self._thread.join(timeout=max(0.0, deadline - self._shutdown_monotonic()))
            alive = self._thread.is_alive()

            with self._state_lock:
                failed = self._error is not None
                if not alive and not failed:
                    self._state = WriterState.STOPPED
                mode = "writer-error" if failed else "timeout" if alive else "normal"
                result = WriterCloseResult(
                    mode=mode,
                    thread_alive=alive,
                    pending_items=self._queue.qsize(),
                )
                if not alive:
                    self._close_result = result
                return result

    def _request_stop(self, deadline: float) -> None:
        """Enqueue the stop sentinel, draining abandoned work after failure."""

        while self._thread.is_alive() and self._shutdown_monotonic() < deadline:
            with self._state_lock:
                if self._stop_requested:
                    return
                failed = self._error is not None

            try:
                self._queue.put(None, timeout=_QUEUE_PUT_TIMEOUT_SECONDS)
                with self._state_lock:
                    self._stop_requested = True
                return
            except Full:
                if failed:
                    while True:
                        try:
                            self._queue.get_nowait()
                            self._queue.task_done()
                        except Empty:
                            return
