"""Command-line interface for GPIO edge logging."""

from __future__ import annotations

import argparse
from pathlib import Path

from .gpio_edge import GpioEdgeConfig
from .gpio_edge import run_gpio_edge_logger


def build_parser() -> argparse.ArgumentParser:
    """Build and return the CLI parser for GPIO edge logging."""

    parser = argparse.ArgumentParser(
        prog="camera-gpio-edge",
        description=(
            "Write timestamped GPIO value files. One file is written at startup, "
            "then one file per asynchronous edge event."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Directory where GPIO value files are written.",
    )
    parser.add_argument(
        "--chip",
        type=str,
        default="gpiochip0",
        help="libgpiod chip name (default: gpiochip0).",
    )
    parser.add_argument(
        "--line-offset",
        type=int,
        required=True,
        help="GPIO line offset within the selected chip.",
    )
    parser.add_argument(
        "--tag",
        type=str,
        default="gpio",
        help="Tag inserted into each output filename (default: gpio).",
    )
    parser.add_argument(
        "--edge",
        choices=["rising", "falling", "both"],
        default="both",
        help="Edge type to monitor (default: both).",
    )
    parser.add_argument(
        "--consumer",
        type=str,
        default="camera-gpio-edge",
        help="Consumer label shown in GPIO diagnostics (default: camera-gpio-edge).",
    )
    parser.add_argument(
        "--poll-timeout-ms",
        type=int,
        default=1000,
        help="Edge wait timeout in milliseconds (default: 1000).",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Optional number of edge events to process before exiting.",
    )
    parser.add_argument(
        "--duration-seconds",
        type=float,
        default=None,
        help="Optional maximum runtime in seconds before exit.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for asynchronous GPIO edge logging."""

    args = build_parser().parse_args(argv)
    config = GpioEdgeConfig(
        output_dir=args.output_dir,
        chip_name=args.chip,
        line_offset=args.line_offset,
        tag=args.tag,
        edge=args.edge,
        consumer=args.consumer,
        max_events=args.max_events,
        poll_timeout_ms=args.poll_timeout_ms,
        duration_seconds=args.duration_seconds,
    )

    try:
        written = run_gpio_edge_logger(config)
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"Error: {type(exc).__name__}: {exc}")
        return 1

    if written:
        print(f"Wrote {len(written)} GPIO value file(s) to {config.output_dir}")
    return 0
