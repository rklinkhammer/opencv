"""Shared timestamp formatting helpers used by capture modules."""

from __future__ import annotations

from datetime import datetime


def capture_datetime(capture_time: float) -> datetime:
    """Convert a capture timestamp into a timezone-aware datetime."""

    return datetime.fromtimestamp(capture_time).astimezone()


def format_filename_timestamp(capture_time: float) -> str:
    """Format a cross-platform-safe timestamp string for filenames."""

    dt = capture_datetime(capture_time)
    return f"{dt.strftime('%Y%m%dT%H%M%S')}_{dt.microsecond // 1000:03d}{dt.strftime('%z')}"


def format_iso_timestamp(capture_time: float) -> str:
    """Format a capture timestamp for overlays and logs."""

    dt = capture_datetime(capture_time)
    return dt.isoformat(timespec="milliseconds")
