# Camera/GPIO Capture Architecture

This is the canonical maintainer reference for the camera capture, GPIO edge logging,
and parallel runtime packages. The project favors small modules, immutable configuration
records, injected hardware dependencies, bounded concurrency, and transactional output.

## Package Map

### `camera_capture`

- `models.py`: immutable capture configuration and frame records.
- `validators.py`: canonical `CaptureConfig` validation and normalization.
- `backends.py`: backend protocol, factory, OpenCV implementation, and native GStreamer
  appsink implementation.
- `writer.py`: bounded asynchronous writer, lifecycle state, overlay, EXIF, and atomic
  output publication.
- `capture.py`: fixed-duration orchestration and optional callable frame transform.
- `benchmarks.py`: camera throughput measurement helper.
- `cli.py`: standalone camera CLI and its output formatting.

### `gpio_capture`

- `gpio_edge.py`: public GPIO configuration, validation, and v1/v2 dispatch.
- `core.py`: tags, value-file output, and stop-condition adaptation.
- `runner_common.py`: version-neutral initial-value and edge-event loop.
- `runner_v1.py`, `runner_v2.py`: isolated libgpiod API adapters.
- `cli.py`: standalone GPIO edge-logging CLI.

### `capture_shared`

- `errors.py`: typed domain exception hierarchy.
- `clocks.py`, `timestamps.py`: monotonic control time and wall-clock artifact time.
- `output.py`: collision-safe reservations, atomic transactions, and stale recovery.
- `cli_options.py`: camera arguments shared by the standalone and unified CLIs.
- `runtime.py`: duration and cooperative stop-event logic.
- `parallel_service.py`: presentation-free camera/GPIO orchestration.

`parallel_cli.py` at the source root contains unified parsing and result presentation.

## Camera Capture Flow

1. A CLI or caller constructs immutable `CaptureConfig`.
2. `validate_capture_config()` validates the complete contract and normalizes backend and
   extension names.
3. `create_capture_backend()` resolves OpenCV or native GStreamer.
4. `open_camera()` opens, validates, configures, and guarantees release of the handle.
5. Warmup reads discard unstable startup frames.
6. Each successful read becomes immutable `FrameRecord` with a sequence and wall time.
7. An optional transform callable processes the record.
8. `AsyncFrameWriter.submit()` puts the record on its bounded queue before the deadline.
9. The writer applies overlay/EXIF policy and commits through `OutputTransaction`.
10. Shutdown drains work, surfaces the first failure, and returns saved paths.

## Writer Lifecycle

The writer owns one thread and one bounded queue. Its synchronized states are:

```text
NEW -> RUNNING -> STOPPING -> STOPPED
          |           |
          +---------> FAILED
```

- `start()` is valid only in `NEW`.
- `submit()` is valid only in `RUNNING`; a full queue applies bounded backpressure.
- `close()` enters `STOPPING`, queues a sentinel, and joins with a timeout.
- Completed closes are idempotent; timed-out closes remain retryable.
- `FAILED` retains the first writer exception for deterministic propagation.

The sentinel wakes the worker, while `WriterState` is authoritative. Atomic output means
failed writes do not leave completed-looking artifacts.

## Camera Backend Boundary

The structural `CaptureBackend` contract is:

```python
open(config, cv2_module) -> CaptureHandle
configure(capture, config, cv2_module) -> None
```

`OpenCvBackend` opens `cv2.VideoCapture` and applies OpenCV properties. Native GStreamer
constructs an appsink pipeline. Its configuration step installs the optional diagnostic
reporter; `open_camera()` never branches on backend names.

OpenCV configuration reads each requested property back after `set()`. FOURCC and integer
controls must match; FPS allows a 5% tolerance for driver quantization. A rejected or
materially different value raises `CaptureError`. With `--verbose`, the CLI also reports
the pre-configuration properties and every verified update. Unsupported diagnostic reads
are shown as `unavailable` and do not stop capture; requested updates remain strict.

Native GStreamer reports its pipeline and the first negotiated caps in verbose mode. For
generated presets, the first sample must match the requested width, height, FPS, and BGR
format. A custom pipeline owns its width, height, and FPS negotiation, but must still
produce BGR frames because the appsink adapter returns three-channel NumPy arrays.

The portable property set covers frame mode, exposure, image adjustment, white balance,
focus, pan/tilt/roll/zoom, and buffering. Backend-specific OpenNI, XI, OBSENSOR, mobile,
and GPhoto properties are intentionally excluded.

Public backend names remain `opencv` and `gstreamer`. GStreamer supports explicit
pipelines plus `usb-v4l2` and `jetson-csi` presets.

## GPIO v1/v2 Dispatch

`run_gpio_edge_logger()` validates config and detects the libgpiod surface:

```text
GpioEdgeConfig
    |
    +-- request_lines + LineSettings + line --> runner_v2 --+
    |                                                       |
    +-- otherwise ---------------------------> runner_v1 --+--> runner_common
```

Both adapters implement the same internal edge-source contract. The common loop writes
exactly one initial-value file, then one file per event until max-events, duration, or an
external stop event ends the run. Monotonic event timestamps are never formatted as Unix
time; wall time is used unless a realtime event clock is explicitly available. The API
returns the value-file paths as `list[Path]`.

## Parallel Execution

`execute_parallel_capture()` stays presentation-free:

1. Create a shared stop event.
2. Start one GPIO thread per `GpioJob`.
3. Run camera capture on the calling thread.
4. Record camera and GPIO exceptions independently.
5. Signal GPIO shutdown after camera completion or failure.
6. Join workers with bounded timeouts.
7. Return `ParallelOutcome`; the CLI renders it and selects the exit code.

Worker callables remain injectable and list-returning, keeping tests hardware-free.

## Error and Time Models

Package-authored failures use `CaptureError`, `ConfigurationError`, or `GpioError`.
CLIs render them as `Error: <TypeName>: <message>`.

Monotonic time controls deadlines and elapsed duration. Wall time is used for filenames,
overlays, EXIF, and realtime GPIO timestamps. Tests inject deterministic clocks.

## Testing Strategy

The default suite requires no hardware. It uses fake OpenCV captures, fake
GStreamer/libgpiod surfaces, deterministic clocks, temporary directories, blocked writer
hooks, and injected worker callables.

```bash
.venv/bin/python -m pytest -q --cov --cov-report=term-missing --cov-fail-under=75
.venv/bin/python -m compileall -q src tests
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy src
```

Hardware tests are opt-in through the environment variables in the README.

## Adding a Camera Backend

1. Implement `CaptureBackend` in `camera_capture/backends.py`.
2. Keep hardware-specific opening and configuration inside that implementation.
3. Return `CaptureHandle` with `isOpened()`, `read()`, and `release()`.
4. Add the public name to canonical validation and the backend factory.
5. Add hardware-free tests with a fake handle.
6. Do not add backend conditionals to `open_camera()` or `capture.py`.

## Adding a Frame Transform

1. Write a callable accepting and returning `FrameRecord`.
2. Preserve sequence and capture timestamp so ordering and temporal identity stay stable.
3. Return a new immutable record when changing the image payload.
4. Inject it with `capture_images(..., frame_transform=transform)`.
5. Test that it runs between capture and writer submission.

Avoid a generalized pipeline framework until concrete stages require composition or
lifecycle management.

## CLI Examples

Install the editable package first:

```bash
.venv/bin/python -m pip install -e '.[dev]'
```

Basic camera capture:

```bash
camera-capture --output-dir /tmp/camera-test --duration 2
```

OpenCV with explicit mode:

```bash
camera-capture --output-dir /tmp/camera-test --duration 2 \
  --capture-backend opencv --width 1280 --height 720 --fps 30 --fourcc MJPG
```

GStreamer USB V4L2 preset:

```bash
camera-capture --output-dir /tmp/camera-test --duration 2 \
  --capture-backend gstreamer --gstreamer-source usb-v4l2 \
  --width 1280 --height 720 --fps 30
```

Jetson CSI preset:

```bash
camera-capture --output-dir /tmp/camera-test --duration 2 \
  --capture-backend gstreamer --gstreamer-source jetson-csi \
  --camera-index 0 --width 1280 --height 720 --fps 30
```

GPIO edge logging:

```bash
camera-gpio-edge --output-dir /tmp/gpio-test --chip gpiochip0 \
  --line-offset 17 --tag trigger --edge both --duration-seconds 2
```

Parallel camera and GPIO:

```bash
capture-main --camera-output-dir /tmp/camera-test \
  --gpio-output-dir /tmp/gpio-test --duration 2 \
  --gpio gpiochip0:17:trigger:both
```

Benchmark OpenCV and GStreamer:

```bash
camera-capture --output-dir /tmp/camera-benchmark \
  --benchmark-backends --benchmark-duration 2 --benchmark-capture-only
```

Benchmark Jetson CSI presets:

```bash
camera-capture --output-dir /tmp/camera-benchmark \
  --benchmark-jetson-csi --benchmark-duration 2 --benchmark-capture-only
```
