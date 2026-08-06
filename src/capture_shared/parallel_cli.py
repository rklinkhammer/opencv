"""Unified camera and GPIO command line interface."""

from __future__ import annotations

import argparse
from pathlib import Path

from capture_shared.capture_cli import add_common_camera_args
from capture_shared.capture_cli import build_capture_config
from capture_shared.errors import ConfigurationError
from capture_shared.parallel_service import GpioJob
from capture_shared.parallel_service import execute_parallel_capture
from camera_capture.capture import capture_images
from gpio_capture.gpio_edge import run_gpio_edge_logger


def _format_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def _parse_gpio_spec(spec: str) -> GpioJob:
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


def build_parser() -> argparse.ArgumentParser:
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


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.duration <= 0:
        print("Error: --duration must be > 0")
        return 1
    if args.gpio_poll_timeout_ms <= 0:
        print("Error: --gpio-poll-timeout-ms must be > 0")
        return 1

    try:
        gpio_specs = [_parse_gpio_spec(spec) for spec in args.gpio]
    except ConfigurationError as exc:
        print(f"Error: {_format_exception(exc)}")
        return 1

    if gpio_specs and args.gpio_output_dir is None:
        print("Error: --gpio-output-dir is required when one or more --gpio specs are provided")
        return 1

    seen_tags: set[str] = set()
    for spec in gpio_specs:
        normalized = spec.tag.strip().lower()
        if normalized in seen_tags:
            print(f"Error: duplicate GPIO tag detected: {spec.tag}")
            return 1
        seen_tags.add(normalized)

    print(
        "Starting parallel capture run: "
        f"camera_duration={args.duration:.2f}s gpio_workers={len(gpio_specs)} "
        f"camera_backend={args.capture_backend}"
    )
    for spec in gpio_specs:
        print(f"- GPIO worker {spec.key} edge={spec.edge}")

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
    if outcome.camera_error is not None:
        print(f"Error: camera capture failed: {_format_exception(outcome.camera_error)}")
    else:
        print(f"Saved {len(outcome.images)} image(s) to {outcome.camera_output_dir}")

    for worker in outcome.workers:
        if worker.error is not None:
            print(f"Error: GPIO worker {worker.key} failed: {_format_exception(worker.error)}")
        else:
            print(f"GPIO worker {worker.key} completed with {len(worker.files)} value file(s)")

    failed = outcome.camera_error is not None or any(
        worker.error is not None for worker in outcome.workers
    )
    print(f"Total GPIO value files: {sum(len(worker.files) for worker in outcome.workers)}")
    print(
        "Parallel capture run complete: "
        f"status={'FAILED' if failed else 'OK'} elapsed_s={outcome.elapsed_seconds:.2f}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
