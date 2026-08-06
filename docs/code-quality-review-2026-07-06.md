# Code Quality Review - 2026-07-06

> **Historical document:** This review records the code as it existed on its stated date.
> Some referenced probe and metrics code has since been removed. See
> [ARCHITECTURE.md](../ARCHITECTURE.md) for the current implementation.

## Scope
- Reviewed runtime capture pipeline, async shutdown path, backend ingestion, probe flow, CLI diagnostics, tests, and packaging metadata.
- Primary files:
  - src/camera_capture/capture.py
  - src/camera_capture/backends.py
  - src/camera_capture/probe.py
  - src/camera_capture/cli.py
  - src/camera_capture/benchmarks.py
  - tests/test_capture.py
  - tests/test_cli.py
  - pyproject.toml

## Findings (Ordered by Severity)

### 1) Medium: Shared global logger lifecycle is not concurrency-safe (Implemented)
- Evidence:
  - capture.py resets all handlers for logger name "camera_capture" on each run.
  - capture.py also removes and closes handlers at function exit.
- Risk:
  - Concurrent invocations in the same process can remove each other's handlers, causing dropped logs and hard-to-debug behavior.
  - External embedding applications that preconfigure this logger can have handlers removed unexpectedly.
- Recommendation:
  - Use a per-run logger name (for example with a UUID suffix), or keep global logger static and attach a per-run handler without removing unrelated handlers.
  - Track and close only handlers created by this call.
 - Implementation:
   - capture.py now creates a per-run logger name using a UUID and disables propagation.

### 2) Medium: Potential indefinite block on queue join in "healthy writer" path (Implemented)
- Evidence:
  - capture.py waits on queue.join() when writer_errors is empty.
- Risk:
  - If writer thread hangs inside a blocking operation (for example filesystem stall around imwrite), unfinished_tasks never reaches zero and capture shutdown can block indefinitely.
- Recommendation:
  - Replace unbounded queue.join() with timeout-based join loop and watchdog logging.
  - If timeout expires, mark shutdown mode as degraded and return error with actionable diagnostics.
 - Implementation:
   - capture.py now uses a timeout-bound unfinished-task wait loop and raises a RuntimeError on join timeout.

### 3) Low: Probe input validation is less strict than capture/benchmark paths (Implemented)
- Evidence:
  - probe.py validates duration_seconds but not camera_index >= 0.
  - capture/benchmark paths now validate camera_index.
- Risk:
  - Inconsistent error behavior across commands and less actionable user feedback.
- Recommendation:
  - Add camera_index validation in probe.py for consistency.
 - Implementation:
   - probe.py now validates camera_index >= 0.

### 4) Low: Benchmark backend failure output is less informative than other CLI errors (Implemented)
- Evidence:
  - cli.py backend benchmark records failures as FAIL: {exc}, without exception type.
  - Other CLI surfaces use typed formatting via _format_exception().
- Risk:
  - Lower diagnostic value for production troubleshooting.
- Recommendation:
  - Use _format_exception(exc) in backend benchmark status messages as well.
 - Implementation:
   - cli.py now records backend benchmark failures as FAIL: <Type>: <message>.

## Positive Observations
- Async writer deadlock path was addressed with queue draining and explicit shutdown metrics.
- Cross-platform filename safety improved by replacing colon-containing timestamp format in filenames.
- Native GStreamer frame extraction now validates caps, dimensions, and buffer size before reshape.
- Test coverage includes regression tests for writer-failure shutdown and CLI benchmark failure exit code.

## Test/Process Gaps
- No dedicated automated test asserts shutdown metrics are emitted as expected.
- No explicit timeout/chaos tests for stuck writer I/O (for example mocked long-running imwrite).

## Recommended Next Steps
1. Add one log-focused test that validates shutdown metrics line contents.
