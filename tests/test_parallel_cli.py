"""Unit tests for unified parallel CLI validation and orchestration wiring.

These tests verify argument validation, camera-only execution, multi-GPIO
dispatch, and failure propagation from worker outcomes.
"""

import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from capture_shared.parallel_cli import main
from capture_shared.parallel_service import ParallelOutcome, WorkerOutcome


class ParallelCliTests(unittest.TestCase):
    @patch("capture_shared.parallel_cli.execute_parallel_capture")
    def test_main_fails_when_gpio_worker_does_not_stop(
        self,
        mock_execute,
    ):
        mock_execute.return_value = ParallelOutcome(
            camera_output_dir=Path("camera"),
            images=(),
            camera_error=None,
            workers=(
                WorkerOutcome(
                    key="gpiochip0:17:door",
                    error=RuntimeError("worker did not stop before the join timeout"),
                ),
            ),
            elapsed_seconds=1.0,
        )
        with tempfile.TemporaryDirectory() as tmp_dir:
            exit_code = main(
                [
                    "--camera-output-dir",
                    str(Path(tmp_dir) / "camera"),
                    "--gpio-output-dir",
                    str(Path(tmp_dir) / "gpio"),
                    "--duration",
                    "1",
                    "--gpio",
                    "gpiochip0:17:door:both",
                ]
            )

        self.assertEqual(1, exit_code)

    @patch("capture_shared.parallel_cli.run_gpio_edge_logger")
    @patch("capture_shared.parallel_cli.capture_images")
    def test_main_runs_camera_only_when_no_gpio_spec_provided(
        self,
        mock_capture_images,
        mock_run_gpio_edge_logger,
    ):
        mock_capture_images.return_value = [Path("one.jpg")]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exit_code = main(
                [
                    "--camera-output-dir",
                    str(Path(tmp_dir) / "camera"),
                    "--duration",
                    "1",
                ]
            )

        self.assertEqual(0, exit_code)
        self.assertEqual(1, mock_capture_images.call_count)
        self.assertEqual(0, mock_run_gpio_edge_logger.call_count)

    @patch("capture_shared.parallel_cli.run_gpio_edge_logger")
    @patch("capture_shared.parallel_cli.capture_images")
    def test_main_runs_camera_and_multiple_gpio_workers(
        self, mock_capture_images, mock_run_gpio_edge_logger
    ):
        mock_capture_images.return_value = [Path("one.jpg"), Path("two.jpg")]
        mock_run_gpio_edge_logger.side_effect = [
            [Path("gpio_a.txt"), Path("gpio_a2.txt")],
            [Path("gpio_b.txt")],
        ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            exit_code = main(
                [
                    "--camera-output-dir",
                    str(Path(tmp_dir) / "camera"),
                    "--gpio-output-dir",
                    str(Path(tmp_dir) / "gpio"),
                    "--duration",
                    "1",
                    "--gpio",
                    "gpiochip0:17:door:both",
                    "--gpio",
                    "gpiochip0:18:button:rising",
                ]
            )

        self.assertEqual(0, exit_code)
        self.assertEqual(1, mock_capture_images.call_count)
        self.assertEqual(2, mock_run_gpio_edge_logger.call_count)

        first_gpio_config = mock_run_gpio_edge_logger.call_args_list[0][0][0]
        second_gpio_config = mock_run_gpio_edge_logger.call_args_list[1][0][0]
        self.assertEqual("door", first_gpio_config.tag)
        self.assertEqual("button", second_gpio_config.tag)
        self.assertEqual("both", first_gpio_config.edge)
        self.assertEqual("rising", second_gpio_config.edge)

    def test_main_rejects_duplicate_gpio_tags(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            exit_code = main(
                [
                    "--camera-output-dir",
                    str(Path(tmp_dir) / "camera"),
                    "--gpio-output-dir",
                    str(Path(tmp_dir) / "gpio"),
                    "--duration",
                    "1",
                    "--gpio",
                    "gpiochip0:17:door:both",
                    "--gpio",
                    "gpiochip0:18:door:rising",
                ]
            )

        self.assertEqual(1, exit_code)

    def test_main_rejects_invalid_gpio_spec(self):
        output = StringIO()
        with tempfile.TemporaryDirectory() as tmp_dir:
            with redirect_stdout(output):
                exit_code = main(
                    [
                        "--camera-output-dir",
                        str(Path(tmp_dir) / "camera"),
                        "--gpio-output-dir",
                        str(Path(tmp_dir) / "gpio"),
                        "--duration",
                        "1",
                        "--gpio",
                        "gpiochip0:17",
                    ]
                )

        self.assertEqual(1, exit_code)
        self.assertIn("Error: ConfigurationError:", output.getvalue())

    def test_main_rejects_gpio_spec_without_gpio_output_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            exit_code = main(
                [
                    "--camera-output-dir",
                    str(Path(tmp_dir) / "camera"),
                    "--duration",
                    "1",
                    "--gpio",
                    "gpiochip0:17:door:both",
                ]
            )

        self.assertEqual(1, exit_code)


if __name__ == "__main__":
    unittest.main()
