# Refactor Report

Date: 2026-07-06
Project: Camera Capture App

## Scope

This report summarizes high-impact refactor opportunities identified in the runtime CLI orchestration, camera capture pipeline, backend abstraction, and test consistency.

## Top Priorities

### 1) Decompose parallel CLI orchestration

Target: `src/capture_shared/parallel_cli.py`

Current issue:
- `main()` handles argument validation, GPIO parsing, duplicate-tag checks, worker creation, thread lifecycle, camera execution, error reporting, and summary rendering in one function.

Why refactor:
- Harder to test behavior in isolation.
- Higher risk of regressions when changing one phase.

Recommended split:
- `_validate_parallel_args(args)`
- `_parse_gpio_specs(args)`
- `_build_gpio_threads(...)`
- `_run_camera_capture(...)`
- `_collect_and_render_summary(...)`

Expected benefit:
- Better unit test granularity.
- Easier maintenance and lower cognitive load.

---

### 2) Break `capture_images()` into lifecycle phases

Target: `src/camera_capture/capture.py`

Current issue:
- `capture_images()` includes setup, warmup, frame enqueue loop, backpressure handling, shutdown choreography, and final error mapping in one long block.

Why refactor:
- Complex failure handling paths are difficult to reason about.
- Small behavior changes require touching a large function.

Recommended split:
- `_warmup_camera(...)`
- `_enqueue_frames_until_deadline(...)`
- `_shutdown_writer(...)`
- `_finalize_capture_result(...)`

Expected benefit:
- Cleaner control flow.
- Easier testing for warmup, queue saturation, and shutdown timeout scenarios.

---

### 3) Replace shared mutable error list with explicit signaling

Targets:
- `src/camera_capture/capture.py`
- `src/camera_capture/writer.py`

Current issue:
- Producer and writer threads coordinate error state through `writer_errors: list[Exception]` side effects.

Why refactor:
- Implicit coordination pattern is easy to misuse.
- Concurrency intent is not self-documenting.

Recommended approach:
- Introduce an explicit error channel (e.g., `Queue[Exception]`) or a small thread-safe state object.
- Keep a single definitive writer failure source.

Expected benefit:
- Improved correctness and readability in concurrent code paths.

## Medium Priorities

### 4) Reduce compatibility-wrapper indirection

Target: `src/camera_capture/capture.py`

Current issue:
- Multiple thin wrappers forward directly to backend/probe modules.

Why refactor:
- Adds indirection without strong value unless strict backward compatibility is required.

Recommended approach:
- Either remove wrappers and call backend/probe functions directly,
- Or formalize wrappers into a dedicated facade module with clear compatibility intent.

Expected benefit:
- Simpler module surface and clearer ownership boundaries.

---

### 5) Introduce structured run-result model for CLI summaries

Target: `src/capture_shared/parallel_cli.py`

Current issue:
- Reporting and status are assembled with booleans plus ad-hoc prints.

Why refactor:
- Hard to extend output or reuse for alternate frontends.

Recommended approach:
- Add dataclasses:
  - `WorkerResult`
  - `ParallelRunResult`
- Render textual output from result objects in one place.

Expected benefit:
- Easier output changes and stronger contract for tests.

---

### 6) Make camera property application table-driven

Target: `src/camera_capture/backends.py`

Current issue:
- Repetitive `if` blocks for optional camera properties.

Why refactor:
- Verbose and more error-prone when adding new properties.

Recommended approach:
- Use a mapping table from config fields to cv2 property constants.
- Keep special handling for FOURCC as a distinct branch.

Expected benefit:
- Less repetition, easier extension.

## Low-Risk Quick Wins

### 7) Replace magic timing values with named constants

Targets:
- `src/camera_capture/capture.py`
- `src/camera_capture/writer.py`

Current issue:
- Polling/sleep/join intervals are embedded as literals.

Recommended approach:
- Extract constants such as queue put timeout, idle sleep, join timeout, and writer poll timeout.

Expected benefit:
- Better readability and safer tuning.

---

### 8) Align test runner guidance with actual workflow

Targets:
- `README.md`
- `tests/*`

Current issue:
- Tests are `unittest`-style, but workflow also uses `pytest` successfully.

Recommended approach:
- Define one canonical test command in docs, optionally keep both documented explicitly.

Expected benefit:
- Fewer environment/setup mismatches.

## Suggested Implementation Order

1. Refactor `parallel_cli.main()` into phase helpers (behavior-preserving).
2. Add structured run result model for CLI reporting.
3. Refactor `capture_images()` into lifecycle helpers.
4. Replace writer error list with explicit signaling.
5. Table-drive camera property application.
6. Normalize constants and docs.

## Verification Checklist

After each step:
- Run `python -m pytest -q tests/test_parallel_cli.py`.
- Run `python -m unittest discover -s tests -v`.
- Smoke test camera-only CLI:
  - `capture-main --camera-output-dir ./captures/images --duration 1`
- Smoke test camera+GPIO CLI (on supported host):
  - `capture-main --camera-output-dir ./captures/images --gpio-output-dir ./captures/gpio --duration 1 --gpio gpiochip0:17:door:both`

## Notes

- Prioritize behavior-preserving decomposition first.
- Keep current CLI contract intact while internal structure improves.
- Prefer small, test-backed refactor PRs to reduce risk.
