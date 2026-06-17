"""Tests for Open-Meteo parsing and unit conversion."""

from __future__ import annotations

import dataclasses
import datetime

import pytest

from weatherdisplay import config as config_lib
from weatherdisplay import errors
from weatherdisplay import weather

_PAYLOAD: weather.ForecastPayload = {
    "current": {
        "temperature_2m": 14.3,
        "relative_humidity_2m": 63,
        "weather_code": 2,
        "uv_index": 5.2,
        "is_day": 1,
    },
    "hourly": {
        "time": [
            "2026-06-06T13:00",
            "2026-06-06T14:00",
            "2026-06-06T15:00",
            "2026-06-06T16:00",
        ],
        "temperature_2m": [13.0, 14.0, 15.0, 16.0],
        "precipitation_probability": [10, 20, None, 40],
    },
    "daily": {
        "time": ["2026-06-06", "2026-06-07", "2026-06-08"],
        "weather_code": [2, 61, 0],
        "temperature_2m_max": [18.0, 17.0, 20.0],
        "temperature_2m_min": [8.0, 9.0, 10.0],
        "precipitation_probability_max": [20, 80, 5],
        "sunrise": ["2026-06-06T04:45", "2026-06-07T04:44", "2026-06-08T04:44"],
        "sunset": ["2026-06-06T21:14", "2026-06-07T21:15", "2026-06-08T21:16"],
        "uv_index_max": [6.0, 5.0, 7.0],
    },
}


def _now(cfg: config_lib.Config) -> datetime.datetime:
    return datetime.datetime(2026, 6, 6, 14, 32, tzinfo=cfg.tzinfo)


def test_celsius_to_fahrenheit() -> None:
    assert weather.celsius_to_fahrenheit(0) == 32.0
    assert weather.celsius_to_fahrenheit(100) == 212.0


def test_parse_current(cfg: config_lib.Config) -> None:
    report = weather.parse(_PAYLOAD, cfg, now=_now(cfg))
    assert report.temperature_c == 14.3
    assert report.humidity == 63
    assert report.uv_index == 5.2
    assert report.is_day is True
    assert report.condition.label == "Partly cloudy"
    assert round(report.temperature_f) == 58


def test_parse_hours_start_at_current_hour(cfg: config_lib.Config) -> None:
    report = weather.parse(_PAYLOAD, cfg, now=_now(cfg))
    # 13:00 is before the 14:00 current hour and is dropped.
    assert [h.time.hour for h in report.hours] == [14, 15, 16]
    assert report.hours[0].temperature_c == 14.0
    # A null precipitation probability becomes 0.
    assert report.hours[1].precipitation_probability == 0


def test_parse_sun_times(cfg: config_lib.Config) -> None:
    report = weather.parse(_PAYLOAD, cfg, now=_now(cfg))
    assert (report.sunrise.hour, report.sunrise.minute) == (4, 45)
    assert (report.sunset.hour, report.sunset.minute) == (21, 14)


def test_parse_days(cfg: config_lib.Config) -> None:
    report = weather.parse(_PAYLOAD, cfg, now=_now(cfg))
    assert len(report.days) == 3
    chip = report.days[1]
    assert chip.weather_code == 61
    assert chip.temp_max_c == 17.0
    assert chip.precipitation_probability == 80


def test_day_chips_respects_limit(cfg: config_lib.Config) -> None:
    cfg = dataclasses.replace(cfg, day_chips=2)
    report = weather.parse(_PAYLOAD, cfg, now=_now(cfg))
    assert len(report.days) == 2


def test_parse_malformed_response_raises(cfg: config_lib.Config) -> None:
    # A structurally-valid payload with empty daily arrays trips the guard
    # (daily["sunrise"][0] -> IndexError -> ApiError "response shape").
    empty_daily: weather.DailyBlock = {
        "time": [],
        "weather_code": [],
        "temperature_2m_max": [],
        "temperature_2m_min": [],
        "precipitation_probability_max": [],
        "sunrise": [],
        "sunset": [],
        "uv_index_max": [],
    }
    bad: weather.ForecastPayload = {
        "current": _PAYLOAD["current"],
        "hourly": _PAYLOAD["hourly"],
        "daily": empty_daily,
    }
    with pytest.raises(errors.ApiError, match="response shape"):
        weather.parse(bad, cfg, now=_now(cfg))


def test_chart_min_max(cfg: config_lib.Config) -> None:
    report = weather.parse(_PAYLOAD, cfg, now=_now(cfg))
    assert report.chart_min_c == 14.0
    assert report.chart_max_c == 16.0
