"""Unit tests for camera CLI command flows and output rendering.

These tests validate argument wiring, benchmark paths, and non-zero exit
behavior when runtime operations fail.
"""

from pathlib import Path
import unittest
from unittest.mock import patch
from io import StringIO
from contextlib import redirect_stdout

from camera_capture.cli import main
from camera_capture.models import CaptureConfig
from parallel_cli import build_parser as build_parallel_parser


class CliTests(unittest.TestCase):
    def test_compose_lists_every_parallel_cli_option(self):
        parser = build_parallel_parser()
        compose = (Path(__file__).parents[1] / "compose.yaml").read_text(encoding="utf-8")
        options = {
            option
            for action in parser._actions
            for option in action.option_strings
            if option.startswith("--") and option != "--help"
        }

        self.assertEqual([], sorted(option for option in options if option not in compose))

    @patch("camera_capture.cli.capture_images")
    def test_main_success(self, mock_capture_images):
        mock_capture_images.return_value = ["one", "two"]

        exit_code = main(
            [
                "--output-dir",
                "./captures",
                "--duration",
                "5",
                "--verbose",
                "--camera-index",
                "0",
                "--capture-backend",
                "gstreamer",
                "--gstreamer-source",
                "jetson-csi",
                "--gstreamer-pipeline",
                "v4l2src device=/dev/video0 ! videoconvert ! appsink",
                "--fps",
                "2",
                "--width",
                "640",
                "--height",
                "480",
                "--fourcc",
                "MJPG",
                "--auto-exposure",
                "3",
                "--exposure",
                "-6",
                "--gain",
                "8",
                "--brightness",
                "42",
                "--contrast",
                "10",
                "--saturation",
                "20",
                "--hue",
                "1",
                "--gamma",
                "100",
                "--sharpness",
                "3",
                "--backlight",
                "1",
                "--no-auto-white-balance",
                "--white-balance-temperature",
                "4500",
                "--white-balance-blue",
                "2",
                "--white-balance-red",
                "3",
                "--no-autofocus",
                "--focus",
                "20",
                "--zoom",
                "2",
                "--pan",
                "1",
                "--tilt",
                "2",
                "--roll",
                "3",
                "--buffer-size",
                "1",
                "--warmup-frames",
                "8",
                "--overlay-timestamp",
                "--overlay-text",
                "Lab Camera",
                "--no-timestamp-in-filename",
                "--write-exif-timestamp",
                "--image-type",
                "png",
                "--write-queue-size",
                "256",
                "--log-file",
                "./captures/capture.log",
            ]
        )

        self.assertEqual(0, exit_code)
        mock_capture_images.assert_called_once()
        config = mock_capture_images.call_args[0][0]
        self.assertIsInstance(config, CaptureConfig)
        self.assertTrue(config.verbose)
        self.assertEqual("gstreamer", config.capture_backend)
        self.assertEqual("jetson-csi", config.gstreamer_source)
        self.assertEqual(
            "v4l2src device=/dev/video0 ! videoconvert ! appsink", config.gstreamer_pipeline
        )
        self.assertEqual(2.0, config.fps)
        self.assertEqual(640, config.frame_width)
        self.assertEqual(480, config.frame_height)
        self.assertEqual("MJPG", config.fourcc)
        self.assertEqual(3.0, config.auto_exposure)
        self.assertEqual(-6.0, config.exposure)
        self.assertEqual(8.0, config.gain)
        self.assertEqual(42.0, config.brightness)
        self.assertEqual(10.0, config.contrast)
        self.assertEqual(20.0, config.saturation)
        self.assertEqual(1.0, config.hue)
        self.assertEqual(100.0, config.gamma)
        self.assertEqual(3.0, config.sharpness)
        self.assertEqual(1.0, config.backlight)
        self.assertFalse(config.auto_white_balance)
        self.assertEqual(4500.0, config.white_balance_temperature)
        self.assertEqual(2.0, config.white_balance_blue)
        self.assertEqual(3.0, config.white_balance_red)
        self.assertFalse(config.autofocus)
        self.assertEqual(20.0, config.focus)
        self.assertEqual(2.0, config.zoom)
        self.assertEqual(1.0, config.pan)
        self.assertEqual(2.0, config.tilt)
        self.assertEqual(3.0, config.roll)
        self.assertEqual(1, config.buffer_size)
        self.assertEqual(8, config.warmup_frames)
        self.assertTrue(config.overlay_timestamp)
        self.assertEqual("Lab Camera", config.overlay_text)
        self.assertFalse(config.timestamp_in_filename)
        self.assertTrue(config.write_exif_timestamp)
        self.assertEqual("png", config.image_extension)
        self.assertEqual(256, config.write_queue_size)
        self.assertEqual("capture.log", config.log_file.name)

    @patch("camera_capture.cli.capture_images")
    def test_main_failure(self, mock_capture_images):
        mock_capture_images.side_effect = RuntimeError("camera unavailable")

        exit_code = main(
            [
                "--output-dir",
                "./captures",
            ]
        )

        self.assertEqual(1, exit_code)

    @patch("camera_capture.cli.capture_images")
    def test_main_benchmark_mode(self, mock_capture_images):
        mock_capture_images.side_effect = [["a"], ["b", "c"]]

        exit_code = main(
            [
                "--output-dir",
                "./captures",
                "--benchmark-backends",
                "--benchmark-duration",
                "1",
                "--camera-index",
                "0",
                "--fps",
                "30",
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertEqual(2, mock_capture_images.call_count)
        first_config = mock_capture_images.call_args_list[0][0][0]
        second_config = mock_capture_images.call_args_list[1][0][0]
        self.assertEqual("opencv", first_config.capture_backend)
        self.assertEqual("gstreamer", second_config.capture_backend)

    @patch("camera_capture.cli.capture_images")
    def test_main_benchmark_mode_returns_failure_if_any_backend_fails(self, mock_capture_images):
        mock_capture_images.side_effect = [["a"], RuntimeError("backend failed")]

        exit_code = main(
            [
                "--output-dir",
                "./captures",
                "--benchmark-backends",
                "--benchmark-duration",
                "1",
                "--camera-index",
                "0",
                "--fps",
                "30",
            ]
        )

        self.assertEqual(1, exit_code)

    @patch("camera_capture.cli.capture_images")
    def test_main_benchmark_mode_failure_output_includes_exception_type(self, mock_capture_images):
        mock_capture_images.side_effect = [["a"], RuntimeError("backend failed")]

        out = StringIO()
        with redirect_stdout(out):
            exit_code = main(
                [
                    "--output-dir",
                    "./captures",
                    "--benchmark-backends",
                    "--benchmark-duration",
                    "1",
                    "--camera-index",
                    "0",
                    "--fps",
                    "30",
                ]
            )

        self.assertEqual(1, exit_code)
        self.assertIn("FAIL: RuntimeError: backend failed", out.getvalue())

    @patch("camera_capture.cli.capture_images")
    @patch("camera_capture.cli.benchmark_capture_only")
    def test_main_benchmark_capture_only_mode(
        self, mock_benchmark_capture_only, mock_capture_images
    ):
        mock_benchmark_capture_only.side_effect = [(10, 1.0, 10.0), (12, 1.0, 12.0)]

        exit_code = main(
            [
                "--output-dir",
                "./captures",
                "--benchmark-backends",
                "--benchmark-capture-only",
                "--benchmark-duration",
                "1",
                "--camera-index",
                "0",
                "--fps",
                "30",
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertEqual(2, mock_benchmark_capture_only.call_count)
        mock_capture_images.assert_not_called()

    @patch("camera_capture.cli.capture_images")
    @patch("camera_capture.cli.benchmark_capture_only")
    def test_main_jetson_csi_benchmark_mode(self, mock_benchmark_capture_only, mock_capture_images):
        mock_benchmark_capture_only.side_effect = [
            (5, 1.0, 5.0),
            (10, 1.0, 10.0),
            (20, 1.0, 20.0),
            (30, 1.0, 30.0),
        ]

        exit_code = main(
            [
                "--output-dir",
                "./captures",
                "--benchmark-jetson-csi",
                "--benchmark-capture-only",
                "--benchmark-duration",
                "1",
                "--camera-index",
                "0",
                "--fps",
                "30",
            ]
        )

        self.assertEqual(0, exit_code)
        self.assertEqual(4, mock_benchmark_capture_only.call_count)

        benchmarked_resolutions = [
            (call_args[0][0].frame_width, call_args[0][0].frame_height)
            for call_args in mock_benchmark_capture_only.call_args_list
        ]
        self.assertEqual(
            [(320, 240), (640, 480), (1280, 720), (1920, 1080)],
            benchmarked_resolutions,
        )
        mock_capture_images.assert_not_called()

    def test_main_rejects_incompatible_benchmark_flags(self):
        exit_code = main(
            [
                "--output-dir",
                "./captures",
                "--benchmark-backends",
                "--benchmark-jetson-csi",
            ]
        )

        self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
