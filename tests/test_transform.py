"""Integration test for the optional frame transform."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from camera_capture.capture import capture_images
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
        self._properties = {}

    def isOpened(self):
        return True

    def read(self):
        return next(self._frames, (False, None))

    def set(self, property_id, value):
        self._properties[property_id] = value
        return True

    def get(self, property_id):
        return self._properties.get(property_id, 0.0)

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

    def __call__(self, frame: FrameRecord) -> FrameRecord:
        self.frames.append(frame)
        return replace(frame, image=f"processed-{frame.image}")


class FramePipelineTests(unittest.TestCase):
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
