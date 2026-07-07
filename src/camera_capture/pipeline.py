"""Minimal frame transformation boundary for camera capture orchestration."""

from __future__ import annotations

from typing import Protocol

from .models import FrameRecord


class FrameTransform(Protocol):
    """Transform a frame while preserving its capture identity and ordering."""

    def apply(self, frame: FrameRecord) -> FrameRecord:
        """Return the frame record to submit to the writer."""

        ...


class IdentityFrameTransform:
    """Default transform that preserves the captured frame unchanged."""

    def apply(self, frame: FrameRecord) -> FrameRecord:
        """Return the original immutable frame record."""

        return frame
