"""Integration tests for the lightweight frame transformation seam."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from camera_capture.capture import capture_images, capture_images_with_result
from camera_capture.models import CaptureConfig, FrameRecord


class _Clock:
    def __init__(self):
        self._monotonic = iter([0.0, 0.0, 0.2])

    def monotonic(self):
        return next(self._monotonic)

    def wall_time(self):
        return 1_700_000_000.0


class _Capture:
    def __init__(self):
        self.released = False
        self._frames = iter([(True, "raw-frame")])

    def isOpened(self):
        return True

    def read(self):
        return next(self._frames, (False, None))

    def set(self, _property, _value):
        return True

    def release(self):
        self.released = True


class _Cv2:
    CAP_PROP_FPS = 5

    def __init__(self, capture):
        self.capture = capture
        self.written_images = []

    def VideoCapture(self, _camera_index):
        return self.capture

    def imwrite(self, path, image):
        self.written_images.append(image)
        Path(path).write_bytes(b"image")
        return True


class _RecordingTransform:
    def __init__(self):
        self.frames = []

    def apply(self, frame: FrameRecord) -> FrameRecord:
        self.frames.append(frame)
        return replace(frame, image=f"processed-{frame.image}")


class FramePipelineTests(unittest.TestCase):
    def test_richer_capture_api_reports_deterministic_metrics(self):
        capture = _Capture()
        cv2_module = _Cv2(capture)

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                timestamp_in_filename=False,
                write_exif_timestamp=False,
            )
            result = capture_images_with_result(
                config,
                clock=_Clock(),
                sleep_provider=lambda _seconds: None,
                cv2_module=cv2_module,
            )

        self.assertEqual(1, len(result.images))
        self.assertEqual(1, result.capture_metrics.frames_read)
        self.assertEqual(1, result.capture_metrics.frames_enqueued)
        self.assertEqual(1, result.capture_metrics.frames_saved)
        self.assertEqual(0, result.capture_metrics.read_failures)
        self.assertEqual(0, result.capture_metrics.warmup_requested)
        self.assertEqual(0, result.capture_metrics.warmup_completed)
        self.assertEqual(0, result.capture_metrics.queue_full_events)
        self.assertAlmostEqual(0.2, result.capture_metrics.elapsed_seconds)
        self.assertEqual(1, result.writer_metrics.frames_submitted)
        self.assertEqual(1, result.writer_metrics.frames_written)
        self.assertEqual(0, result.writer_metrics.write_failures)
        self.assertEqual("normal", result.writer_metrics.close_mode)
        self.assertEqual(0, result.writer_metrics.pending_items_at_close)

    def test_injected_transform_runs_between_capture_and_writer(self):
        capture = _Capture()
        cv2_module = _Cv2(capture)
        transform = _RecordingTransform()

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                timestamp_in_filename=False,
                write_exif_timestamp=False,
            )
            saved = capture_images(
                config,
                clock=_Clock(),
                sleep_provider=lambda _seconds: None,
                cv2_module=cv2_module,
                frame_transform=transform,
            )

        self.assertEqual(1, len(saved))
        self.assertEqual(["processed-raw-frame"], cv2_module.written_images)
        self.assertEqual(0, transform.frames[0].sequence)
        self.assertEqual(1_700_000_000.0, transform.frames[0].captured_at)
        self.assertTrue(capture.released)


if __name__ == "__main__":
    unittest.main()
