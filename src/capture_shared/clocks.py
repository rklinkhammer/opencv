"""Explicit wall-clock and monotonic time sources for capture workflows."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Callable, Protocol


class Clock(Protocol):
    def wall_time(self) -> float: ...

    def monotonic(self) -> float: ...


@dataclass(frozen=True)
class SystemClock:
    def wall_time(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.perf_counter()


@dataclass(frozen=True)
class FunctionClock:
    wall_provider: Callable[[], float]
    monotonic_provider: Callable[[], float]

    def wall_time(self) -> float:
        return self.wall_provider()

    def monotonic(self) -> float:
        return self.monotonic_provider()
