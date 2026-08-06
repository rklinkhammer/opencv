"""Tests for opening and releasing camera handles."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock

from camera_capture.backends import open_camera
from camera_capture.models import CaptureConfig
from capture_shared.errors import CaptureError


class OpenCameraTests(unittest.TestCase):
    def setUp(self):
        self.config = CaptureConfig(output_dir=Path("."), camera_index=2)
        self.cv2_module = object()
        self.capture = MagicMock()
        self.capture.isOpened.return_value = True
        self.backend = MagicMock()
        self.backend.open.return_value = self.capture

    def test_releases_capture_after_normal_exit(self):
        with open_camera(self.config, self.cv2_module, self.backend) as opened:
            self.assertIs(opened, self.capture)

        self.capture.release.assert_called_once_with()

    def test_releases_capture_when_context_body_raises(self):
        with self.assertRaisesRegex(RuntimeError, "read failed"):
            with open_camera(self.config, self.cv2_module, self.backend):
                raise RuntimeError("read failed")

        self.capture.release.assert_called_once_with()

    def test_releases_capture_when_handle_is_not_open(self):
        self.capture.isOpened.return_value = False

        with self.assertRaisesRegex(CaptureError, "camera at index 2"):
            with open_camera(self.config, self.cv2_module, self.backend):
                pass

        self.backend.configure.assert_not_called()
        self.capture.release.assert_called_once_with()

    def test_releases_capture_when_backend_configuration_fails(self):
        self.backend.configure.side_effect = RuntimeError("configuration failed")

        with self.assertRaisesRegex(RuntimeError, "configuration failed"):
            with open_camera(self.config, self.cv2_module, self.backend):
                pass

        self.capture.release.assert_called_once_with()

    def test_release_failure_does_not_mask_context_error(self):
        self.capture.release.side_effect = RuntimeError("release failed")

        with self.assertRaisesRegex(RuntimeError, "read failed"):
            with open_camera(self.config, self.cv2_module, self.backend):
                raise RuntimeError("read failed")


if __name__ == "__main__":
    unittest.main()
