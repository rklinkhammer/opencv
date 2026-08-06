"""Shared GPIO event logging control flow independent of libgpiod version."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from capture_shared.clocks import Clock
from capture_shared.output import recover_stale_outputs
from capture_shared.runtime import should_stop

from .core import write_value_file


class EdgeSource(Protocol):
    def read_value(self) -> int: ...

    def wait_event(self, timeout_seconds: float) -> Any | None: ...

    def event_time(self, event: Any, clock: Clock) -> float: ...


def run_event_logger(config, *, source: EdgeSource, clock: Clock, stop_event) -> list[Path]:
    written = []
    recover_stale_outputs(config.output_dir)
    event_count = 0
    start_time = clock.monotonic()
    written.append(
        write_value_file(
            output_dir=config.output_dir,
            line_offset=config.line_offset,
            tag=config.tag,
            capture_time=clock.wall_time(),
            gpio_value=source.read_value(),
        )
    )
    if config.max_events == 0:
        return written

    while True:
        current_time = clock.monotonic()
        if should_stop(
            start_time=start_time,
            duration_seconds=config.duration_seconds,
            stop_event=stop_event,
            time_provider=lambda: current_time,
        ):
            break
        event = source.wait_event(config.poll_timeout_ms / 1000.0)
        if event is None:
            continue
        written.append(
            write_value_file(
                output_dir=config.output_dir,
                line_offset=config.line_offset,
                tag=config.tag,
                capture_time=source.event_time(event, clock),
                gpio_value=source.read_value(),
            )
        )
        event_count += 1
        if config.max_events is not None and event_count >= config.max_events:
            break
    return written
