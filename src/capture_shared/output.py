"""Collision-safe output path allocation and atomic text persistence."""

from __future__ import annotations

from pathlib import Path
import os
import time
from uuid import uuid4

from capture_shared.errors import CaptureError


def reserve_unique_path(output_dir: Path, file_stem: str, extension: str) -> Path:
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CaptureError(f"Unable to create output directory {output_dir}: {exc}") from exc
    extension = extension.lstrip(".")
    sequence = 0
    while True:
        suffix = "" if sequence == 0 else f"_{sequence:04d}"
        output_path = output_dir / f"{file_stem}{suffix}.{extension}"
        try:
            output_path.touch(exist_ok=False)
            return output_path
        except FileExistsError:
            sequence += 1
        except OSError as exc:
            raise CaptureError(f"Unable to reserve output path {output_path}: {exc}") from exc


def temporary_peer_path(output_path: Path) -> Path:
    return output_path.with_name(f".{output_path.stem}.{uuid4().hex}.tmp{output_path.suffix}")


class OutputTransaction:
    def __init__(self, output_dir: Path, file_stem: str, extension: str) -> None:
        self.destination = reserve_unique_path(output_dir, file_stem, extension)
        self.temporary = temporary_peer_path(self.destination)
        self._committed = False

    def commit(self) -> Path:
        try:
            os.replace(self.temporary, self.destination)
        except OSError as exc:
            raise CaptureError(f"Unable to commit output {self.destination}: {exc}") from exc
        self._committed = True
        return self.destination

    def close(self) -> None:
        self.temporary.unlink(missing_ok=True)
        if not self._committed:
            self.destination.unlink(missing_ok=True)

    def __enter__(self) -> OutputTransaction:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def recover_stale_outputs(output_dir: Path, *, older_than_seconds: float = 3600.0) -> int:
    if not output_dir.exists():
        return 0
    cutoff = time.time() - older_than_seconds
    removed = 0
    for path in output_dir.iterdir():
        try:
            stale = path.stat().st_mtime <= cutoff
            temporary = path.name.startswith(".") and ".tmp." in path.name
            empty_reservation = path.stat().st_size == 0 and path.name.startswith(
                ("frame_", "gpio_")
            )
            if stale and (temporary or empty_reservation):
                path.unlink()
                removed += 1
        except FileNotFoundError:
            continue
    return removed


def write_unique_text(output_dir: Path, file_stem: str, extension: str, content: str) -> Path:
    output_path = reserve_unique_path(output_dir, file_stem, extension)
    try:
        output_path.write_text(content, encoding="utf-8")
        return output_path
    except OSError as exc:
        output_path.unlink(missing_ok=True)
        raise CaptureError(f"Unable to write output {output_path}: {exc}") from exc
