"""libgpiod v2 runner implementation for GPIO edge logging."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from capture_shared.clocks import Clock
from capture_shared.errors import ConfigurationError, GpioError

from .runner_common import run_event_logger

if TYPE_CHECKING:
    from .gpio_edge import GpioEdgeConfig


def event_request_type_v2(edge: str, gpiod_module: Any) -> Any:
    """Map edge name to libgpiod v2 edge enum."""

    normalized = edge.lower().strip()
    mapping = {
        "rising": gpiod_module.line.Edge.RISING,
        "falling": gpiod_module.line.Edge.FALLING,
        "both": gpiod_module.line.Edge.BOTH,
    }
    if normalized not in mapping:
        raise ConfigurationError("edge must be one of: rising, falling, both")
    return mapping[normalized]


def coerce_gpio_value(value: Any, gpiod_module: Any) -> int:
    """Coerce libgpiod value types into numeric 0/1."""

    try:
        if hasattr(gpiod_module, "line") and hasattr(gpiod_module.line, "Value"):
            if value == gpiod_module.line.Value.ACTIVE:
                return 1
            if value == gpiod_module.line.Value.INACTIVE:
                return 0
    except Exception:
        pass
    return int(value)


def extract_event_time(
    event: Any,
    time_provider: Callable[[], float],
    *,
    event_clock_is_realtime: bool = False,
) -> float:
    """Extract event timestamp from libgpiod v2 event with compatibility fallbacks."""

    # GPIO event timestamps use CLOCK_MONOTONIC unless the request explicitly
    # selects CLOCK_REALTIME. A monotonic value must never be formatted as a
    # Unix timestamp; fall back to the wall clock when realtime is unavailable.
    if not event_clock_is_realtime:
        return time_provider()

    for attr in ["timestamp_ns", "ts_ns"]:
        value = getattr(event, attr, None)
        if value is not None:
            try:
                numeric = float(value)
                if numeric > 0:
                    return numeric / 1e9
            except (TypeError, ValueError):
                pass

    sec = getattr(event, "sec", None)
    nsec = getattr(event, "nsec", None)
    if sec is not None and nsec is not None:
        try:
            combined = float(sec) + (float(nsec) / 1e9)
            if combined > 0:
                return combined
        except (TypeError, ValueError):
            pass

    return time_provider()


def run_v2(
    config: GpioEdgeConfig,
    *,
    clock: Clock,
    gpiod_module: Any,
    stop_event,
) -> list[Path]:
    """Run GPIO edge logging using libgpiod v2 APIs."""

    request_edge = event_request_type_v2(config.edge, gpiod_module)

    chip_path = config.chip_name
    if not chip_path.startswith("/dev/"):
        chip_path = f"/dev/{chip_path}"

    event_clock_is_realtime = False
    line_settings_kwargs = {"edge_detection": request_edge}
    clock_enum = getattr(gpiod_module.line, "Clock", None)
    if clock_enum is not None and hasattr(clock_enum, "REALTIME"):
        line_settings_kwargs["event_clock"] = clock_enum.REALTIME
        event_clock_is_realtime = True
    line_settings = gpiod_module.LineSettings(**line_settings_kwargs)
    try:
        request = gpiod_module.request_lines(
            chip_path,
            consumer=config.consumer,
            config={config.line_offset: line_settings},
        )
    except Exception as exc:
        raise GpioError(
            f"Unable to request GPIO line {config.line_offset} on {chip_path}: {exc}"
        ) from exc

    try:

        class V2EdgeSource:
            """Adapt one libgpiod v2 line request to the common event source."""

            def read_value(self) -> int:
                """Read and coerce the v2 enum or numeric line value to zero or one."""

                value = request.get_value(config.line_offset)
                return coerce_gpio_value(value, gpiod_module)

            def wait_event(self, timeout_seconds: float) -> Any | None:
                """Wait for v2 edge readiness and return at most one queued event."""

                if not request.wait_edge_events(timeout=timeout_seconds):
                    return None
                events = request.read_edge_events(max_events=1)
                return events[0] if events else None

            def event_time(self, event: Any, active_clock: Clock) -> float:
                """Extract realtime event time or fall back to the active wall clock."""

                return extract_event_time(
                    event,
                    active_clock.wall_time,
                    event_clock_is_realtime=event_clock_is_realtime,
                )

        return run_event_logger(
            config,
            source=V2EdgeSource(),
            clock=clock,
            stop_event=stop_event,
        )
    finally:
        try:
            request.release()
        except Exception:  # pragma: no cover - defensive cleanup
            pass
