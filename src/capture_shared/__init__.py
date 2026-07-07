"""Shared utilities for capture-oriented packages.

Public API index (module-level):
- `capture_shared.clocks`:
        - `Clock`, `SystemClock`, `FunctionClock`
- `capture_shared.output`:
        - `OutputTransaction`, `recover_stale_outputs`
- `capture_shared.timestamps`:
        - `capture_datetime`, `format_filename_timestamp`, `format_iso_timestamp`
- `capture_shared.parallel_service`:
        - `GpioJob`, `WorkerOutcome`, `ParallelOutcome`, `execute_parallel_capture`
- `capture_shared.capture_cli`:
        - shared parser/config mapping helpers for camera-oriented CLIs

Execution role:
- This package provides cross-cutting primitives consumed by camera and GPIO
        runtimes to keep orchestration logic consistent and avoid duplication.
"""
