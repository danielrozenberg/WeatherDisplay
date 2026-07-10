"""Orchestration for the two commands: ``update`` and ``dev``.

``update`` is the periodic job run on the Pi: schedule the next PiSugar
wake-up, read battery, fetch weather, render, show, then power off. Any
expected failure leaves the previous screen up with an error banner. ``dev``
just starts the local preview server.
"""

from __future__ import annotations

import datetime
import logging
import os
import pathlib
import subprocess
import time

from . import config as config_lib
from . import dev_server
from . import display
from . import errors
from . import logging_setup
from . import pisugar
from . import render
from . import weather

# Touch one of these files to keep the Pi awake (skip auto-shutdown) for
# maintenance/SSH. Bookworm mounts the boot partition at /boot/firmware.
_STAY_AWAKE_SENTINELS = (
    pathlib.Path("/boot/firmware/weatherdisplay-stayawake"),
    pathlib.Path("/boot/weatherdisplay-stayawake"),
)

# Exponential backoff between forecast-fetch retries (see _fetch_with_retries).
# The default cfg.fetch_retries=4 gives 2+4+8+16 = ~30s before giving up, enough
# to ride out WiFi/DNS not being ready yet right after a wake.
_RETRY_BASE_DELAY = 2.0
_RETRY_MAX_DELAY = 30.0

# Grace period before power-off so the Inky panel finishes its refresh cycle;
# cutting power mid-update leaves the screen stuck half-drawn.
_SHUTDOWN_DELAY_SECONDS = 30.0


def default_state_dir() -> pathlib.Path:
    """Returns the directory for persistent state (the last-good image)."""
    return pathlib.Path(os.environ.get("WEATHERDISPLAY_STATE", "state"))


def update(cfg: config_lib.Config) -> None:
    """Runs one update cycle: fetch, render, show, then sleep.

    Arms the next wake-up before touching the network or the panel, so the
    cadence survives the process dying mid-cycle; the ``finally`` re-arm covers
    pisugar-server not accepting connections yet right after boot.

    Args:
      cfg: The loaded configuration.
    """
    log = logging_setup.setup_logging(verbose=cfg.verbose)
    sugar = pisugar.from_config(cfg)
    last_image = default_state_dir() / "last_image.png"

    _schedule_next_wake(cfg, sugar, log)
    try:
        battery = _read_battery(sugar, log)
        log.info("fetching weather for %.3f, %.3f", cfg.latitude, cfg.longitude)
        report = _fetch_with_retries(cfg, log)
        png = render.render_png(report, battery, cfg)
        display.show(png, cfg.saturation, last_image_path=last_image)
        log.info("display updated")
    except errors.WeatherDisplayError as exc:
        log.error("update failed: %s", exc.user_message)
        _show_error(exc, cfg, last_image, log)
    finally:
        _schedule_next_wake(cfg, sugar, log)
        _maybe_shutdown(cfg, log)


def _fetch_with_retries(
    cfg: config_lib.Config, log: logging.Logger
) -> weather.WeatherReport:
    """Fetches the forecast, retrying network failures with exponential backoff.

    Rides out a network that is not ready yet (e.g. WiFi/DNS just after a wake):
    retries up to ``cfg.fetch_retries`` times before re-raising. Only
    ``NetworkError`` is retried — an ``ApiError`` (bad request, or a 5xx that
    already exhausted the HTTP-layer retries) will not fix itself.

    Raises:
      NetworkError: If every attempt failed to reach Open-Meteo.
      ApiError: If the response was an error status or unparseable.
    """
    attempts = cfg.fetch_retries + 1
    for attempt in range(1, attempts + 1):
        try:
            return weather.fetch(cfg)
        except errors.NetworkError as exc:
            if attempt >= attempts:
                raise
            delay = min(
                _RETRY_MAX_DELAY, _RETRY_BASE_DELAY * 2 ** (attempt - 1)
            )
            log.warning(
                "fetch attempt %d/%d failed: %s; retrying in %.0fs",
                attempt,
                attempts,
                exc.user_message,
                delay,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def dev(cfg: config_lib.Config) -> None:
    """Starts the local design-preview server.

    Args:
      cfg: The loaded configuration.
    """
    logging_setup.setup_logging(verbose=cfg.verbose)
    dev_server.serve(cfg)


def _read_battery(
    sugar: pisugar.PiSugar, log: logging.Logger
) -> pisugar.BatteryStatus | None:
    """Reads the battery, returning None (non-fatal) on failure."""
    try:
        status = sugar.read_battery()
        log.info(
            "battery %.0f%% (%s)",
            status.percent,
            "charging" if status.plugged else "on battery",
        )
        return status
    except errors.PiSugarError as exc:
        log.warning("could not read battery: %s", exc)
        return None


def _show_error(
    exc: errors.WeatherDisplayError,
    cfg: config_lib.Config,
    last_image: pathlib.Path,
    log: logging.Logger,
) -> None:
    """Overlays the error on the last-good screen, logging any push failure."""
    try:
        display.show_error(
            exc.user_message, cfg.saturation, last_image_path=last_image
        )
    except errors.DisplayError as derr:
        log.error("could not show error screen: %s", derr)


def _schedule_next_wake(
    cfg: config_lib.Config, sugar: pisugar.PiSugar, log: logging.Logger
) -> None:
    """Arms the next PiSugar wake-up; failure is logged but not fatal."""
    now = datetime.datetime.now(cfg.tzinfo)
    wake = pisugar.next_wake_time(now, cfg.wake_interval_hours)
    try:
        sugar.schedule_wake(wake)
        log.info("next wake scheduled for %s", wake.isoformat())
    except errors.PiSugarError as exc:
        log.error("could not schedule next wake: %s", exc)


def _maybe_shutdown(cfg: config_lib.Config, log: logging.Logger) -> None:
    """Powers off unless disabled in config or a stay-awake sentinel exists."""
    if not cfg.auto_shutdown:
        log.info("auto_shutdown disabled in config; staying awake")
        return
    sentinel = _active_sentinel()
    if sentinel is not None:
        log.info("stay-awake sentinel %s present; staying awake", sentinel)
        return
    log.info(
        "waiting %.0fs for the panel to settle, then powering off",
        _SHUTDOWN_DELAY_SECONDS,
    )
    time.sleep(_SHUTDOWN_DELAY_SECONDS)
    _poweroff(log)


def _active_sentinel() -> pathlib.Path | None:
    """Returns the first present stay-awake sentinel file, if any."""
    for path in _STAY_AWAKE_SENTINELS:
        if path.exists():
            return path
    return None


def _poweroff(log: logging.Logger) -> None:
    """Powers the system off via systemd, logging any failure."""
    try:
        subprocess.run(["systemctl", "poweroff"], check=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        log.error("poweroff failed (need privileges?): %s", exc)
