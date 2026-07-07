"""Optional hardware integration tests for real camera and GPIO devices.

These checks are intended for environments with physical hardware and may be
skipped in CI or local runs without attached peripherals.
"""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.mark.hardware
@pytest.mark.skipif(
    os.environ.get("CAMERA_CAPTURE_RUN_HARDWARE_TESTS") != "1",
    reason="set CAMERA_CAPTURE_RUN_HARDWARE_TESTS=1 to enable",
)
def test_default_camera_returns_a_frame():
    cv2 = pytest.importorskip("cv2")
    capture = cv2.VideoCapture(0)
    try:
        assert capture.isOpened()
        ok, frame = capture.read()
        assert ok
        assert frame is not None
    finally:
        capture.release()


@pytest.mark.hardware
@pytest.mark.skipif(
    os.environ.get("GPIO_CAPTURE_RUN_HARDWARE_TESTS") != "1",
    reason="set GPIO_CAPTURE_RUN_HARDWARE_TESTS=1 to enable",
)
def test_configured_gpio_line_returns_initial_value():
    pytest.importorskip("gpiod")
    from gpio_capture.gpio_edge import GpioEdgeConfig, run_gpio_edge_logger

    chip = os.environ.get("GPIO_CAPTURE_CHIP", "gpiochip0")
    line = int(os.environ["GPIO_CAPTURE_LINE"])
    with tempfile.TemporaryDirectory() as tmp_dir:
        written = run_gpio_edge_logger(
            GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name=chip,
                line_offset=line,
                max_events=0,
            )
        )
        assert len(written) == 1
        assert written[0].read_text(encoding="utf-8") in {"0\n", "1\n"}
