"""Write captured frames on a background thread."""

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
from capture_shared.errors import CaptureError
from capture_shared.timestamps import format_filename_timestamp, format_iso_timestamp

from .models import CaptureConfig, FrameRecord

_QUEUE_GET_TIMEOUT_SECONDS = 0.1
_QUEUE_PUT_TIMEOUT_SECONDS = 0.05


@dataclass(frozen=True)
class WriterCloseResult:
    """Observable state after a bounded writer shutdown attempt."""

    mode: str
    thread_alive: bool
    pending_items: int


class WriterState(Enum):
    """Lifecycle states used to reject unsafe writer operations."""

    NEW = "new"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"


def write_exif_timestamp(image_path: Path, capture_time: float) -> None:
    try:
        import piexif
    except ImportError as exc:
        raise CaptureError("EXIF writing requires piexif") from exc

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
    """Persist frames off the capture thread using a bounded queue."""

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
        self._config = config
        self._cv2 = cv2_module
        self._extension = extension
        self._logger = logger
        self._exif_writer = exif_writer
        self._shutdown_monotonic = shutdown_monotonic
        self._queue: Queue[FrameRecord | None] = Queue(config.write_queue_size)
        self._state_lock = Lock()
        self._submit_lock = Lock()
        self._state = WriterState.NEW
        self._error: Exception | None = None
        self._stop_requested = False
        self._close_result: WriterCloseResult | None = None
        self.saved_images: list[Path] = []
        self._thread = Thread(target=self._run, name="camera-capture-writer", daemon=True)
        self._thread_started = False

    @property
    def state(self) -> WriterState:
        with self._state_lock:
            return self._state

    def start(self) -> None:
        with self._state_lock:
            if self._state is not WriterState.NEW:
                raise CaptureError(f"Writer cannot start while state is {self._state.value}")
            self._state = WriterState.RUNNING
            try:
                self._thread.start()
                self._thread_started = True
            except Exception as exc:
                error = CaptureError(f"Unable to start writer thread: {exc}")
                self._error = error
                self._state = WriterState.FAILED
                raise error from exc

    def _set_error(self, error: Exception) -> None:
        with self._state_lock:
            if self._error is None:
                self._error = error
                self._state = WriterState.FAILED

    def raise_if_failed(self) -> None:
        with self._state_lock:
            error = self._error
        if error is not None:
            raise error

    def _save(self, frame: FrameRecord) -> Path:
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
                raise CaptureError(f"Failed to save image: {output.destination}")
            if self._config.write_exif_timestamp and self._extension in {"jpg", "jpeg"}:
                self._exif_writer(output.temporary, frame.captured_at)
            return output.commit()

    def _run(self) -> None:
        while True:
            try:
                frame = self._queue.get(timeout=_QUEUE_GET_TIMEOUT_SECONDS)
            except Empty:
                continue
            try:
                if frame is None:
                    with self._state_lock:
                        if self._state is not WriterState.FAILED:
                            self._state = WriterState.STOPPED
                    return
                path = self._save(frame)
                self.saved_images.append(path)
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
        if self._submit_once(frame, timeout=None):
            return True

        while monotonic() < deadline:
            if self._submit_once(frame, timeout=_QUEUE_PUT_TIMEOUT_SECONDS):
                return True
        return False

    def _submit_once(self, frame: FrameRecord, *, timeout: float | None) -> bool:
        with self._submit_lock:
            with self._state_lock:
                if self._error is not None:
                    raise self._error
                if self._state is not WriterState.RUNNING:
                    raise CaptureError(
                        f"Writer cannot accept frames while state is {self._state.value}"
                    )
            try:
                if timeout is None:
                    self._queue.put_nowait(frame)
                else:
                    self._queue.put(frame, timeout=timeout)
            except Full:
                return False
            return True

    def close(self, *, timeout: float = 5.0) -> WriterCloseResult:
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
