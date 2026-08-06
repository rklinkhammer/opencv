"""libgpiod v1 runner implementation for GPIO edge logging."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from capture_shared.clocks import Clock
from capture_shared.errors import ConfigurationError, GpioError

from .runner_common import run_event_logger

if TYPE_CHECKING:
    from .gpio_edge import GpioEdgeConfig


def event_request_type(edge: str, gpiod_module: Any) -> int:
    """Map edge name to libgpiod v1 request constant."""

    normalized = edge.lower().strip()
    mapping = {
        "rising": gpiod_module.LINE_REQ_EV_RISING_EDGE,
        "falling": gpiod_module.LINE_REQ_EV_FALLING_EDGE,
        "both": gpiod_module.LINE_REQ_EV_BOTH_EDGES,
    }
    if normalized not in mapping:
        raise ConfigurationError("edge must be one of: rising, falling, both")
    return mapping[normalized]


def run_v1(
    config: GpioEdgeConfig,
    *,
    clock: Clock,
    gpiod_module: Any,
    stop_event,
) -> list[Path]:
    """Run GPIO edge logging using libgpiod v1 APIs."""

    request_type = event_request_type(config.edge, gpiod_module)

    chip = None
    try:
        chip = gpiod_module.Chip(config.chip_name)
        line = chip.get_line(config.line_offset)
    except Exception as exc:
        if chip is not None:
            try:
                chip.close()
            except Exception:  # pragma: no cover - defensive cleanup
                pass
        raise GpioError(
            f"Unable to access GPIO line {config.line_offset} on {config.chip_name}: {exc}"
        ) from exc

    try:
        request_kwargs = {"consumer": config.consumer, "type": request_type}
        realtime_flag = getattr(gpiod_module, "LINE_REQ_FLAG_EVENT_CLOCK_REALTIME", None)
        if realtime_flag is not None:
            request_kwargs["flags"] = realtime_flag
        try:
            line.request(**request_kwargs)
        except Exception as exc:
            raise GpioError(
                f"Unable to request GPIO line {config.line_offset} on {config.chip_name}: {exc}"
            ) from exc

        class V1EdgeSource:
            """Adapt one requested libgpiod v1 line to the common event source."""

            def read_value(self) -> int:
                """Read the v1 line value and normalize it to an integer."""

                return int(line.get_value())

            def wait_event(self, timeout_seconds: float) -> Any | None:
                """Wait for a v1 edge and read it when the line signals readiness."""

                return line.event_read() if line.event_wait(timeout_seconds) else None

            def event_time(self, event: Any, active_clock: Clock) -> float:
                """Use realtime event fields when requested, otherwise use wall time."""

                if realtime_flag is None:
                    return active_clock.wall_time()
                timestamp = float(getattr(event, "sec", 0)) + (
                    float(getattr(event, "nsec", 0)) / 1e9
                )
                return timestamp if timestamp > 0 else active_clock.wall_time()

        return run_event_logger(
            config,
            source=V1EdgeSource(),
            clock=clock,
            stop_event=stop_event,
        )
    finally:
        try:
            line.release()
        except Exception:  # pragma: no cover - defensive cleanup
            pass
        try:
            chip.close()
        except Exception:  # pragma: no cover - defensive cleanup
            pass
