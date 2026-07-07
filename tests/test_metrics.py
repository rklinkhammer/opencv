"""Deterministic tests for structured GPIO runtime metrics."""

import tempfile
import unittest
from pathlib import Path

from gpio_capture.gpio_edge import GpioEdgeConfig, run_gpio_edge_logger_with_result


class _Clock:
    def __init__(self):
        self._values = iter([10.0, 10.1, 10.2])
        self._last = 0.0

    def monotonic(self):
        self._last = next(self._values)
        return self._last

    def wall_time(self):
        return self._last


class _Line:
    def __init__(self):
        self._values = iter([0, 1])
        self._waits = iter([False, True])

    def request(self, **_kwargs):
        pass

    def get_value(self):
        return next(self._values)

    def event_wait(self, _timeout):
        return next(self._waits)

    def event_read(self):
        return object()

    def release(self):
        pass


class _Chip:
    def __init__(self, line):
        self._line = line

    def get_line(self, _offset):
        return self._line

    def close(self):
        pass


class _Gpiod:
    LINE_REQ_EV_RISING_EDGE = 1
    LINE_REQ_EV_FALLING_EDGE = 2
    LINE_REQ_EV_BOTH_EDGES = 3

    def __init__(self):
        self._line = _Line()

    def Chip(self, _name):
        return _Chip(self._line)


class GpioMetricsTests(unittest.TestCase):
    def test_richer_gpio_api_reports_event_loop_metrics(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=4,
                max_events=1,
            )
            result = run_gpio_edge_logger_with_result(
                config,
                clock=_Clock(),
                gpiod_module=_Gpiod(),
            )

        self.assertEqual(2, len(result.files))
        self.assertTrue(result.metrics.initial_value_written)
        self.assertEqual(1, result.metrics.edge_events_written)
        self.assertEqual(1, result.metrics.poll_timeouts)
        self.assertAlmostEqual(0.2, result.metrics.elapsed_seconds)


if __name__ == "__main__":
    unittest.main()
