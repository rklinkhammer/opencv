"""Unit tests for camera backend implementations and factory selection."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from camera_capture.backends import (
    NativeGStreamerBackend,
    OpenCvBackend,
    apply_camera_settings,
    create_capture_backend,
    open_camera,
)
from camera_capture.models import CaptureConfig
from capture_shared.errors import CaptureError, ConfigurationError


class BackendFactoryTests(unittest.TestCase):
    def test_factory_returns_backend_implementations_for_public_names(self):
        self.assertIsInstance(create_capture_backend(" OpenCV "), OpenCvBackend)
        self.assertIsInstance(create_capture_backend("GSTREAMER"), NativeGStreamerBackend)

    def test_factory_rejects_unknown_backend(self):
        with self.assertRaises(ConfigurationError):
            create_capture_backend("unknown")

    def test_opencv_backend_owns_open_and_configuration(self):
        capture = MagicMock()
        cv2_module = MagicMock()
        cv2_module.VideoCapture.return_value = capture
        cv2_module.CAP_PROP_FPS = 5
        capture.set.return_value = True
        capture.get.return_value = 24.0
        config = CaptureConfig(output_dir=Path("."), camera_index=3, fps=24.0)
        backend = OpenCvBackend()

        opened = backend.open(config, cv2_module)
        backend.configure(opened, config, cv2_module)

        self.assertIs(opened, capture)
        cv2_module.VideoCapture.assert_called_once_with(3)
        capture.set.assert_called_once_with(5, 24.0)

    def test_verbose_configuration_reports_defaults_and_verified_values(self):
        class Cv2:
            CAP_PROP_FPS = 5
            CAP_PROP_FRAME_WIDTH = 3

        class Capture:
            values = {5: 29.97, 3: 1920.0}

            def get(self, property_id):
                return self.values[property_id]

            def set(self, property_id, value):
                self.values[property_id] = value
                return True

        config = CaptureConfig(output_dir=Path("."), fps=30.0, frame_width=640, verbose=True)

        with patch("builtins.print") as report:
            apply_camera_settings(Capture(), config, Cv2())

        lines = [call.args[0] for call in report.call_args_list]
        self.assertIn("Camera defaults: fps=29.97, width=1920", lines)
        self.assertIn("Camera setting verified: fps=30 (actual=30)", lines)
        self.assertIn("Camera setting verified: width=640 (actual=640)", lines)

    def test_configuration_fails_when_camera_does_not_apply_value(self):
        class Cv2:
            CAP_PROP_FPS = 5

        capture = MagicMock()
        capture.set.return_value = True
        capture.get.return_value = 30.0
        config = CaptureConfig(output_dir=Path("."), fps=60.0)

        with self.assertRaisesRegex(CaptureError, "did not apply fps"):
            apply_camera_settings(capture, config, Cv2())

    def test_native_gstreamer_backend_owns_capture_construction(self):
        config = CaptureConfig(output_dir=Path("."), capture_backend="gstreamer")
        capture = MagicMock()
        backend = NativeGStreamerBackend()

        with patch("camera_capture.backends.NativeGStreamerCapture", return_value=capture):
            opened = backend.open(config, object())
            backend.configure(opened, config, object())

        self.assertIs(opened, capture)

    def test_open_camera_uses_injected_backend(self):
        config = CaptureConfig(output_dir=Path("."), capture_backend="gstreamer")
        cv2_module = object()
        capture = MagicMock()
        capture.isOpened.return_value = True
        backend = MagicMock()
        backend.open.return_value = capture

        with open_camera(config, cv2_module, backend) as opened:
            self.assertIs(opened, capture)

        backend.open.assert_called_once_with(config, cv2_module)
        backend.configure.assert_called_once_with(capture, config, cv2_module)
        capture.release.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
