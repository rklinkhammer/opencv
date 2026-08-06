"""Minimal frame transformation boundary for camera capture orchestration."""

from __future__ import annotations

from typing import Protocol

from .models import FrameRecord


class FrameTransform(Protocol):
    def apply(self, frame: FrameRecord) -> FrameRecord: ...


class IdentityFrameTransform:
    def apply(self, frame: FrameRecord) -> FrameRecord:
        return frame
