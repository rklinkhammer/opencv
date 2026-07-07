"""Immutable runtime result models for GPIO edge logging."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GpioMetrics:
    """Structured counters describing one GPIO edge logging run."""

    initial_value_written: bool
    edge_events_written: int
    poll_timeouts: int
    elapsed_seconds: float


@dataclass(frozen=True)
class GpioRunResult:
    """Durable GPIO value paths and metrics from the richer GPIO API."""

    files: tuple[Path, ...]
    metrics: GpioMetrics
