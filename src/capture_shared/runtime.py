"""Shared runtime loop helpers for duration and cooperative stop semantics."""

from __future__ import annotations

from threading import Event
from typing import Callable


def should_stop(
    *,
    start_time: float,
    duration_seconds: float | None,
    stop_event: Event | None,
    time_provider: Callable[[], float],
) -> bool:
    if stop_event is not None and stop_event.is_set():
        return True
    if duration_seconds is not None:
        elapsed = time_provider() - start_time
        if elapsed >= duration_seconds:
            return True
    return False
