"""Hand-built ``WeatherReport`` scenarios for dev-mode preview.

Each preset returns a complete report so the renderer can be exercised on many
conditions (rainy, snowy, hot, cold, ...) without hitting the network. Dev mode
shows one button per preset; ``"live"`` (handled by the dev server) fetches the
real forecast instead.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Callable

from . import config as config_lib
from . import weather

# A fixed "now" so presets are deterministic across reloads.
_NOW = datetime.datetime(2026, 6, 15, 14, 30)


def _clampi(value: float) -> int:
    """Clamps to an int percentage in 0..100."""
    return max(0, min(100, round(value)))


def _build(
    cfg: config_lib.Config,
    *,
    temp_c: float,
    humidity: int,
    uv: float,
    code: int,
    is_day: bool,
    hour_amp: float,
    precip: int,
    day_codes: list[int],
    day_precip: int,
    sunrise: tuple[int, int],
    sunset: tuple[int, int],
) -> weather.WeatherReport:
    """Synthesizes a full report from a few scenario parameters."""
    now = _NOW.replace(tzinfo=cfg.tzinfo)
    hours = []
    for i in range(cfg.chart_hours):
        t = now + datetime.timedelta(hours=i)
        # Diurnal wave peaking mid-afternoon.
        wave = hour_amp * math.sin(2.0 * math.pi * (t.hour - 9) / 24.0)
        jitter = precip + 12 * math.sin(i / 1.7)
        hours.append(
            weather.HourPoint(
                time=t,
                temperature_c=round(temp_c + wave, 1),
                precipitation_probability=_clampi(jitter if precip else 0),
            )
        )
    base_day = now.date()
    days = []
    for i in range(cfg.day_chips):
        days.append(
            weather.DayChip(
                day=base_day + datetime.timedelta(days=i),
                weather_code=day_codes[i % len(day_codes)],
                temp_min_c=round(temp_c - 5.0, 1),
                temp_max_c=round(temp_c + 4.0, 1),
                precipitation_probability=_clampi(day_precip + 8 * math.sin(i)),
            )
        )
    return weather.WeatherReport(
        fetched_at=now,
        temperature_c=temp_c,
        humidity=humidity,
        uv_index=uv,
        weather_code=code,
        is_day=is_day,
        sunrise=now.replace(hour=sunrise[0], minute=sunrise[1]),
        sunset=now.replace(hour=sunset[0], minute=sunset[1]),
        hours=hours,
        days=days,
    )


def _clear_day(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=24.0,
        humidity=40,
        uv=7.0,
        code=0,
        is_day=True,
        hour_amp=5.0,
        precip=0,
        day_codes=[0, 1, 2, 0, 1],
        day_precip=5,
        sunrise=(6, 0),
        sunset=(20, 30),
    )


def _clear_night(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=13.0,
        humidity=72,
        uv=0.0,
        code=0,
        is_day=False,
        hour_amp=3.0,
        precip=0,
        day_codes=[0, 1, 0, 2, 1],
        day_precip=5,
        sunrise=(6, 0),
        sunset=(20, 30),
    )


def _partly_cloudy(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=18.0,
        humidity=55,
        uv=5.0,
        code=2,
        is_day=True,
        hour_amp=4.0,
        precip=20,
        day_codes=[2, 3, 1, 2, 80],
        day_precip=25,
        sunrise=(6, 10),
        sunset=(20, 10),
    )


def _rainy(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=12.0,
        humidity=92,
        uv=1.0,
        code=63,
        is_day=True,
        hour_amp=2.0,
        precip=80,
        day_codes=[61, 63, 65, 80, 51],
        day_precip=85,
        sunrise=(6, 20),
        sunset=(20, 0),
    )


def _snowy(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=-2.0,
        humidity=88,
        uv=1.0,
        code=73,
        is_day=True,
        hour_amp=2.0,
        precip=75,
        day_codes=[71, 73, 75, 85, 86],
        day_precip=80,
        sunrise=(7, 40),
        sunset=(17, 0),
    )


def _thunderstorm(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=22.0,
        humidity=80,
        uv=3.0,
        code=95,
        is_day=True,
        hour_amp=3.0,
        precip=65,
        day_codes=[95, 96, 80, 63, 2],
        day_precip=70,
        sunrise=(6, 5),
        sunset=(20, 20),
    )


def _fog(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=8.0,
        humidity=96,
        uv=1.0,
        code=45,
        is_day=True,
        hour_amp=2.0,
        precip=10,
        day_codes=[45, 3, 2, 48, 1],
        day_precip=15,
        sunrise=(6, 30),
        sunset=(19, 40),
    )


def _hot(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=39.0,
        humidity=22,
        uv=11.0,
        code=0,
        is_day=True,
        hour_amp=6.0,
        precip=0,
        day_codes=[0, 0, 1, 0, 2],
        day_precip=0,
        sunrise=(5, 40),
        sunset=(20, 50),
    )


def _cold(cfg: config_lib.Config) -> weather.WeatherReport:
    return _build(
        cfg,
        temp_c=-8.0,
        humidity=68,
        uv=2.0,
        code=0,
        is_day=True,
        hour_amp=3.0,
        precip=10,
        day_codes=[0, 1, 71, 0, 2],
        day_precip=20,
        sunrise=(8, 0),
        sunset=(16, 30),
    )


PRESETS: dict[str, Callable[[config_lib.Config], weather.WeatherReport]] = {
    "clear-day": _clear_day,
    "clear-night": _clear_night,
    "partly-cloudy": _partly_cloudy,
    "rainy": _rainy,
    "snowy": _snowy,
    "thunderstorm": _thunderstorm,
    "fog": _fog,
    "hot": _hot,
    "cold": _cold,
}


def names() -> tuple[str, ...]:
    """Returns the preset names, in display order."""
    return tuple(PRESETS)


def build(name: str, cfg: config_lib.Config) -> weather.WeatherReport:
    """Builds the preset ``name`` for ``cfg`` (raises KeyError if unknown)."""
    return PRESETS[name](cfg)
