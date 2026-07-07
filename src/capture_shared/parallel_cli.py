"""Unified parallel launcher for camera capture and GPIO edge logging.

Architecture:
- Parses and validates user intent at the CLI boundary.
- Delegates execution to `capture_shared.parallel_service` (no worker logic in
    this module).
- Owns user-facing formatting of success/failure summaries.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from capture_shared.capture_cli import add_common_camera_args
from capture_shared.capture_cli import build_capture_config
from capture_shared.errors import ConfigurationError
from capture_shared.parallel_service import GpioJob
from capture_shared.parallel_service import ParallelOutcome
from capture_shared.parallel_service import execute_parallel_capture
from camera_capture.capture import capture_images
from gpio_capture.gpio_edge import run_gpio_edge_logger


def _format_exception(exc: Exception) -> str:
    """Render exceptions consistently for user-facing CLI output."""

    return f"{type(exc).__name__}: {exc}"


def _parse_gpio_spec(spec: str) -> GpioJob:
    """Parse gpio spec in format chip:line:tag[:edge]."""

    parts = [part.strip() for part in spec.split(":")]
    if len(parts) not in {3, 4}:
        raise ConfigurationError(
            "GPIO spec must use format chip:line_offset:tag[:edge], "
            "for example gpiochip0:17:door:both"
        )

    chip = parts[0]
    if not chip:
        raise ConfigurationError("GPIO spec chip cannot be empty")

    try:
        line_offset = int(parts[1])
    except ValueError as exc:
        raise ConfigurationError(f"GPIO line offset must be an integer: {parts[1]}") from exc

    if line_offset < 0:
        raise ConfigurationError("GPIO line offset must be >= 0")

    tag = parts[2]
    if not tag:
        raise ConfigurationError("GPIO tag cannot be empty")

    edge = "both"
    if len(parts) == 4:
        edge = parts[3].lower()
    if edge not in {"rising", "falling", "both"}:
        raise ConfigurationError(f"GPIO edge must be one of rising/falling/both, got: {edge}")

    return GpioJob(chip=chip, line_offset=line_offset, tag=tag, edge=edge)


def _worker_label(spec: GpioJob) -> str:
    """Build a stable human-readable worker label."""

    return f"{spec.chip}:{spec.line_offset}:{spec.tag}"


def build_parser() -> argparse.ArgumentParser:
    """Build and return parser for unified parallel capture launcher."""

    parser = argparse.ArgumentParser(
        prog="capture-main",
        description=(
            "Run camera capture and one or more GPIO edge loggers in parallel. "
            "Each GPIO writes tagged timestamped files."
        ),
    )

    parser.add_argument(
        "--camera-output-dir",
        type=Path,
        required=True,
        help="Directory for camera image output.",
    )
    parser.add_argument(
        "--gpio-output-dir",
        type=Path,
        default=None,
        help="Directory for GPIO edge output files (required when using --gpio).",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Shared runtime for camera and GPIO workers in seconds (default: 5).",
    )

    parser.add_argument(
        "--gpio",
        action="append",
        default=[],
        help=(
            "GPIO spec chip:line_offset:tag[:edge]. "
            "Repeat --gpio for each line. Example: --gpio gpiochip0:17:door:both"
        ),
    )
    parser.add_argument(
        "--gpio-poll-timeout-ms",
        type=int,
        default=1000,
        help="GPIO poll timeout in milliseconds (default: 1000).",
    )

    add_common_camera_args(parser)
    parser.add_argument(
        "--camera-log-file",
        type=Path,
        default=None,
        help="Optional camera log file path.",
    )
    return parser


def _validate_runtime_args(args: argparse.Namespace) -> str | None:
    """Validate scalar runtime options and return a user-facing error string."""

    if args.duration <= 0:
        return "Error: --duration must be > 0"
    if args.gpio_poll_timeout_ms <= 0:
        return "Error: --gpio-poll-timeout-ms must be > 0"
    return None


def _parse_gpio_specs(gpio_args: list[str]) -> list[GpioJob]:
    """Parse all repeated GPIO CLI specs into normalized `GpioJob` values."""

    return [_parse_gpio_spec(spec) for spec in gpio_args]


def _validate_gpio_requirements(
    *,
    gpio_specs: list[GpioJob],
    gpio_output_dir: Path | None,
) -> str | None:
    """Validate GPIO-specific CLI constraints.

    Ensures output directory requirements and tag uniqueness before dispatch.
    """

    if gpio_specs and gpio_output_dir is None:
        return "Error: --gpio-output-dir is required when one or more --gpio specs are provided"

    seen_tags: set[str] = set()
    for spec in gpio_specs:
        normalized = spec.tag.strip().lower()
        if normalized in seen_tags:
            return f"Error: duplicate GPIO tag detected: {spec.tag}"
        seen_tags.add(normalized)
    return None


def _print_run_header(args: argparse.Namespace, gpio_specs: list[GpioJob]) -> None:
    """Emit startup summary lines before orchestrating worker execution."""

    print(
        "Starting parallel capture run: "
        f"camera_duration={args.duration:.2f}s gpio_workers={len(gpio_specs)} "
        f"camera_backend={args.capture_backend}"
    )
    for spec in gpio_specs:
        print(f"- GPIO worker {_worker_label(spec)} edge={spec.edge}")


def _print_run_summary(*, result: ParallelOutcome) -> int:
    """Render final run summary and return process exit code."""

    for line in _render_run_summary_lines(result):
        print(line)
    return 1 if _run_failed(result) else 0


def _run_failed(result: ParallelOutcome) -> bool:
    """Return whether camera or any GPIO worker reported an error."""

    return result.camera_error is not None or any(
        worker.error is not None for worker in result.workers
    )


def _render_run_summary_lines(result: ParallelOutcome) -> list[str]:
    """Build deterministic, operator-readable summary lines for a run."""

    lines: list[str] = []
    if result.camera_error is not None:
        lines.append(f"Error: camera capture failed: {_format_exception(result.camera_error)}")
    else:
        lines.append(f"Saved {len(result.images)} image(s) to {result.camera_output_dir}")

    for worker in result.workers:
        if worker.error is not None:
            lines.append(
                f"Error: GPIO worker {worker.key} failed: {_format_exception(worker.error)}"
            )
        else:
            lines.append(
                f"GPIO worker {worker.key} completed with {len(worker.files)} value file(s)"
            )

    total_gpio_files = sum(len(worker.files) for worker in result.workers)
    failed = _run_failed(result)
    lines.append(f"Total GPIO value files: {total_gpio_files}")
    lines.append(
        "Parallel capture run complete: "
        f"status={'FAILED' if failed else 'OK'} elapsed_s={result.elapsed_seconds:.2f}"
    )
    return lines


def main(argv: list[str] | None = None) -> int:
    """Run camera and GPIO capture workflows in parallel.

    Execution flow:
    1. Parse/validate CLI arguments.
    2. Build camera runtime config and GPIO job set.
    3. Delegate orchestration to `execute_parallel_capture`.
    4. Render outcome lines and return a shell-friendly exit code.
    """

    args = build_parser().parse_args(argv)

    runtime_error = _validate_runtime_args(args)
    if runtime_error is not None:
        print(runtime_error)
        return 1

    try:
        gpio_specs = _parse_gpio_specs(args.gpio)
    except ConfigurationError as exc:
        print(f"Error: {_format_exception(exc)}")
        return 1

    gpio_error = _validate_gpio_requirements(
        gpio_specs=gpio_specs,
        gpio_output_dir=args.gpio_output_dir,
    )
    if gpio_error is not None:
        print(gpio_error)
        return 1

    _print_run_header(args, gpio_specs)

    camera_config = build_capture_config(
        args=args,
        output_dir=args.camera_output_dir,
        duration_seconds=args.duration,
        log_file=args.camera_log_file,
    )

    outcome = execute_parallel_capture(
        camera_config=camera_config,
        gpio_jobs=gpio_specs,
        gpio_output_dir=args.gpio_output_dir,
        duration_seconds=args.duration,
        gpio_poll_timeout_ms=args.gpio_poll_timeout_ms,
        capture_fn=capture_images,
        gpio_fn=run_gpio_edge_logger,
    )
    return _print_run_summary(result=outcome)


if __name__ == "__main__":
    raise SystemExit(main())
