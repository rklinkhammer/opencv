# Camera/GPIO Capture Cleanup — Implementor Prompt and PR Plan

> **Historical document:** This plan describes an earlier design and names components
> that have since been removed. See [ARCHITECTURE.md](../../ARCHITECTURE.md) for the
> current implementation.

## Purpose

Use this prompt to drive a cleanup implementation pass for the Python camera capture, GPIO edge logging, and shared runtime packages.

The objective is not to add new user-facing capture features. The objective is to make the existing codebase easier to maintain, easier to test, safer under concurrency, and better prepared for future processing stages.

The current code already has strong foundations:

- clear separation between camera capture, GPIO edge capture, shared runtime, and CLIs
- immutable runtime configuration models
- injectable clocks, OpenCV, libgpiod, sleep providers, and writer hooks
- transactional filesystem output
- asynchronous image writing
- version-specific GPIO runners behind common loop logic
- presentation-free parallel orchestration

The cleanup must preserve that style.

---

# IMPLEMENTOR PROMPT

You are implementing a cleanup pass for a Python camera/GPIO capture package.

## Repository Scope

Inspect the current repository before making changes. Focus on these modules:

- `camera_capture/__init__.py`
- `camera_capture/backends.py`
- `camera_capture/benchmarks.py`
- `camera_capture/capture.py`
- `camera_capture/cli.py`
- `camera_capture/models.py`
- `camera_capture/probe.py`
- `camera_capture/reporting.py`
- `camera_capture/session.py`
- `camera_capture/validators.py`
- `camera_capture/writer.py`
- `gpio_capture/core.py`
- `gpio_capture/gpio_edge.py`
- `gpio_capture/gpioi_cli.py` or GPIO CLI equivalent
- `gpio_capture/runner_common.py`
- `gpio_capture/runner_v1.py`
- `gpio_capture/runner_v2.py`
- `capture_shared/capture_cli.py`
- `capture_shared/clocks.py`
- `capture_shared/output.py`
- `capture_shared/parallel_cli.py`
- `capture_shared/parallel_service.py`
- `capture_shared/runtime.py`
- `capture_shared/timestamps.py`

Do not assume names are exactly final. Verify actual package layout and imports.

## Primary Cleanup Goals

Implement the cleanup incrementally, preserving behavior and command-line compatibility unless a change is explicitly justified.

Primary goals:

1. Introduce a typed exception hierarchy.
2. Make writer lifecycle and shutdown behavior explicit.
3. Introduce a backend abstraction/factory boundary for camera capture.
4. Consolidate validation so CLI/service/runtime layers do not drift.
5. Simplify `CameraSession` so it primarily owns resource lifetime.
6. Introduce a lightweight frame pipeline seam without over-engineering.
7. Add structured runtime metrics for capture, writer, and GPIO workers.
8. Expand tests around shutdown, failure injection, validation, and filesystem recovery.

Do not rewrite the entire package at once. Preserve working behavior at every PR boundary.

---

# Non-Negotiable Constraints

## Behavior Preservation

Preserve existing CLI behavior unless explicitly called out in the plan.

Existing behavior to preserve:

- fixed-duration camera capture
- OpenCV backend support
- native GStreamer backend support
- optional GStreamer pipeline string
- Jetson CSI GStreamer preset
- USB V4L2 GStreamer preset
- probe mode
- backend benchmark mode
- capture-only benchmark mode
- JPEG/PNG/BMP output extension validation
- timestamp-in-filename option
- EXIF timestamp option for JPEG/JPEG
- timestamp overlay option
- warmup frame behavior
- asynchronous writer behavior
- GPIO initial-value file
- GPIO edge value files
- libgpiod v1 and v2 support
- parallel camera + GPIO execution
- cooperative GPIO shutdown through stop event
- atomic/transactional output behavior

## Architecture Preservation

Preserve these good design principles:

- immutable dataclasses for configuration/result records where practical
- dependency injection for clocks, OpenCV, libgpiod, sleep functions, and IO hooks
- no global mutable runtime state
- CLIs parse/validate/present; services perform work
- filesystem writes use transactional or collision-safe helpers
- version-specific GPIO logic remains isolated from common event-loop logic
- tests should not require real cameras or real GPIO hardware

## Avoid Overreach

Do not introduce:

- async/await rewrite
- multiprocessing rewrite
- new GUI/dashboard
- database persistence
- cloud upload
- GraphX integration
- hardware-specific assumptions beyond existing OpenCV/GStreamer/libgpiod behavior
- broad package renaming unless needed for correctness

---

# Recommended PR Plan

## PR0 — Baseline Characterization and Safety Tests

### Goal

Create a safety net before refactoring.

### Tasks

- Add or update tests that characterize current behavior.
- Cover config validation success/failure cases.
- Cover CLI config construction.
- Cover output transaction commit and cleanup behavior.
- Cover stale output recovery for temporary files and empty reservations.
- Cover timestamp formatting deterministically using fixed timestamps.
- Cover writer success path with fake `cv2.imwrite` and fake EXIF writer.
- Cover writer failure path when `imwrite` returns false.
- Cover camera capture loop with fake capture object and fake clock.
- Cover GPIO common loop with fake edge source.
- Cover parallel service success/failure behavior with fake workers.

### Acceptance Criteria

- Tests pass without real camera hardware.
- Tests pass without real GPIO hardware.
- Tests document current behavior before structural refactors.
- No production behavior changes beyond testability fixes.

---

## PR1 — Typed Exception Hierarchy

### Goal

Replace generic `RuntimeError`/`ValueError` usage where it represents known domain failures, while preserving user-facing CLI output.

### Proposed API

Create a module such as:

```python
# capture_shared/errors.py

class CaptureSystemError(Exception):
    """Base class for camera/GPIO capture package errors."""

class ConfigurationError(CaptureSystemError): ...
class BackendError(CaptureSystemError): ...
class CameraOpenError(BackendError): ...
class WriterError(CaptureSystemError): ...
class WriterTimeoutError(WriterError): ...
class OutputError(CaptureSystemError): ...
class GpioError(CaptureSystemError): ...
class ParallelExecutionError(CaptureSystemError): ...
```

Use package-specific subclasses only where the code is raising its own errors. Do not wrap arbitrary third-party exceptions unless it improves diagnostics.

### Tasks

- Introduce the exception hierarchy.
- Replace validation `ValueError` with `ConfigurationError` where errors are package-level user configuration errors.
- Replace camera open failures with `CameraOpenError`.
- Replace backend initialization failures with `BackendError`.
- Replace writer failures with `WriterError` or `WriterTimeoutError`.
- Replace output transaction failures with `OutputError` where appropriate.
- Replace GPIO setup/request failures with `GpioError` where appropriate.
- Keep CLI formatting generic: `Error: <TypeName>: <message>`.

### Acceptance Criteria

- Existing CLI error messages remain clear.
- Tests assert exception types for domain failures.
- No broad exception swallowing is introduced.

---

## PR2 — Explicit Writer Lifecycle

### Goal

Make the asynchronous writer lifecycle explicit and easier to reason about.

Current writer behavior is good but relies on queue sentinel semantics. Keep the single writer thread and bounded queue, but make state transitions explicit.

### Proposed Concepts

```python
from enum import Enum

class WriterState(Enum):
    NEW = "new"
    RUNNING = "running"
    STOPPING = "stopping"
    STOPPED = "stopped"
    FAILED = "failed"
```

`AsyncFrameWriter` should expose:

- `start()`
- `submit(frame, deadline, monotonic)`
- `close(timeout=...) -> WriterCloseResult`
- `raise_if_failed()`
- `state` property

### Tasks

- Add explicit writer state protected by a lock.
- Prevent submitting before start or after stopping.
- Preserve current queue backpressure behavior.
- Preserve current writer failure propagation behavior.
- Ensure `close()` is idempotent if practical.
- Ensure timeout reports a typed timeout error or structured close result.
- Preserve saved image list behavior.
- Add tests for:
  - normal close
  - close with full queue
  - writer error during save
  - submit after failure
  - submit after close
  - close timeout simulation

### Acceptance Criteria

- Writer shutdown behavior is more explicit than sentinel-only control.
- Existing `capture_images()` behavior is preserved.
- Failure modes are deterministic under tests.

---

## PR3 — Camera Backend Interface and Factory

### Goal

Move backend selection and backend-specific configuration out of orchestration code.

### Proposed API

```python
class CaptureBackend(Protocol):
    def open(self, config: CaptureConfig, cv2_module: Any) -> CaptureHandle: ...
    def configure(self, capture: CaptureHandle, config: CaptureConfig, cv2_module: Any) -> None: ...

class OpenCvBackend:
    ...

class NativeGStreamerBackend:
    ...

def create_capture_backend(name: str) -> CaptureBackend:
    ...
```

Alternatively, use a smaller factory if that fits the current code better.

### Tasks

- Introduce backend interface/protocol.
- Move OpenCV camera setting application behind OpenCV backend implementation.
- Move native GStreamer construction behind GStreamer backend implementation.
- Keep `NativeGStreamerCapture` or rename only if helpful.
- Update `CameraSession` to depend on a backend/factory rather than choosing backends internally.
- Preserve `capture_backend` config values: `opencv`, `gstreamer`.
- Preserve explicit pipeline string behavior.
- Preserve `usb-v4l2` and `jetson-csi` presets.

### Acceptance Criteria

- `capture.py` does not contain backend branching.
- `CameraSession` no longer decides OpenCV vs GStreamer behavior directly.
- Tests can inject fake backend objects.
- Existing CLI flags still work.

---

## PR4 — Consolidated Validation

### Goal

Reduce repeated validation and make runtime contracts clearer.

### Tasks

- Centralize validation around config objects.
- Keep lightweight CLI argument validation for immediate user-facing errors where useful.
- Ensure `CaptureConfig` validation covers:
  - duration > 0
  - fps > 0
  - camera index >= 0
  - warmup frames >= 0
  - write queue size > 0
  - optional width/height > 0
  - backend in allowed set
  - image extension in allowed set
  - fourcc length exactly 4 when provided
- Ensure `GpioEdgeConfig` validation covers:
  - output dir present
  - non-empty chip name
  - line offset >= 0
  - non-empty tag
  - edge in rising/falling/both
  - max events is None or >= 0
  - poll timeout > 0
  - duration is None or > 0
- Consider adding:

```python
def validate_capture_config(config: CaptureConfig) -> ValidatedCaptureConfig | tuple[str, str]
def validate_gpio_config(config: GpioEdgeConfig) -> ValidatedGpioConfig
```

Do not overcomplicate this if the current tuple return is sufficient.

### Acceptance Criteria

- Duplicate validation in benchmark/probe/capture paths is reduced.
- Tests cover validation once at the canonical boundary.
- CLI still reports user-friendly errors.

---

## PR5 — Simplify CameraSession to RAII

### Goal

Make `CameraSession` primarily own resource lifetime.

### Desired Direction

`CameraSession` should:

- receive an already-resolved backend or opener
- open resource on enter
- validate opened state
- release on exit or setup failure

It should not:

- normalize backend names
- know which backend requires which settings
- contain backend-specific conditionals

### Tasks

- Refactor session construction around the backend abstraction introduced in PR3.
- Keep `safe_release()` behavior.
- Ensure session releases capture on configuration failure.
- Ensure tests cover release on normal exit and exception path.

### Acceptance Criteria

- `CameraSession` is small and resource-lifetime focused.
- Backend-specific behavior lives in backend classes/functions.

---

## PR6 — Lightweight Frame Pipeline Seam

### Goal

Prepare for future processing stages without changing current behavior.

Do not build a large framework. Add only a small seam that allows future transformations to be inserted between frame acquisition and writer submission.

### Proposed Concepts

```python
class FrameSink(Protocol):
    def submit(self, frame: FrameRecord, *, deadline: float, monotonic: Callable[[], float]) -> bool: ...

class FrameTransform(Protocol):
    def apply(self, frame: FrameRecord) -> FrameRecord: ...
```

A default identity transform is enough.

### Tasks

- Keep current `capture_images(config)` public API stable.
- Internally allow an optional transform or pipeline callable to be injected for tests/future use.
- Ensure current writer remains the default sink.
- Do not change filename sequence semantics unless explicitly tested and justified.
- Add tests for a simple injected transform.

### Acceptance Criteria

- Existing behavior unchanged.
- Future processing steps can be added without editing the capture loop significantly.
- No unnecessary abstraction explosion.

---

## PR7 — Structured Runtime Metrics

### Goal

Expose structured run metrics without replacing existing log/CLI behavior.

### Proposed Models

```python
@dataclass(frozen=True)
class CaptureMetrics:
    frames_read: int
    frames_enqueued: int
    frames_saved: int
    read_failures: int
    warmup_requested: int
    warmup_completed: int
    queue_full_events: int
    elapsed_seconds: float

@dataclass(frozen=True)
class WriterMetrics:
    frames_submitted: int
    frames_written: int
    write_failures: int
    close_mode: str
    pending_items_at_close: int

@dataclass(frozen=True)
class GpioMetrics:
    initial_value_written: bool
    edge_events_written: int
    poll_timeouts: int
    elapsed_seconds: float
```

Keep this modest. Metrics should not dominate the code.

### Tasks

- Add metrics structures where they naturally fit.
- Decide whether public functions should return only paths for compatibility or expose optional richer results.
- Recommended approach:
  - keep existing `capture_images()` returning `list[Path]`
  - add `capture_images_with_result()` returning paths + metrics, or add optional `return_result=False`
  - keep existing CLI behavior
- Add metrics to parallel outcome if useful.
- Log metrics at end of run.

### Acceptance Criteria

- Existing public API remains compatible.
- Tests can assert metrics deterministically.
- Metrics improve observability without large design churn.

---

## PR8 — GPIO Refinement and Test Expansion

### Goal

Tighten GPIO behavior and testing around libgpiod v1/v2 compatibility.

### Tasks

- Preserve version-specific runners.
- Add tests for:
  - edge mapping for v1
  - edge mapping for v2
  - v2 value coercion
  - v2 timestamp extraction when realtime is unavailable
  - v2 timestamp extraction when realtime timestamp exists
  - common event loop max-events behavior
  - duration-based stop behavior
  - external stop-event behavior
- Validate that common loop writes exactly one initial file before edge events.
- Consider adding typed GPIO errors around request/setup failure.

### Acceptance Criteria

- No real libgpiod or GPIO hardware required by tests.
- v1/v2 compatibility behavior is documented by tests.
- Existing CLI behavior preserved.

---

## PR9 — Integration and Documentation Pass

### Goal

Make the cleaned-up architecture discoverable and safe to evolve.

### Tasks

- Add `ARCHITECTURE.md` or update existing docs with:
  - package map
  - capture flow
  - writer lifecycle
  - backend abstraction
  - GPIO v1/v2 dispatch
  - parallel execution flow
  - testing strategy
- Add CLI examples:
  - basic camera capture
  - OpenCV capture with resolution/fps/fourcc
  - GStreamer USB V4L2 capture
  - Jetson CSI capture
  - GPIO edge logging
  - parallel camera + GPIO run
  - benchmark/probe modes
- Add contributor notes for adding a new backend.
- Add contributor notes for adding a new frame transform.

### Acceptance Criteria

- A new maintainer can understand the architecture without reading every file.
- Examples remain accurate against actual CLI flags.
- Documentation reflects the refactored code, not the old layout.

---

# Suggested Final Architecture

The final architecture should look approximately like this:

```text
camera_capture/
  __init__.py
  models.py
  errors.py                # or capture_shared/errors.py
  validators.py
  backends.py              # backend interface + implementations/factory
  session.py               # RAII only
  writer.py                # explicit writer lifecycle
  capture.py               # orchestration, minimal branching
  probe.py
  benchmarks.py
  reporting.py
  cli.py

gpio_capture/
  gpio_edge.py             # public config + dispatch
  core.py                  # shared file/timestamp helpers
  runner_common.py         # version-neutral loop
  runner_v1.py
  runner_v2.py
  gpio_cli.py

capture_shared/
  capture_cli.py
  clocks.py
  errors.py
  output.py
  parallel_cli.py
  parallel_service.py
  runtime.py
  timestamps.py
```

Do not force this exact layout if the repository already has better naming. Preserve intent over names.

---

# Implementation Guidance

## Preserve Small Modules

The existing small-module style is good. Do not collapse everything into one large file.

## Prefer Narrow Interfaces

Use protocols only where there is a real testing or backend boundary. Avoid abstract base classes unless they buy something concrete.

## Keep Tests Hardware-Free

All new tests should be possible with:

- fake OpenCV module
- fake capture handle
- fake GStreamer/libgpiod modules
- fake clocks
- temporary directories

## Avoid Large-Bang Refactors

Each PR must leave the system runnable.

A good PR should be reviewable in isolation.

## Maintain CLI Compatibility

If a CLI flag must change, explicitly justify it and provide a compatibility alias where practical.

## Use Deterministic Clocks in Tests

The existing `Clock` abstraction is a major strength. Use it heavily.

## Treat Filesystem Behavior as Part of the Contract

Atomic output behavior and stale recovery are important. Do not weaken them.

---

# Verification Checklist

Run after each PR:

```bash
python -m pytest
python -m compileall .
```

If project tooling exists, also run:

```bash
ruff check .
ruff format --check .
mypy .
```

Manual smoke tests, where hardware is available:

```bash
camera-capture --output-dir /tmp/camera-test --duration 2
camera-capture --output-dir /tmp/camera-test --duration 2 --probe-modes
camera-capture --output-dir /tmp/camera-test --duration 2 --benchmark-backends
camera-gpio-edge --output-dir /tmp/gpio-test --line-offset 17 --duration-seconds 2
capture-main --camera-output-dir /tmp/cam --gpio-output-dir /tmp/gpio --duration 2 --gpio gpiochip0:17:test:both
```

Adapt executable/module names to the actual project packaging.

---

# Expected Outcome

After this cleanup pass, the project should have:

- clearer error types
- safer writer lifecycle semantics
- backend selection hidden behind a clean abstraction
- less duplicated validation
- simpler session lifecycle ownership
- a seam for future frame processing
- structured runtime metrics
- stronger tests around concurrency and failure paths
- documentation that reflects the architecture

This should make the package ready for future additions such as:

- raw frame output
- video encoding
- image preprocessing
- timestamp correlation reports
- hardware trigger correlation
- additional camera backends
- richer benchmarking
