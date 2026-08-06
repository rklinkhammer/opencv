"""Asynchronous GPIO edge logger using libgpiod.

Writes one timestamped text file at startup with the current GPIO value, then
writes a new timestamped text file for each edge event.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import threading
from typing import Any

from capture_shared.clocks import Clock, SystemClock
from capture_shared.errors import ConfigurationError, GpioError

from .runner_v1 import run_v1
from .runner_v2 import run_v2


@dataclass(frozen=True)
class GpioEdgeConfig:
    output_dir: Path
    chip_name: str
    line_offset: int
    tag: str = "gpio"
    edge: str = "both"
    consumer: str = "camera-gpio-edge"
    max_events: int | None = None
    poll_timeout_ms: int = 1000
    duration_seconds: float | None = None


def validate_gpio_config(config: GpioEdgeConfig) -> None:
    if config.output_dir is None:
        raise ConfigurationError("output_dir must be provided")
    if not config.chip_name.strip():
        raise ConfigurationError("chip_name must not be empty")
    if config.line_offset < 0:
        raise ConfigurationError("line_offset must be >= 0")
    if not config.tag.strip():
        raise ConfigurationError("tag must not be empty")
    if config.edge.lower().strip() not in {"rising", "falling", "both"}:
        raise ConfigurationError("edge must be one of: rising, falling, both")
    if config.max_events is not None and config.max_events < 0:
        raise ConfigurationError("max_events must be >= 0 when provided")
    if config.poll_timeout_ms <= 0:
        raise ConfigurationError("poll_timeout_ms must be > 0")
    if config.duration_seconds is not None and config.duration_seconds <= 0:
        raise ConfigurationError("duration_seconds must be > 0 when provided")


def _import_gpiod() -> Any:
    try:
        import gpiod
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise GpioError(
            "libgpiod Python bindings are required. Install 'gpiod' in your active venv "
            "(or system package 'python3-libgpiod')."
        ) from exc
    return gpiod


def _is_gpiod_v2(gpiod_module: Any) -> bool:
    return all(hasattr(gpiod_module, attr) for attr in ["request_lines", "LineSettings", "line"])


def run_gpio_edge_logger(
    config: GpioEdgeConfig,
    *,
    clock: Clock | None = None,
    gpiod_module: Any | None = None,
    stop_event: threading.Event | None = None,
) -> list[Path]:
    validate_gpio_config(config)

    if gpiod_module is None:
        gpiod_module = _import_gpiod()

    active_clock = clock or SystemClock()

    if _is_gpiod_v2(gpiod_module):
        return run_v2(
            config,
            clock=active_clock,
            gpiod_module=gpiod_module,
            stop_event=stop_event,
        )

    return run_v1(
        config,
        clock=active_clock,
        gpiod_module=gpiod_module,
        stop_event=stop_event,
    )
