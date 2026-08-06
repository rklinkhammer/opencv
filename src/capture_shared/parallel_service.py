"""Run camera and GPIO capture together."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Thread
import time
from typing import Callable

from capture_shared.errors import CaptureError, ConfigurationError
from camera_capture.models import CaptureConfig
from gpio_capture.gpio_edge import GpioEdgeConfig

_GPIO_JOIN_GRACE_SECONDS = 1.0


@dataclass(frozen=True)
class GpioJob:
    """One GPIO line monitored alongside camera capture."""

    chip: str
    line_offset: int
    tag: str
    edge: str

    @property
    def key(self) -> str:
        return f"{self.chip}:{self.line_offset}:{self.tag}"


@dataclass(frozen=True)
class WorkerOutcome:
    """Files or failure reported by one GPIO worker."""

    key: str
    files: tuple[Path, ...] = ()
    error: Exception | None = None


@dataclass(frozen=True)
class ParallelOutcome:
    """Combined camera and GPIO results from one parallel run."""

    camera_output_dir: Path
    images: tuple[Path, ...]
    camera_error: Exception | None
    workers: tuple[WorkerOutcome, ...]
    elapsed_seconds: float


def execute_parallel_capture(
    *,
    camera_config: CaptureConfig,
    gpio_jobs: list[GpioJob],
    gpio_output_dir: Path | None,
    duration_seconds: float,
    gpio_poll_timeout_ms: int,
    capture_fn: Callable[[CaptureConfig], list[Path]],
    gpio_fn: Callable[..., list[Path]],
) -> ParallelOutcome:
    """Run camera capture with one worker per GPIO job and collect all outcomes."""
    if gpio_jobs and gpio_output_dir is None:
        raise ConfigurationError("gpio_output_dir is required when GPIO jobs are configured")

    started = time.perf_counter()
    stop_event = Event()
    results: list[list[Path] | Exception | None] = [None] * len(gpio_jobs)

    def run_gpio(index: int, job: GpioJob) -> None:
        assert gpio_output_dir is not None
        config = GpioEdgeConfig(
            output_dir=gpio_output_dir,
            chip_name=job.chip,
            line_offset=job.line_offset,
            tag=job.tag,
            edge=job.edge,
            duration_seconds=duration_seconds,
            poll_timeout_ms=gpio_poll_timeout_ms,
        )
        try:
            results[index] = gpio_fn(config, stop_event=stop_event)
        except Exception as exc:
            results[index] = exc

    threads = [
        Thread(
            target=run_gpio,
            args=(index, job),
            name=f"gpio-edge-{job.tag}-{job.line_offset}",
            daemon=True,
        )
        for index, job in enumerate(gpio_jobs)
    ]
    for thread in threads:
        thread.start()

    images: list[Path] = []
    camera_error: Exception | None = None
    try:
        images = capture_fn(camera_config)
    except Exception as exc:
        camera_error = exc
    finally:
        stop_event.set()
        for thread in threads:
            thread.join(timeout=(gpio_poll_timeout_ms / 1000.0) + _GPIO_JOIN_GRACE_SECONDS)

    outcomes: list[WorkerOutcome] = []
    for job, thread, raw in zip(gpio_jobs, threads, results):
        if thread.is_alive():
            raw = CaptureError("worker did not stop before the join timeout")
        elif raw is None:
            raw = CaptureError("worker exited without reporting a result")
        if isinstance(raw, Exception):
            outcomes.append(WorkerOutcome(key=job.key, error=raw))
        else:
            outcomes.append(WorkerOutcome(key=job.key, files=tuple(raw)))

    return ParallelOutcome(
        camera_output_dir=camera_config.output_dir,
        images=tuple(images),
        camera_error=camera_error,
        workers=tuple(sorted(outcomes, key=lambda outcome: outcome.key)),
        elapsed_seconds=time.perf_counter() - started,
    )
