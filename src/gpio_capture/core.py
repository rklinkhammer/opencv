"""Shared GPIO edge-loop primitives used by versioned runners."""

from __future__ import annotations

from pathlib import Path
from capture_shared.clocks import Clock

from capture_shared.runtime import should_stop
from capture_shared.output import write_unique_text
from capture_shared.timestamps import format_filename_timestamp


def sanitize_tag(tag: str) -> str:
    """Normalize free-form tags into filesystem-safe filename components."""

    safe_tag = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in tag).strip("_")
    return safe_tag if safe_tag else "gpio"


def write_value_file(
    *,
    output_dir: Path,
    line_offset: int,
    tag: str,
    capture_time: float,
    gpio_value: int,
) -> Path:
    """Write one timestamped GPIO value file and return its path."""

    normalized_tag = sanitize_tag(tag)
    file_stem = f"gpio_{normalized_tag}_{line_offset:04d}_{format_filename_timestamp(capture_time)}"
    return write_unique_text(output_dir, file_stem, "txt", f"{gpio_value}\n")


def should_stop_loop(
    *,
    start_time: float,
    config,
    stop_event,
    clock: Clock,
    current_time: float | None = None,
) -> bool:
    """Evaluate common loop stop conditions for GPIO workers."""

    return should_stop(
        start_time=start_time,
        duration_seconds=config.duration_seconds,
        stop_event=stop_event,
        time_provider=clock.monotonic if current_time is None else lambda: current_time,
    )
