"""Unit tests for camera backend implementations and factory selection."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from camera_capture.backends import (
    NativeGStreamerBackend,
    OpenCvBackend,
    create_capture_backend,
    open_camera,
)
from camera_capture.models import CaptureConfig
from capture_shared.errors import ConfigurationError


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
        config = CaptureConfig(output_dir=Path("."), camera_index=3, fps=24.0)
        backend = OpenCvBackend()

        opened = backend.open(config, cv2_module)
        backend.configure(opened, config, cv2_module)

        self.assertIs(opened, capture)
        cv2_module.VideoCapture.assert_called_once_with(3)
        capture.set.assert_called_once_with(5, 24.0)

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
