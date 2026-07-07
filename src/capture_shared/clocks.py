"""Explicit wall-clock and monotonic time sources for capture workflows."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol


class Clock(Protocol):
    """Supply timestamps and elapsed-time readings from distinct clock domains."""

    def wall_time(self) -> float:
        """Return Unix wall time for human-readable artifact timestamps."""

        ...

    def monotonic(self) -> float:
        """Return monotonic time for deadlines and elapsed-duration control."""

        ...


@dataclass(frozen=True)
class SystemClock:
    """Production clock backed by the system wall and performance counters."""

    def wall_time(self) -> float:
        """Return the current system Unix timestamp."""

        return time.time()

    def monotonic(self) -> float:
        """Return the current high-resolution monotonic counter."""

        return time.perf_counter()


@dataclass(frozen=True)
class FunctionClock:
    """Clock adapter used by tests and compatibility call sites."""

    wall_provider: Callable[[], float]
    monotonic_provider: Callable[[], float]

    def wall_time(self) -> float:
        """Delegate wall-time reads to the injected provider."""

        return self.wall_provider()

    def monotonic(self) -> float:
        """Delegate monotonic reads to the injected provider."""

        return self.monotonic_provider()
