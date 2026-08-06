"""Command-line interface for camera capture, probe, and benchmark flows."""

from __future__ import annotations

import argparse
from pathlib import Path
import time

from capture_shared.cli_options import add_common_camera_args
from capture_shared.cli_options import build_capture_config

from .benchmarks import benchmark_capture_only
from .capture import capture_images
from .models import ProbeResult
from .probe import probe_camera_modes


def format_exception(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"


def print_probe_results(results: list[ProbeResult], best: ProbeResult | None) -> None:
    if not results:
        print("No probe results were produced.")
        return

    print("Mode probe results:")
    for result in results:
        print(
            f"- {result.fourcc} {result.width}x{result.height} "
            f"req_fps={result.requested_fps:.1f} measured_fps={result.measured_fps:.2f} "
            f"frames={result.measured_frames} reported_fps={result.reported_fps:.2f}"
        )

    if best is not None:
        print(
            "Best mode: "
            f"{best.fourcc} {best.width}x{best.height} measured_fps={best.measured_fps:.2f}"
        )


def print_backend_benchmark_results(
    *,
    mode_name: str,
    results: list[tuple[str, int, float, float, str]],
) -> bool:
    print(f"Backend benchmark results ({mode_name}):")
    failed = False
    for backend, frames, elapsed, saved_fps, status in results:
        if status.startswith("FAIL:"):
            failed = True
        print(
            f"- {backend}: frames_saved={frames} elapsed_s={elapsed:.2f} "
            f"saved_fps={saved_fps:.2f} status={status}"
        )
    return failed


def build_parser() -> argparse.ArgumentParser:
    """Build and return the top-level CLI argument parser."""

    parser = argparse.ArgumentParser(
        prog="camera-capture",
        description="Capture images from a USB camera for a fixed duration.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where captured images are saved.",
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=5.0,
        help="Capture duration in seconds (default: 5).",
    )
    add_common_camera_args(parser)
    parser.add_argument(
        "--probe-modes",
        action="store_true",
        help="Probe common camera modes for measured FPS and exit.",
    )
    parser.add_argument(
        "--probe-duration",
        type=float,
        default=5.0,
        help="Duration per mode in probe mode, seconds (default: 5).",
    )
    parser.add_argument(
        "--benchmark-backends",
        action="store_true",
        help="Run a simple sequential benchmark for opencv and gstreamer backends and exit.",
    )
    parser.add_argument(
        "--benchmark-duration",
        type=float,
        default=5.0,
        help="Duration per backend in benchmark mode, seconds (default: 5).",
    )
    parser.add_argument(
        "--benchmark-capture-only",
        action="store_true",
        help="Benchmark ingest FPS only (no queueing, processing, or file writes).",
    )
    parser.add_argument(
        "--benchmark-jetson-csi",
        action="store_true",
        help="Run a Jetson CSI benchmark preset across common resolutions and exit.",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Optional log file path for timestamped capture logs.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint.

    Args:
        argv: Optional argument list override.

    Returns:
        Process-style exit code.
    """

    parser = build_parser()
    args = parser.parse_args(argv)

    if args.benchmark_backends and args.benchmark_jetson_csi:
        print("Error: --benchmark-backends and --benchmark-jetson-csi are mutually exclusive")
        return 1

    if args.probe_modes:
        try:
            results, best = probe_camera_modes(
                camera_index=args.camera_index,
                duration_seconds=args.probe_duration,
            )
        except Exception as exc:
            print(f"Error: {format_exception(exc)}")
            return 1

        print_probe_results(results, best)
        return 0

    if args.benchmark_backends:
        return _run_backend_benchmark(args)

    if args.benchmark_jetson_csi:
        return _run_jetson_csi_benchmark(args)

    config = build_capture_config(
        args=args,
        output_dir=args.output_dir,
        duration_seconds=args.duration,
        log_file=args.log_file,
    )

    try:
        saved = capture_images(config)
    except Exception as exc:
        print(f"Error: {format_exception(exc)}")
        return 1

    print(f"Saved {len(saved)} image(s) to {config.output_dir}")
    return 0


def _run_backend_benchmark(args: argparse.Namespace) -> int:
    """Execute a backend benchmark run and return exit status."""

    base_dir = Path(args.output_dir)
    benchmark_duration = args.benchmark_duration
    if benchmark_duration <= 0:
        print("Error: --benchmark-duration must be > 0")
        return 1

    results: list[tuple[str, int, float, float, str]] = []
    mode_name = "capture-only" if args.benchmark_capture_only else "full-pipeline"
    for backend in ["opencv", "gstreamer"]:
        output_dir = base_dir / f"benchmark_{backend}"
        if not args.benchmark_capture_only:
            output_dir.mkdir(parents=True, exist_ok=True)

        config = build_capture_config(
            args=args,
            output_dir=output_dir,
            duration_seconds=benchmark_duration,
            log_file=None,
            capture_backend=backend,
        )

        started = time.perf_counter()
        try:
            if args.benchmark_capture_only:
                frames, elapsed, fps = benchmark_capture_only(
                    config, duration_seconds=benchmark_duration
                )
            else:
                frames = len(capture_images(config))
                elapsed = max(time.perf_counter() - started, 1e-9)
                fps = frames / elapsed
            results.append((backend, frames, elapsed, fps, "OK"))
        except Exception as exc:
            elapsed = max(time.perf_counter() - started, 1e-9)
            results.append((backend, 0, elapsed, 0.0, f"FAIL: {format_exception(exc)}"))

    failed = print_backend_benchmark_results(mode_name=mode_name, results=results)
    return 1 if failed else 0


def _run_jetson_csi_benchmark(args: argparse.Namespace) -> int:
    """Run Jetson CSI benchmark presets across common resolutions."""

    benchmark_duration = args.benchmark_duration
    if benchmark_duration <= 0:
        print("Error: --benchmark-duration must be > 0")
        return 1

    resolutions: list[tuple[int, int]] = [
        (320, 240),
        (640, 480),
        (1280, 720),
        (1920, 1080),
    ]

    mode_name = "capture-only" if args.benchmark_capture_only else "full-pipeline"
    print(f"Jetson CSI benchmark results ({mode_name}):")
    print(
        f"- camera_index={args.camera_index} requested_fps={args.fps:.1f} "
        f"duration_s={benchmark_duration:.1f}"
    )
    failures = 0

    for width, height in resolutions:
        output_dir = Path(args.output_dir) / f"benchmark_jetson_csi_{width}x{height}"
        if not args.benchmark_capture_only:
            output_dir.mkdir(parents=True, exist_ok=True)

        config = build_capture_config(
            args=args,
            output_dir=output_dir,
            duration_seconds=benchmark_duration,
            log_file=None,
            capture_backend="gstreamer",
            gstreamer_source="jetson-csi",
            frame_width=width,
            frame_height=height,
        )

        started = time.perf_counter()
        try:
            if args.benchmark_capture_only:
                frames, elapsed, fps = benchmark_capture_only(
                    config, duration_seconds=benchmark_duration
                )
            else:
                frames = len(capture_images(config))
                elapsed = max(time.perf_counter() - started, 1e-9)
                fps = frames / elapsed
            print(
                f"- {width}x{height}: frames={frames} elapsed_s={elapsed:.2f} "
                f"fps={fps:.2f} status=OK"
            )
        except Exception as exc:
            failures += 1
            elapsed = max(time.perf_counter() - started, 1e-9)
            print(
                f"- {width}x{height}: frames=0 elapsed_s={elapsed:.2f} "
                f"fps=0.00 status=FAIL: {format_exception(exc)}"
            )

    return 1 if failures > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
