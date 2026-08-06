"""Tests for application errors and error chaining."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from camera_capture.backends import NativeGStreamerCapture
from camera_capture.models import CaptureConfig
from capture_shared.errors import CaptureError, ConfigurationError, GpioError
from capture_shared.output import OutputTransaction
from capture_shared.parallel_service import GpioJob, execute_parallel_capture
from gpio_capture.gpio_edge import GpioEdgeConfig, run_gpio_edge_logger


class ErrorHierarchyTests(unittest.TestCase):
    def test_specific_errors_share_one_catchable_base(self):
        self.assertTrue(issubclass(ConfigurationError, CaptureError))
        self.assertTrue(issubclass(GpioError, CaptureError))

    def test_native_gstreamer_dependency_failure_is_capture_error(self):
        config = CaptureConfig(output_dir=Path("."), capture_backend="gstreamer")

        with patch.dict("sys.modules", {"gi": None}):
            with self.assertRaises(CaptureError) as raised:
                NativeGStreamerCapture(config)

        self.assertIsInstance(raised.exception.__cause__, ImportError)

    def test_output_commit_failure_is_capture_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            transaction = OutputTransaction(Path(tmp_dir), "frame_000000", "jpg")
            transaction.temporary.write_bytes(b"image")
            with patch("capture_shared.output.os.replace", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(CaptureError, "Unable to commit output") as raised:
                    transaction.commit()
            transaction.close()

        self.assertIsInstance(raised.exception.__cause__, OSError)

    def test_gpio_v1_request_failure_is_gpio_error(self):
        class FailingLine:
            def request(self, **_kwargs):
                raise OSError("line busy")

            def release(self):
                pass

        class Chip:
            def get_line(self, _offset):
                return FailingLine()

            def close(self):
                pass

        class Gpiod:
            LINE_REQ_EV_RISING_EDGE = 1
            LINE_REQ_EV_FALLING_EDGE = 2
            LINE_REQ_EV_BOTH_EDGES = 3

            def Chip(self, _name):
                return Chip()

        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(output_dir=Path(tmp_dir), chip_name="gpiochip0", line_offset=4)
            with self.assertRaisesRegex(GpioError, "Unable to request GPIO line") as raised:
                run_gpio_edge_logger(config, gpiod_module=Gpiod())

        self.assertIsInstance(raised.exception.__cause__, OSError)

    def test_gpio_v1_line_lookup_failure_closes_open_chip(self):
        class Chip:
            def __init__(self):
                self.closed = False

            def get_line(self, _offset):
                raise OSError("line unavailable")

            def close(self):
                self.closed = True

        class Gpiod:
            LINE_REQ_EV_RISING_EDGE = 1
            LINE_REQ_EV_FALLING_EDGE = 2
            LINE_REQ_EV_BOTH_EDGES = 3

            def __init__(self):
                self.chip = Chip()

            def Chip(self, _name):
                return self.chip

        gpiod = Gpiod()
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(output_dir=Path(tmp_dir), chip_name="gpiochip0", line_offset=4)
            with self.assertRaisesRegex(GpioError, "Unable to access GPIO line"):
                run_gpio_edge_logger(config, gpiod_module=gpiod)

        self.assertTrue(gpiod.chip.closed)

    def test_missing_parallel_worker_result_is_capture_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = CaptureConfig(output_dir=Path(tmp_dir), duration_seconds=0.1)
            outcome = execute_parallel_capture(
                camera_config=config,
                gpio_jobs=[GpioJob("gpiochip0", 4, "door", "both")],
                gpio_output_dir=Path(tmp_dir),
                duration_seconds=0.1,
                gpio_poll_timeout_ms=1,
                capture_fn=lambda _config: [],
                gpio_fn=lambda *_args, **_kwargs: None,
            )

        self.assertIsInstance(outcome.workers[0].error, CaptureError)

    def test_parallel_service_requires_output_directory_for_gpio_jobs(self):
        config = CaptureConfig(output_dir=Path("."), duration_seconds=0.1)

        with self.assertRaisesRegex(ConfigurationError, "gpio_output_dir is required"):
            execute_parallel_capture(
                camera_config=config,
                gpio_jobs=[GpioJob("gpiochip0", 4, "door", "both")],
                gpio_output_dir=None,
                duration_seconds=0.1,
                gpio_poll_timeout_ms=1,
                capture_fn=lambda _config: [],
                gpio_fn=lambda *_args, **_kwargs: [],
            )


if __name__ == "__main__":
    unittest.main()
