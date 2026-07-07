"""Compatibility tests for libgpiod v1 and v2 runner adapters."""

import unittest

from capture_shared.errors import ConfigurationError
from gpio_capture.runner_v1 import event_request_type
from gpio_capture.runner_v2 import (
    coerce_gpio_value,
    event_request_type_v2,
    extract_event_time,
)


class _V1Gpiod:
    LINE_REQ_EV_RISING_EDGE = 10
    LINE_REQ_EV_FALLING_EDGE = 20
    LINE_REQ_EV_BOTH_EDGES = 30


class _V2Gpiod:
    class line:
        class Edge:
            RISING = "rising-enum"
            FALLING = "falling-enum"
            BOTH = "both-enum"

        class Value:
            ACTIVE = "active-enum"
            INACTIVE = "inactive-enum"


class GpioRunnerCompatibilityTests(unittest.TestCase):
    def test_v1_edge_mapping(self):
        expected = {
            "rising": _V1Gpiod.LINE_REQ_EV_RISING_EDGE,
            "falling": _V1Gpiod.LINE_REQ_EV_FALLING_EDGE,
            "both": _V1Gpiod.LINE_REQ_EV_BOTH_EDGES,
        }

        for edge, request_type in expected.items():
            with self.subTest(edge=edge):
                self.assertEqual(request_type, event_request_type(edge, _V1Gpiod))

        with self.assertRaises(ConfigurationError):
            event_request_type("invalid", _V1Gpiod)

    def test_v2_edge_mapping(self):
        expected = {
            "rising": _V2Gpiod.line.Edge.RISING,
            "falling": _V2Gpiod.line.Edge.FALLING,
            "both": _V2Gpiod.line.Edge.BOTH,
        }

        for edge, request_type in expected.items():
            with self.subTest(edge=edge):
                self.assertEqual(request_type, event_request_type_v2(edge, _V2Gpiod))

        with self.assertRaises(ConfigurationError):
            event_request_type_v2("invalid", _V2Gpiod)

    def test_v2_value_coercion(self):
        cases = (
            (_V2Gpiod.line.Value.ACTIVE, 1),
            (_V2Gpiod.line.Value.INACTIVE, 0),
            (1, 1),
            (0, 0),
        )

        for value, expected in cases:
            with self.subTest(value=value):
                self.assertEqual(expected, coerce_gpio_value(value, _V2Gpiod))

    def test_v2_monotonic_timestamp_falls_back_to_wall_clock(self):
        event = type("Event", (), {"timestamp_ns": 1_234_000_000})()

        timestamp = extract_event_time(
            event,
            lambda: 1_700_000_000.5,
            event_clock_is_realtime=False,
        )

        self.assertEqual(1_700_000_000.5, timestamp)

    def test_v2_realtime_nanosecond_timestamp_is_used(self):
        event = type("Event", (), {"timestamp_ns": 1_700_000_000_250_000_000})()

        timestamp = extract_event_time(
            event,
            lambda: 99.0,
            event_clock_is_realtime=True,
        )

        self.assertAlmostEqual(1_700_000_000.25, timestamp, places=6)

    def test_v2_realtime_sec_nsec_timestamp_is_used(self):
        event = type("Event", (), {"sec": 1_700_000_000, "nsec": 750_000_000})()

        timestamp = extract_event_time(
            event,
            lambda: 99.0,
            event_clock_is_realtime=True,
        )

        self.assertEqual(1_700_000_000.75, timestamp)


if __name__ == "__main__":
    unittest.main()
