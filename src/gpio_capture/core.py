"""Shared GPIO edge-loop primitives used by versioned runners."""

from __future__ import annotations

from pathlib import Path

from capture_shared.output import write_unique_text
from capture_shared.timestamps import format_filename_timestamp


def sanitize_tag(tag: str) -> str:
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
    normalized_tag = sanitize_tag(tag)
    file_stem = f"gpio_{normalized_tag}_{line_offset:04d}_{format_filename_timestamp(capture_time)}"
    return write_unique_text(output_dir, file_stem, "txt", f"{gpio_value}\n")
