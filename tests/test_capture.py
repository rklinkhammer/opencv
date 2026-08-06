"""Unit tests for camera capture orchestration.

Coverage includes warmup behavior, backend setup, writer failure handling,
timestamp formatting, EXIF policies, and capture lifecycle edge cases.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from capture_shared.errors import CaptureError, ConfigurationError
from camera_capture.capture import capture_images
from camera_capture.models import CaptureConfig


class _SequenceClock:
    def __init__(self, values):
        self._values = iter(values)
        self._last = 0.0

    def monotonic(self):
        self._last = next(self._values)
        return self._last

    def wall_time(self):
        return self._last


class _DualClock:
    def __init__(self, wall_values, monotonic_values):
        self._wall_values = iter(wall_values)
        self._monotonic_values = iter(monotonic_values)

    def wall_time(self):
        return next(self._wall_values)

    def monotonic(self):
        return next(self._monotonic_values)


class FakeVideoCapture:
    def __init__(self, opened=True, read_sequence=None):
        self._opened = opened
        self._read_sequence = read_sequence or []
        self._read_index = 0
        self.released = False
        self.set_calls = []

    def isOpened(self):
        return self._opened

    def read(self):
        if self._read_index >= len(self._read_sequence):
            return False, None
        item = self._read_sequence[self._read_index]
        self._read_index += 1
        return item

    def release(self):
        self.released = True

    def set(self, prop_id, value):
        self.set_calls.append((prop_id, value))
        return True

    def get(self, prop_id):
        for set_prop_id, value in reversed(self.set_calls):
            if set_prop_id == prop_id:
                return value
        return 0.0


class FakeCv2:
    FONT_HERSHEY_SIMPLEX = 0
    LINE_AA = 0
    CAP_PROP_FPS = 5
    CAP_PROP_FRAME_WIDTH = 3
    CAP_PROP_FRAME_HEIGHT = 4
    CAP_PROP_FOURCC = 6
    CAP_PROP_BRIGHTNESS = 10
    CAP_PROP_GAIN = 14
    CAP_PROP_EXPOSURE = 15
    CAP_PROP_AUTO_EXPOSURE = 21

    def __init__(self, capture_obj):
        self.capture_obj = capture_obj
        self.written = []
        self.overlay_calls = []

    def VideoCapture(self, *args):
        return self.capture_obj

    def VideoWriter_fourcc(self, c1, c2, c3, c4):
        return ord(c1) | (ord(c2) << 8) | (ord(c3) << 16) | (ord(c4) << 24)

    def imwrite(self, path, frame):
        self.written.append((path, frame))
        Path(path).write_bytes(b"image")
        return True

    def putText(self, frame, text, org, font, font_scale, color, thickness, line_type):
        self.overlay_calls.append(
            {
                "text": text,
                "org": org,
                "font": font,
                "font_scale": font_scale,
                "color": color,
                "thickness": thickness,
                "line_type": line_type,
            }
        )
        return frame


class FakeCv2FailFirstWrite(FakeCv2):
    def __init__(self, capture_obj):
        super().__init__(capture_obj)
        self._write_calls = 0

    def imwrite(self, path, frame):
        self._write_calls += 1
        self.written.append((path, frame))
        if self._write_calls == 1:
            return False
        Path(path).write_bytes(b"image")
        return True


class FakeVideoCaptureFailRead(FakeVideoCapture):
    def read(self):
        raise RuntimeError("warmup read failed")


class CaptureImagesTests(unittest.TestCase):
    def test_capture_saves_images_and_releases_camera(self):
        fake_capture = FakeVideoCapture(
            opened=True,
            read_sequence=[
                (True, "warmup-1"),
                (True, "warmup-2"),
                (True, "warmup-3"),
                (True, "warmup-4"),
                (True, "warmup-5"),
                (True, "warmup-6"),
                (True, "warmup-7"),
                (True, "warmup-8"),
                (True, "frame-1"),
                (True, "frame-2"),
                (True, "frame-3"),
            ],
        )
        fake_cv2 = FakeCv2(fake_capture)

        times = iter([0.0, 0.1, 1.0, 2.0, 5.1])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir), duration_seconds=5.0, write_exif_timestamp=False
            )
            saved = capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertEqual(3, len(saved))
        self.assertTrue(fake_capture.released)
        self.assertEqual(3, len(fake_cv2.written))

    def test_capture_raises_if_camera_cannot_open(self):
        fake_capture = FakeVideoCapture(opened=False)
        fake_cv2 = FakeCv2(fake_capture)

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=5.0)
            with self.assertRaises(CaptureError):
                capture_images(
                    config,
                    clock=_SequenceClock([0.0]),
                    sleep_provider=lambda _seconds: None,
                    cv2_module=fake_cv2,
                )
        self.assertTrue(fake_capture.released)

    def test_capture_releases_camera_when_setting_application_fails(self):
        class FailingSettingsCapture(FakeVideoCapture):
            def set(self, prop_id, value):
                raise RuntimeError("setting failed")

        fake_capture = FailingSettingsCapture(opened=True)
        fake_cv2 = FakeCv2(fake_capture)
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=1.0)
            with self.assertRaisesRegex(RuntimeError, "setting failed"):
                capture_images(config, cv2_module=fake_cv2)

        self.assertTrue(fake_capture.released)

    def test_capture_uses_separate_monotonic_deadline_clock(self):
        fake_capture = FakeVideoCapture(
            opened=True,
            read_sequence=[(True, "frame-1"), (True, "frame-2")],
        )
        fake_cv2 = FakeCv2(fake_capture)
        wall_times = iter([1700000000.0, 1600000000.0])
        deadline_times = iter([0.0, 0.0, 0.2])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                write_exif_timestamp=False,
            )
            saved = capture_images(
                config,
                clock=_DualClock(wall_times, deadline_times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertEqual(1, len(saved))

    def test_capture_releases_camera_when_warmup_read_fails(self):
        fake_capture = FakeVideoCaptureFailRead(opened=True)
        fake_cv2 = FakeCv2(fake_capture)

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=1.0)
            with self.assertRaisesRegex(RuntimeError, "warmup read failed"):
                capture_images(
                    config,
                    sleep_provider=lambda _seconds: None,
                    cv2_module=fake_cv2,
                )

        self.assertTrue(fake_capture.released)

    def test_capture_rejects_non_positive_duration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=0)
            with self.assertRaises(ConfigurationError):
                capture_images(config, cv2_module=object())

    def test_capture_rejects_non_positive_fps(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=1, fps=0)
            with self.assertRaises(ConfigurationError):
                capture_images(config, cv2_module=object())

    def test_capture_rejects_negative_warmup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=1, warmup_frames=-1)
            with self.assertRaises(ConfigurationError):
                capture_images(config, cv2_module=object())

    def test_capture_rejects_unsupported_image_extension(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir), duration_seconds=1, image_extension="tiff"
            )
            with self.assertRaises(ConfigurationError):
                capture_images(config, cv2_module=object())

    def test_capture_does_not_throttle_by_software_fps(self):
        fake_capture = FakeVideoCapture(
            opened=True,
            read_sequence=[
                (True, "frame-1"),
                (True, "frame-2"),
                (True, "frame-3"),
                (True, "frame-4"),
                (True, "frame-5"),
            ],
        )
        fake_cv2 = FakeCv2(fake_capture)

        # Capture loop should enqueue each available frame until duration end.
        times = iter([0.0, 0.0, 0.1, 0.5, 0.6, 1.0, 1.1])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=1.0,
                fps=2.0,
                warmup_frames=0,
                write_exif_timestamp=False,
            )
            saved = capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertEqual(4, len(saved))
        self.assertEqual([(fake_cv2.CAP_PROP_FPS, 2.0)], fake_capture.set_calls)

    def test_capture_rejects_non_positive_queue_size(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=1, write_queue_size=0)
            with self.assertRaises(ConfigurationError):
                capture_images(config, cv2_module=object())

    def test_capture_rejects_negative_camera_index(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=1, camera_index=-1)
            with self.assertRaises(ConfigurationError):
                capture_images(config, cv2_module=object())

    def test_capture_timestamped_filename_is_cross_platform_safe(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([1700000000.0, 1700000000.0, 1700000000.2])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                write_exif_timestamp=False,
                timestamp_in_filename=True,
            )
            saved = capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertEqual(1, len(saved))
        self.assertNotIn(":", saved[0].name)

    def test_capture_does_not_deadlock_when_writer_fails_with_backlog(self):
        fake_capture = FakeVideoCapture(
            opened=True,
            read_sequence=[(True, f"frame-{idx}") for idx in range(20)],
        )
        fake_cv2 = FakeCv2FailFirstWrite(fake_capture)
        times = iter([0.0, 0.0, 0.01, 0.015, 0.02, 0.03, 0.04, 0.2])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                write_queue_size=1,
                write_exif_timestamp=False,
            )
            with self.assertRaises(CaptureError):
                capture_images(
                    config,
                    clock=_SequenceClock(times),
                    sleep_provider=lambda _seconds: None,
                    cv2_module=fake_cv2,
                )

        self.assertTrue(fake_capture.released)

    def test_capture_discards_warmup_frames(self):
        fake_capture = FakeVideoCapture(
            opened=True,
            read_sequence=[
                (True, "black-1"),
                (True, "black-2"),
                (True, "good-1"),
                (True, "good-2"),
            ],
        )
        fake_cv2 = FakeCv2(fake_capture)

        times = [0.0, 0.0, 0.1, 0.2]
        index = -1

        def time_provider():
            nonlocal index
            index = min(index + 1, len(times) - 1)
            return times[index]

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.15,
                fps=10.0,
                warmup_frames=2,
                write_exif_timestamp=False,
            )
            saved = capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertEqual(2, len(saved))

    def test_capture_can_disable_timestamp_in_filename(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([0.0, 0.0, 0.2])

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
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertEqual(1, len(saved))
        self.assertTrue(saved[0].name.startswith("frame_000000."))

    def test_capture_does_not_overwrite_existing_image(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([0.0, 0.0, 0.2])

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            existing = output_dir / "frame_000000.jpg"
            existing.write_bytes(b"existing")
            config = CaptureConfig(
                output_dir=output_dir,
                duration_seconds=0.1,
                warmup_frames=0,
                timestamp_in_filename=False,
                write_exif_timestamp=False,
            )
            saved = capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

            self.assertEqual(b"existing", existing.read_bytes())
            self.assertEqual("frame_000000_0001.jpg", saved[0].name)

    def test_capture_can_overlay_timestamp_with_custom_text(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([0.0, 0.0, 0.2])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                overlay_timestamp=True,
                overlay_text="Cam-A",
                write_exif_timestamp=False,
            )
            capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertEqual(1, len(fake_cv2.overlay_calls))
        self.assertIn("Cam-A", fake_cv2.overlay_calls[0]["text"])

    def test_capture_writes_exif_when_enabled(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([0.0, 0.0, 0.2])
        exif_calls = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                write_exif_timestamp=True,
                image_extension="jpg",
            )
            capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
                exif_writer=lambda path, capture_time: exif_calls.append((path, capture_time)),
            )

        self.assertEqual(1, len(exif_calls))

    def test_capture_skips_exif_for_non_jpeg_extensions(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([0.0, 0.0, 0.2])
        exif_calls = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                write_exif_timestamp=True,
                image_extension="png",
            )
            saved = capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
                exif_writer=lambda path, capture_time: exif_calls.append((path, capture_time)),
            )

        self.assertEqual(1, len(saved))
        self.assertTrue(saved[0].name.endswith(".png"))
        self.assertEqual(0, len(exif_calls))

    def test_capture_uses_gstreamer_backend(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([0.0, 0.0, 0.2])

        backend = MagicMock()
        backend.open.return_value = fake_capture
        with patch(
            "camera_capture.backends.create_capture_backend", return_value=backend
        ) as mock_factory:
            with tempfile.TemporaryDirectory() as tmp_dir:
                config = CaptureConfig(
                    output_dir=Path(tmp_dir),
                    duration_seconds=0.1,
                    warmup_frames=0,
                    capture_backend="gstreamer",
                    write_exif_timestamp=False,
                )
                capture_images(
                    config,
                    clock=_SequenceClock(times),
                    sleep_provider=lambda _seconds: None,
                    cv2_module=fake_cv2,
                )

        mock_factory.assert_called_once_with("gstreamer")
        backend.open.assert_called_once_with(config, fake_cv2)
        backend.configure.assert_called_once_with(fake_capture, config, fake_cv2)

    def test_capture_uses_custom_gstreamer_pipeline(self):
        from camera_capture.backends import build_gstreamer_pipeline

        config = CaptureConfig(
            output_dir=Path("."),
            capture_backend="gstreamer",
            gstreamer_pipeline="v4l2src device=/dev/video0 ! videoconvert ! appsink name=appsink",
        )
        self.assertEqual(config.gstreamer_pipeline, build_gstreamer_pipeline(config))

    def test_capture_builds_jetson_csi_pipeline(self):
        from camera_capture.backends import build_gstreamer_pipeline

        config = CaptureConfig(
            output_dir=Path("."),
            capture_backend="gstreamer",
            gstreamer_source="jetson-csi",
            camera_index=1,
            frame_width=1920,
            frame_height=1080,
            fps=30,
        )
        pipeline = build_gstreamer_pipeline(config)
        self.assertIn("nvarguscamerasrc sensor-id=1", pipeline)
        self.assertIn("width=(int)1920", pipeline)
        self.assertIn("height=(int)1080", pipeline)

    def test_capture_rejects_unknown_gstreamer_source(self):
        from camera_capture.backends import build_gstreamer_pipeline

        config = CaptureConfig(
            output_dir=Path("."),
            capture_backend="gstreamer",
            gstreamer_source="invalid-source",
        )
        with self.assertRaises(ConfigurationError):
            build_gstreamer_pipeline(config)

    def test_capture_rejects_unknown_backend(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir), duration_seconds=1, capture_backend="unknown"
            )
            with self.assertRaises(ConfigurationError):
                capture_images(config, cv2_module=object())

    def test_capture_applies_optional_camera_controls(self):
        fake_capture = FakeVideoCapture(opened=True, read_sequence=[(True, "frame-1")])
        fake_cv2 = FakeCv2(fake_capture)
        times = iter([0.0, 0.0, 0.2])

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(
                output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                warmup_frames=0,
                write_exif_timestamp=False,
                frame_width=640,
                frame_height=480,
                fourcc="mjpg",
                auto_exposure=3.0,
                exposure=-6.0,
                gain=8.0,
                brightness=42.0,
            )
            capture_images(
                config,
                clock=_SequenceClock(times),
                sleep_provider=lambda _seconds: None,
                cv2_module=fake_cv2,
            )

        self.assertIn((fake_cv2.CAP_PROP_FRAME_WIDTH, 640.0), fake_capture.set_calls)
        self.assertIn((fake_cv2.CAP_PROP_FRAME_HEIGHT, 480.0), fake_capture.set_calls)
        self.assertIn((fake_cv2.CAP_PROP_AUTO_EXPOSURE, 3.0), fake_capture.set_calls)
        self.assertIn((fake_cv2.CAP_PROP_EXPOSURE, -6.0), fake_capture.set_calls)
        self.assertIn((fake_cv2.CAP_PROP_GAIN, 8.0), fake_capture.set_calls)
        self.assertIn((fake_cv2.CAP_PROP_BRIGHTNESS, 42.0), fake_capture.set_calls)


if __name__ == "__main__":
    unittest.main()
