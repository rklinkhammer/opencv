"""Presentation-free orchestration for parallel camera and GPIO capture.

Architecture:
- Accepts pure callables for camera and GPIO execution so orchestration stays
    transport-agnostic and test-friendly.
- Owns thread lifecycle and cooperative stop coordination for GPIO workers.
- Returns structured outcomes; presentation and CLI formatting are handled by
    callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread
import time
from typing import Callable

from capture_shared.errors import ParallelExecutionError
from camera_capture.models import CaptureConfig
from gpio_capture.gpio_edge import GpioEdgeConfig

_GPIO_JOIN_GRACE_SECONDS = 1.0


@dataclass(frozen=True)
class GpioJob:
    """Declarative GPIO worker request produced by CLI parsing."""

    chip: str
    line_offset: int
    tag: str
    edge: str

    @property
    def key(self) -> str:
        """Stable worker identifier used in summaries and result mapping."""

        return f"{self.chip}:{self.line_offset}:{self.tag}"


@dataclass(frozen=True)
class WorkerOutcome:
    """Result payload for one GPIO worker."""

    key: str
    files: tuple[Path, ...] = ()
    error: Exception | None = None


@dataclass(frozen=True)
class ParallelOutcome:
    """Aggregate outcome returned by the parallel orchestration service."""

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
    """Execute all workers and return structured results without printing.

    Execution flow:
    1. Start GPIO worker threads.
    2. Run camera capture on the calling thread.
    3. Signal cooperative stop and join workers.
    4. Normalize worker outcomes for presentation-layer consumers.
    """

    started = time.perf_counter()
    stop_event = Event()
    raw_results: dict[str, list[Path] | Exception] = {}
    results_lock = Lock()

    def run_gpio(job: GpioJob) -> None:
        """Execute one GPIO job and capture either its paths or raised exception."""

        config = GpioEdgeConfig(
            output_dir=gpio_output_dir,  # type: ignore[arg-type]
            chip_name=job.chip,
            line_offset=job.line_offset,
            tag=job.tag,
            edge=job.edge,
            duration_seconds=duration_seconds,
            poll_timeout_ms=gpio_poll_timeout_ms,
        )
        try:
            result: list[Path] | Exception = gpio_fn(config, stop_event=stop_event)
        except Exception as exc:
            result = exc
        with results_lock:
            raw_results[job.key] = result

    threads = [
        Thread(
            target=run_gpio,
            args=(job,),
            name=f"gpio-edge-{job.tag}-{job.line_offset}",
            daemon=True,
        )
        for job in gpio_jobs
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

    with results_lock:
        snapshot = dict(raw_results)
    outcomes: list[WorkerOutcome] = []
    for job, thread in zip(gpio_jobs, threads):
        raw = snapshot.get(job.key)
        if thread.is_alive():
            raw = ParallelExecutionError("worker did not stop before the join timeout")
        elif raw is None:
            raw = ParallelExecutionError("worker exited without reporting a result")
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
