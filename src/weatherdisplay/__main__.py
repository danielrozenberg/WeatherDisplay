"""Command-line entry point: ``weatherdisplay {update,dev}``."""

from __future__ import annotations

import argparse
import pathlib
import sys

from . import app
from . import config as config_lib
from . import errors


def build_parser() -> argparse.ArgumentParser:
    """Builds the argument parser for the ``weatherdisplay`` command."""
    parser = argparse.ArgumentParser(
        prog="weatherdisplay",
        description="E-ink weather display for the Raspberry Pi.",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=config_lib.DEFAULT_CONFIG_PATH,
        metavar="PATH",
        help="path to the TOML config file (default: config.toml)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "update",
        help="fetch, render, show on the panel, then schedule wake & power off",
    )
    sub.add_parser("dev", help="run the local design-preview web server")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parses arguments, loads config, and runs the chosen command.

    Args:
      argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
      A process exit code.
    """
    args = build_parser().parse_args(argv)

    try:
        cfg = config_lib.load_config(args.config)
    except errors.ConfigError as exc:
        print(f"Configuration error: {exc.user_message}", file=sys.stderr)
        return 2

    if args.command == "update":
        app.update(cfg)
    elif args.command == "dev":
        app.dev(cfg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
