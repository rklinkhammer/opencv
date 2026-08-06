"""Explicit wall-clock and monotonic time sources for capture workflows."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    """Wall and monotonic clocks required by capture loops."""

    def wall_time(self) -> float: ...

    def monotonic(self) -> float: ...


class SystemClock:
    """Production clock backed by the standard library."""

    def wall_time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.perf_counter()
