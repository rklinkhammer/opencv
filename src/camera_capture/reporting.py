"""Shared CLI output helpers for camera workflows."""

from __future__ import annotations

from .models import ProbeResult


def format_exception(exc: Exception) -> str:
    """Format exceptions consistently for CLI output."""

    return f"{type(exc).__name__}: {exc}"


def print_probe_results(results: list[ProbeResult], best: ProbeResult | None) -> None:
    """Print mode probe results in a human-readable table-style format."""

    if not results:
        print("No probe results were produced.")
        return

    print("Mode probe results:")
    for result in results:
        print(
            (
                f"- {result.fourcc} {result.width}x{result.height} "
                f"req_fps={result.requested_fps:.1f} measured_fps={result.measured_fps:.2f} "
                f"frames={result.measured_frames} reported_fps={result.reported_fps:.2f}"
            )
        )

    if best is not None:
        print(
            (
                "Best mode: "
                f"{best.fourcc} {best.width}x{best.height} "
                f"measured_fps={best.measured_fps:.2f}"
            )
        )


def print_backend_benchmark_results(
    *,
    mode_name: str,
    results: list[tuple[str, int, float, float, str]],
) -> bool:
    """Print backend benchmark table and return whether any backend failed."""

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
