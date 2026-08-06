"""Explicit wall-clock and monotonic time sources for capture workflows."""

from __future__ import annotations

import time
from typing import Protocol


class Clock(Protocol):
    def wall_time(self) -> float: ...

    def monotonic(self) -> float: ...


class SystemClock:
    def wall_time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.perf_counter()
