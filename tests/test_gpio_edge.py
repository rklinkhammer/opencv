"""Unit tests for GPIO edge logging and versioned runner behavior.

This module exercises filename generation, value persistence, event loops, and
compatibility expectations across libgpiod integration paths.
"""

import tempfile
import unittest
from pathlib import Path

from capture_shared.errors import ConfigurationError
from gpio_capture.core import write_value_file
from gpio_capture.gpio_edge import GpioEdgeConfig, run_gpio_edge_logger


class _SequenceClock:
    def __init__(self, values):
        self._values = iter(values)
        self._last = 0.0

    def monotonic(self):
        self._last = next(self._values)
        return self._last

    def wall_time(self):
        return self._last


class _FakeEvent:
    def __init__(self, sec: int, nsec: int):
        self.sec = sec
        self.nsec = nsec


class _FakeLine:
    def __init__(self, values: list[int], events: list[_FakeEvent], waits: list[bool]):
        self._values = values
        self._events = events
        self._waits = waits
        self.request_kwargs = None
        self.released = False

    def request(self, **kwargs):
        self.request_kwargs = kwargs

    def get_value(self) -> int:
        if self._values:
            return self._values.pop(0)
        return 0

    def event_wait(self, _timeout_seconds: float) -> bool:
        if self._waits:
            return self._waits.pop(0)
        return False

    def event_read(self) -> _FakeEvent:
        return self._events.pop(0)

    def release(self) -> None:
        self.released = True


class _FakeChip:
    def __init__(self, line: _FakeLine):
        self._line = line
        self.closed = False

    def get_line(self, _line_offset: int) -> _FakeLine:
        return self._line

    def close(self) -> None:
        self.closed = True


class _FakeGpiod:
    LINE_REQ_EV_RISING_EDGE = 1
    LINE_REQ_EV_FALLING_EDGE = 2
    LINE_REQ_EV_BOTH_EDGES = 3

    def __init__(self, chip: _FakeChip):
        self._chip = chip

    def Chip(self, _chip_name: str) -> _FakeChip:
        return self._chip


class GpioEdgeTests(unittest.TestCase):
    def test_same_millisecond_events_create_distinct_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir)
            first = write_value_file(
                output_dir=output_dir,
                line_offset=4,
                tag="door",
                capture_time=1700000000.123,
                gpio_value=0,
            )
            second = write_value_file(
                output_dir=output_dir,
                line_offset=4,
                tag="door",
                capture_time=1700000000.123,
                gpio_value=1,
            )

            self.assertNotEqual(first, second)
            self.assertEqual("0\n", first.read_text(encoding="utf-8"))
            self.assertEqual("1\n", second.read_text(encoding="utf-8"))

    def test_initial_file_is_written_at_startup(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_line = _FakeLine(values=[1], events=[], waits=[])
            fake_chip = _FakeChip(fake_line)
            fake_gpiod = _FakeGpiod(fake_chip)

            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=17,
                edge="both",
                max_events=0,
            )

            written = run_gpio_edge_logger(
                config,
                clock=_SequenceClock([1700000000.123]),
                gpiod_module=fake_gpiod,
            )

            self.assertEqual(1, len(written))
            first_file = written[0]
            self.assertTrue(first_file.name.startswith("gpio_gpio_0017_"))
            self.assertEqual("1\n", first_file.read_text(encoding="utf-8"))
            self.assertTrue(fake_line.released)
            self.assertTrue(fake_chip.closed)

    def test_event_writes_new_file_with_gpio_value(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_line = _FakeLine(
                values=[0, 1],
                events=[_FakeEvent(sec=1700000001, nsec=456000000)],
                waits=[True],
            )
            fake_chip = _FakeChip(fake_line)
            fake_gpiod = _FakeGpiod(fake_chip)

            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=4,
                edge="rising",
                max_events=1,
            )
            times = iter([1700000000.0, 1700000000.1, 1700000001.456])

            written = run_gpio_edge_logger(
                config,
                clock=_SequenceClock(times),
                gpiod_module=fake_gpiod,
            )

            self.assertEqual(2, len(written))
            self.assertEqual("0\n", written[0].read_text(encoding="utf-8"))
            self.assertEqual("1\n", written[1].read_text(encoding="utf-8"))
            self.assertIn("gpio_gpio_0004_", written[0].name)
            self.assertEqual(
                {"consumer": "camera-gpio-edge", "type": _FakeGpiod.LINE_REQ_EV_RISING_EDGE},
                fake_line.request_kwargs,
            )

    def test_monotonic_event_timestamp_falls_back_to_wall_clock(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_line = _FakeLine(
                values=[0, 1],
                events=[_FakeEvent(sec=1234, nsec=0)],
                waits=[True],
            )
            fake_gpiod = _FakeGpiod(_FakeChip(fake_line))
            times = iter([1700000000.0, 1700000000.1, 1700000001.0])
            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=4,
                max_events=1,
            )

            written = run_gpio_edge_logger(
                config,
                clock=_SequenceClock(times),
                gpiod_module=fake_gpiod,
            )

            self.assertIn("2023", written[1].name)
            self.assertNotIn("1970", written[1].name)

    def test_tag_is_added_to_output_filename(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            fake_line = _FakeLine(values=[1], events=[], waits=[])
            fake_chip = _FakeChip(fake_line)
            fake_gpiod = _FakeGpiod(fake_chip)

            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=21,
                tag="door_sensor",
                max_events=0,
            )

            written = run_gpio_edge_logger(
                config,
                clock=_SequenceClock([1700000000.000]),
                gpiod_module=fake_gpiod,
            )

            self.assertEqual(1, len(written))
            self.assertIn("gpio_door_sensor_0021_", written[0].name)

    def test_validation_rejects_negative_line_offset(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=-1,
            )

            fake_line = _FakeLine(values=[0], events=[], waits=[])
            fake_chip = _FakeChip(fake_line)
            fake_gpiod = _FakeGpiod(fake_chip)

            with self.assertRaises(ConfigurationError):
                run_gpio_edge_logger(config, gpiod_module=fake_gpiod)

    def test_validation_rejects_non_positive_duration(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            config = GpioEdgeConfig(
                output_dir=Path(tmp_dir),
                chip_name="gpiochip0",
                line_offset=1,
                duration_seconds=0,
            )

            fake_line = _FakeLine(values=[0], events=[], waits=[])
            fake_chip = _FakeChip(fake_line)
            fake_gpiod = _FakeGpiod(fake_chip)

            with self.assertRaises(ConfigurationError):
                run_gpio_edge_logger(config, gpiod_module=fake_gpiod)


if __name__ == "__main__":
    unittest.main()
