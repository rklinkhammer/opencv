"""Canonical configuration validation tests for camera and GPIO workflows."""

import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from io import StringIO
from pathlib import Path

from camera_capture.cli import main as camera_main
from camera_capture.models import CaptureConfig
from camera_capture.validators import validate_capture_config
from capture_shared.errors import ConfigurationError
from gpio_capture.gpio_edge import GpioEdgeConfig, validate_gpio_config


class CaptureConfigValidationTests(unittest.TestCase):
    def test_camera_cli_reports_canonical_configuration_error(self):
        out = StringIO()
        with redirect_stdout(out):
            exit_code = camera_main(
                [
                    "--output-dir",
                    "./captures",
                    "--width",
                    "0",
                ]
            )

        self.assertEqual(1, exit_code)
        self.assertIn(
            "Error: ConfigurationError: frame_width must be greater than 0",
            out.getvalue(),
        )

    def test_valid_config_returns_normalized_runtime_values(self):
        config = CaptureConfig(
            output_dir=Path("captures"),
            capture_backend=" OpenCV ",
            image_extension=".JPEG",
            fourcc="mjpg",
        )

        self.assertEqual(("opencv", "jpeg"), validate_capture_config(config))

    def test_complete_capture_contract_is_validated_canonically(self):
        base = CaptureConfig(output_dir=Path("captures"))
        invalid_values = (
            ("duration_seconds", 0, "duration_seconds"),
            ("fps", 0, "fps"),
            ("camera_index", -1, "camera_index"),
            ("warmup_frames", -1, "warmup_frames"),
            ("write_queue_size", 0, "write_queue_size"),
            ("frame_width", 0, "frame_width"),
            ("frame_height", 0, "frame_height"),
            ("capture_backend", "unknown", "capture_backend"),
            ("image_extension", "tiff", "image_extension"),
            ("fourcc", "MJ", "fourcc"),
        )

        for field, value, message in invalid_values:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ConfigurationError, message):
                    validate_capture_config(replace(base, **{field: value}))


class GpioConfigValidationTests(unittest.TestCase):
    def test_valid_gpio_config_accepts_normalized_edge_spelling(self):
        config = GpioEdgeConfig(
            output_dir=Path("gpio"),
            chip_name="gpiochip0",
            line_offset=17,
            tag="door",
            edge=" BOTH ",
            max_events=0,
            poll_timeout_ms=1,
            duration_seconds=0.1,
        )

        validate_gpio_config(config)

    def test_complete_gpio_contract_is_validated_canonically(self):
        base = GpioEdgeConfig(
            output_dir=Path("gpio"),
            chip_name="gpiochip0",
            line_offset=17,
        )
        invalid_values = (
            ("output_dir", None, "output_dir"),
            ("chip_name", " ", "chip_name"),
            ("line_offset", -1, "line_offset"),
            ("tag", " ", "tag"),
            ("edge", "invalid", "edge"),
            ("max_events", -1, "max_events"),
            ("poll_timeout_ms", 0, "poll_timeout_ms"),
            ("duration_seconds", 0, "duration_seconds"),
        )

        for field, value, message in invalid_values:
            with self.subTest(field=field):
                with self.assertRaisesRegex(ConfigurationError, message):
                    validate_gpio_config(replace(base, **{field: value}))


if __name__ == "__main__":
    unittest.main()
