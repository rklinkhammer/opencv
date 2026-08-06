"""Deterministic tests for the version-neutral GPIO event loop."""

import tempfile
import unittest
from pathlib import Path
from threading import Event

from gpio_capture.gpio_edge import GpioEdgeConfig
from gpio_capture.runner_common import run_event_logger


class _Clock:
    def __init__(self, monotonic_values, wall_time=1_700_000_000.0):
        self._monotonic_values = iter(monotonic_values)
        self._wall_time = wall_time

    def monotonic(self):
        return next(self._monotonic_values)

    def wall_time(self):
        return self._wall_time


class _Source:
    def __init__(self, values, events):
        self._values = iter(values)
        self._events = iter(events)
        self.wait_calls = 0

    def read_value(self):
        return next(self._values)

    def wait_event(self, _timeout_seconds):
        self.wait_calls += 1
        return next(self._events)

    def event_time(self, _event, clock):
        return clock.wall_time()


class GpioCommonLoopTests(unittest.TestCase):
    def test_max_events_writes_one_initial_file_then_exact_event_count(self):
        source = _Source(values=[0, 1, 0], events=[object(), object()])
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=4,
                max_events=2,
            )
            result = run_event_logger(
                config,
                source=source,
                clock=_Clock([0.0, 0.1, 0.2]),
                stop_event=None,
            )

            contents = [path.read_text(encoding="utf-8") for path in result]

        self.assertEqual(["0\n", "1\n", "0\n"], contents)
        self.assertEqual(2, source.wait_calls)

    def test_duration_stop_writes_initial_file_without_polling(self):
        source = _Source(values=[1], events=[])
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=4,
                duration_seconds=1.0,
            )
            result = run_event_logger(
                config,
                source=source,
                clock=_Clock([0.0, 1.0]),
                stop_event=None,
            )

        self.assertEqual(1, len(result))
        self.assertEqual(0, source.wait_calls)

    def test_external_stop_writes_initial_file_without_polling(self):
        stop_event = Event()
        stop_event.set()
        source = _Source(values=[1], events=[])
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=4,
            )
            result = run_event_logger(
                config,
                source=source,
                clock=_Clock([0.0, 0.1]),
                stop_event=stop_event,
            )

        self.assertEqual(1, len(result))
        self.assertEqual(0, source.wait_calls)


if __name__ == "__main__":
    unittest.main()
