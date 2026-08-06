"""Unit tests for camera backend implementations and factory selection."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from camera_capture.backends import (
    CAMERA_PROPERTIES,
    NativeGStreamerBackend,
    NativeGStreamerCapture,
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
            CAP_PROP_FORMAT = 8
            CAP_PROP_CODEC_PIXEL_FORMAT = 46
            CAP_PROP_TEMPERATURE = 23

        class Capture:
            values = {5: 29.97, 3: 1920.0, 8: 16.0, 46: 0.0, 23: 42.0}

            def getBackendName(self):
                return "AVFOUNDATION"

            def get(self, property_id):
                return self.values[property_id]

            def set(self, property_id, value):
                self.values[property_id] = value
                return True

        config = CaptureConfig(output_dir=Path("."), fps=30.0, frame_width=640, verbose=True)

        lines = []
        apply_camera_settings(Capture(), config, Cv2(), lines.append)

        self.assertIn(
            "Camera defaults: fps=29.97, width=1920, backend=AVFOUNDATION, "
            "format=16, codec_pixel_format=0, temperature=42",
            lines,
        )
        self.assertIn("Camera setting verified: fps=30 (actual=30)", lines)
        self.assertIn("Camera setting verified: width=640 (actual=640)", lines)

    def test_unavailable_default_does_not_prevent_requested_setting(self):
        class Cv2:
            CAP_PROP_FPS = 5

        class Capture:
            reads = 0

            def get(self, property_id):
                self.reads += 1
                if self.reads == 1:
                    raise RuntimeError("unsupported diagnostic read")
                return 30.0

            def set(self, property_id, value):
                return True

        lines = []
        apply_camera_settings(
            Capture(), CaptureConfig(output_dir=Path("."), fps=30), Cv2(), lines.append
        )

        self.assertIn("Camera defaults: fps=unavailable", lines)
        self.assertIn("Camera setting verified: fps=30 (actual=30)", lines)

    def test_boolean_verification_does_not_accept_half_enabled_value(self):
        class Cv2:
            CAP_PROP_FPS = 5
            CAP_PROP_AUTOFOCUS = 39

        capture = MagicMock()
        capture.set.return_value = True
        capture.get.side_effect = lambda property_id: 30.0 if property_id == 5 else 0.5

        with self.assertRaisesRegex(CaptureError, "did not apply autofocus"):
            apply_camera_settings(
                capture,
                CaptureConfig(output_dir=Path("."), fps=30, autofocus=True),
                Cv2(),
            )

    def test_property_registry_covers_all_configurable_opencv_controls(self):
        self.assertEqual(
            {
                "fps",
                "frame_width",
                "frame_height",
                "auto_exposure",
                "exposure",
                "gain",
                "brightness",
                "contrast",
                "saturation",
                "hue",
                "gamma",
                "sharpness",
                "backlight",
                "auto_white_balance",
                "white_balance_temperature",
                "white_balance_blue",
                "white_balance_red",
                "autofocus",
                "focus",
                "zoom",
                "pan",
                "tilt",
                "roll",
                "buffer_size",
            },
            set(CAMERA_PROPERTIES),
        )

    def test_configuration_fails_when_camera_does_not_apply_value(self):
        class Cv2:
            CAP_PROP_FPS = 5

        capture = MagicMock()
        capture.set.return_value = True
        capture.get.return_value = 30.0
        config = CaptureConfig(output_dir=Path("."), fps=60.0)

        with self.assertRaisesRegex(CaptureError, "did not apply fps"):
            apply_camera_settings(capture, config, Cv2())

    def test_standard_uvc_controls_are_applied_through_the_registry(self):
        class Cv2:
            CAP_PROP_FPS = 5
            CAP_PROP_CONTRAST = 11
            CAP_PROP_AUTO_WB = 44
            CAP_PROP_AUTOFOCUS = 39
            CAP_PROP_BUFFERSIZE = 38

        class Capture:
            def __init__(self):
                self.values = {}

            def set(self, property_id, value):
                self.values[property_id] = value
                return True

            def get(self, property_id):
                return self.values[property_id]

        capture = Capture()
        config = CaptureConfig(
            output_dir=Path("."),
            fps=30,
            contrast=10,
            auto_white_balance=False,
            autofocus=True,
            buffer_size=2,
        )

        apply_camera_settings(capture, config, Cv2())

        self.assertEqual({5: 30.0, 11: 10.0, 44: 0.0, 39: 1.0, 38: 2.0}, capture.values)

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
        backend.configure.assert_called_once_with(capture, config, cv2_module, None)
        capture.release.assert_called_once_with()

    def test_gstreamer_caps_are_reported_and_verified(self):
        class Fraction:
            numerator = 30
            denominator = 1

        class Structure:
            values = {"format": "BGR", "framerate": Fraction()}

            def get_value(self, name):
                return self.values[name]

        capture = object.__new__(NativeGStreamerCapture)
        capture._config = CaptureConfig(  # noqa: SLF001 - focused boundary test
            output_dir=Path("."), frame_width=640, frame_height=480, fps=30
        )
        lines = []
        capture._reporter = lines.append  # noqa: SLF001 - focused boundary test

        capture._verify_caps(Structure(), 640, 480)  # noqa: SLF001

        self.assertEqual(["GStreamer negotiated: width=640, height=480, fps=30, format=BGR"], lines)

    def test_gstreamer_caps_mismatch_fails_for_generated_pipeline(self):
        class Fraction:
            numerator = 30
            denominator = 1

        structure = MagicMock()
        structure.get_value.side_effect = lambda name: {
            "format": "BGR",
            "framerate": Fraction(),
        }[name]
        structure.get_fraction.return_value = (True, 30, 1)
        capture = object.__new__(NativeGStreamerCapture)
        capture._config = CaptureConfig(  # noqa: SLF001
            output_dir=Path("."), frame_width=640, frame_height=480, fps=30
        )
        capture._reporter = None  # noqa: SLF001

        with self.assertRaisesRegex(CaptureError, "did not apply requested caps"):
            capture._verify_caps(structure, 1280, 720)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
