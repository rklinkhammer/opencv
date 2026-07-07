"""Shared GPIO event logging control flow independent of libgpiod version."""

from __future__ import annotations

from typing import Any, Protocol

from capture_shared.clocks import Clock
from capture_shared.output import recover_stale_outputs

from .core import should_stop_loop, write_value_file
from .models import GpioMetrics, GpioRunResult


class EdgeSource(Protocol):
    """Adapter contract for version-specific GPIO event sources.

    Runner implementations provide this interface so shared loop logic can stay
    independent from libgpiod version details.
    """

    def read_value(self) -> int:
        """Read and normalize the current logical GPIO line value."""

        ...

    def wait_event(self, timeout_seconds: float) -> Any | None:
        """Wait up to the timeout and return one backend event when available."""

        ...

    def event_time(self, event: Any, clock: Clock) -> float:
        """Return a wall-clock timestamp safe for artifact naming."""

        ...


def run_event_logger(config, *, source: EdgeSource, clock: Clock, stop_event) -> GpioRunResult:
    """Write GPIO states and return paths with version-neutral metrics."""

    written = []
    recover_stale_outputs(config.output_dir)
    event_count = 0
    poll_timeouts = 0
    start_time = clock.monotonic()
    last_time = start_time
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
        return GpioRunResult(
            files=tuple(written),
            metrics=GpioMetrics(
                initial_value_written=True,
                edge_events_written=0,
                poll_timeouts=0,
                elapsed_seconds=0.0,
            ),
        )

    while True:
        last_time = clock.monotonic()
        if should_stop_loop(
            start_time=start_time,
            config=config,
            stop_event=stop_event,
            clock=clock,
            current_time=last_time,
        ):
            break
        event = source.wait_event(config.poll_timeout_ms / 1000.0)
        if event is None:
            poll_timeouts += 1
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
    return GpioRunResult(
        files=tuple(written),
        metrics=GpioMetrics(
            initial_value_written=True,
            edge_events_written=event_count,
            poll_timeouts=poll_timeouts,
            elapsed_seconds=max(0.0, last_time - start_time),
        ),
    )
