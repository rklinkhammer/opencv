"""Unit tests for explicit asynchronous writer lifecycle semantics."""

import logging
import tempfile
import time
import unittest
from pathlib import Path
from threading import Barrier, Event, Lock, Thread, Timer

from camera_capture.models import CaptureConfig, FrameRecord
from camera_capture.writer import AsyncFrameWriter, WriterState
from capture_shared.errors import CaptureError


class _Cv2Writer:
    def __init__(self, *, blocker: Event | None = None, entered: Event | None = None):
        self._blocker = blocker
        self._entered = entered

    def imwrite(self, path, _image):
        if self._entered is not None:
            self._entered.set()
        if self._blocker is not None:
            self._blocker.wait(timeout=2.0)
        Path(path).write_bytes(b"image")
        return True


class _FailingCv2Writer:
    def imwrite(self, _path, _image):
        return False


def _wait_for_state(writer: AsyncFrameWriter, expected: WriterState) -> None:
    deadline = time.perf_counter() + 1.0
    while writer.state is not expected and time.perf_counter() < deadline:
        time.sleep(0.001)
    if writer.state is not expected:
        raise AssertionError(f"writer did not reach state {expected.value}")


class WriterLifecycleTests(unittest.TestCase):
    def _writer(
        self,
        output_dir: Path,
        cv2_module,
        *,
        queue_size: int = 2,
        shutdown_monotonic=time.perf_counter,
    ):
        config = CaptureConfig(
            output_dir=output_dir,
            write_queue_size=queue_size,
            timestamp_in_filename=False,
            write_exif_timestamp=False,
        )
        return AsyncFrameWriter(
            config=config,
            cv2_module=cv2_module,
            extension="jpg",
            logger=logging.getLogger(f"writer-test-{id(cv2_module)}"),
            shutdown_monotonic=shutdown_monotonic,
        )

    def _submit(self, writer: AsyncFrameWriter, sequence: int) -> bool:
        return writer.submit(
            FrameRecord(sequence=sequence, captured_at=1_700_000_000.0, image="frame"),
            deadline=time.perf_counter() + 1.0,
            monotonic=time.perf_counter,
        )

    def test_normal_close_transitions_to_stopped_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(Path(tmp_dir), _Cv2Writer())
            self.assertIs(writer.state, WriterState.NEW)
            writer.start()
            self.assertIs(writer.state, WriterState.RUNNING)
            self.assertTrue(self._submit(writer, 0))

            first = writer.close()
            second = writer.close()

        self.assertEqual("normal", first.mode)
        self.assertFalse(first.thread_alive)
        self.assertEqual(first, second)
        self.assertIs(writer.state, WriterState.STOPPED)
        self.assertEqual(1, len(writer.saved_images))

    def test_close_uses_injected_shutdown_clock(self):
        clock_calls = 0

        def shutdown_monotonic():
            nonlocal clock_calls
            clock_calls += 1
            return time.perf_counter()

        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(
                Path(tmp_dir),
                _Cv2Writer(),
                shutdown_monotonic=shutdown_monotonic,
            )
            writer.start()
            writer.close()

        self.assertGreaterEqual(clock_calls, 2)

    def test_close_waits_for_space_when_queue_is_full(self):
        blocker = Event()
        entered = Event()
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(
                Path(tmp_dir),
                _Cv2Writer(blocker=blocker, entered=entered),
                queue_size=1,
            )
            writer.start()
            self.assertTrue(self._submit(writer, 0))
            self.assertTrue(entered.wait(timeout=1.0))
            self.assertTrue(self._submit(writer, 1))

            release = Timer(0.05, blocker.set)
            release.start()
            result = writer.close(timeout=1.0)
            release.join()

        self.assertEqual("normal", result.mode)
        self.assertEqual(2, len(writer.saved_images))
        self.assertIs(writer.state, WriterState.STOPPED)

    def test_writer_error_transitions_to_failed_and_propagates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(Path(tmp_dir), _FailingCv2Writer())
            writer.start()
            self.assertTrue(self._submit(writer, 0))
            _wait_for_state(writer, WriterState.FAILED)

            with self.assertRaisesRegex(CaptureError, "Failed to save image"):
                writer.raise_if_failed()
            result = writer.close()

        self.assertEqual("writer-error", result.mode)
        self.assertIs(writer.state, WriterState.FAILED)
        self.assertEqual([], writer.saved_images)

    def test_submit_after_failure_raises_original_writer_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(Path(tmp_dir), _FailingCv2Writer())
            writer.start()
            self.assertTrue(self._submit(writer, 0))
            _wait_for_state(writer, WriterState.FAILED)

            with self.assertRaisesRegex(CaptureError, "Failed to save image"):
                self._submit(writer, 1)
            writer.close()

    def test_submit_after_close_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(Path(tmp_dir), _Cv2Writer())
            writer.start()
            writer.close()

            with self.assertRaisesRegex(CaptureError, "state is stopped"):
                self._submit(writer, 0)

    def test_submit_before_start_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(Path(tmp_dir), _Cv2Writer())

            with self.assertRaisesRegex(CaptureError, "state is new"):
                self._submit(writer, 0)

    def test_close_timeout_leaves_stopping_state_and_can_be_retried(self):
        blocker = Event()
        entered = Event()
        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(Path(tmp_dir), _Cv2Writer(blocker=blocker, entered=entered))
            writer.start()
            self.assertTrue(self._submit(writer, 0))
            self.assertTrue(entered.wait(timeout=1.0))

            timed_out = writer.close(timeout=0.01)
            self.assertEqual("timeout", timed_out.mode)
            self.assertTrue(timed_out.thread_alive)
            self.assertIs(writer.state, WriterState.STOPPING)

            blocker.set()
            completed = writer.close(timeout=1.0)

        self.assertEqual("normal", completed.mode)
        self.assertFalse(completed.thread_alive)
        self.assertIs(writer.state, WriterState.STOPPED)

    def test_concurrent_submitters_and_close_finish_without_lost_accepted_frames(self):
        submitter_count = 4
        attempts_per_submitter = 25
        start_barrier = Barrier(submitter_count + 1)
        accepted_lock = Lock()
        accepted = 0
        errors = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            writer = self._writer(Path(tmp_dir), _Cv2Writer(), queue_size=4)
            writer.start()

            def submit_frames(worker_index: int) -> None:
                """Submit uniquely sequenced frames until shutdown rejects the worker."""

                nonlocal accepted
                start_barrier.wait()
                for offset in range(attempts_per_submitter):
                    sequence = worker_index * attempts_per_submitter + offset
                    try:
                        submitted = writer.submit(
                            FrameRecord(
                                sequence=sequence,
                                captured_at=1_700_000_000.0,
                                image="frame",
                            ),
                            deadline=time.perf_counter() + 1.0,
                            monotonic=time.perf_counter,
                        )
                    except CaptureError as exc:
                        errors.append(exc)
                        return
                    if submitted:
                        with accepted_lock:
                            accepted += 1

            threads = [
                Thread(target=submit_frames, args=(index,)) for index in range(submitter_count)
            ]
            for thread in threads:
                thread.start()

            start_barrier.wait()
            result = writer.close(timeout=2.0)
            for thread in threads:
                thread.join(timeout=1.0)

        self.assertEqual("normal", result.mode)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertTrue(all(isinstance(error, CaptureError) for error in errors))
        self.assertEqual(accepted, len(writer.saved_images))


if __name__ == "__main__":
    unittest.main()
