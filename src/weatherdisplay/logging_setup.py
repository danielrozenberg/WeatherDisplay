"""Logging configuration.

The ``update`` job runs as a systemd ``oneshot`` service with
``StandardOutput=journal``, so anything written to stdout/stderr is captured by
the systemd journal automatically — that is the "most reasonable point" to wire
into the Pi's logging. We therefore just configure Python's ``logging`` to write
a clean, timestamped line to stdout; journald adds its own metadata on top.

Read the logs on the Pi with::

    journalctl -u weatherdisplay
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(*, verbose: bool = False) -> logging.Logger:
    """Configure root logging once and return the package logger.

    Args:
        verbose: when True, log at DEBUG level; otherwise INFO.
    """
    global _CONFIGURED
    level = logging.DEBUG if verbose else logging.INFO

    if not _CONFIGURED:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        root = logging.getLogger()
        root.handlers.clear()
        root.addHandler(handler)
        _CONFIGURED = True

    logging.getLogger().setLevel(level)
    return logging.getLogger("weatherdisplay")
