"""Tests for the presentation/view-model layer."""

from __future__ import annotations

import dataclasses
import datetime

from weatherdisplay import config as config_lib
from weatherdisplay import pisugar
from weatherdisplay import viewmodel
from weatherdisplay import weather


def _report(cfg: config_lib.Config, n_hours: int = 4) -> weather.WeatherReport:
    now = datetime.datetime(2026, 6, 6, 14, 0, tzinfo=cfg.tzinfo)
    hours = [
        weather.HourPoint(
            time=now + datetime.timedelta(hours=i),
            temperature_c=10.0 + i,
            precipitation_probability=10 * i,
        )
        for i in range(n_hours)
    ]
    days = [
        weather.DayChip(
            day=now.date() + datetime.timedelta(days=i),
            weather_code=0,
            temp_min_c=8.0,
            temp_max_c=18.0,
            precipitation_probability=25,
        )
        for i in range(3)
    ]
    return weather.WeatherReport(
        fetched_at=now,
        temperature_c=14.0,
        humidity=60,
        uv_index=5.0,
        weather_code=0,
        is_day=True,
        wind_speed=12.0,
        wind_direction=315,
        sunrises=[now.replace(hour=4, minute=45)],
        sunsets=[now.replace(hour=21, minute=14)],
        hours=hours,
        days=days,
        air_quality=42,
    )


def test_header_metric(cfg: config_lib.Config) -> None:
    view = viewmodel.build_view(_report(cfg), None, cfg)
    assert view.header.temp_primary == "14"
    assert view.header.unit_primary == "C"
    assert view.header.temp_secondary == "57°F"
    assert view.header.uv_label == "Moderate"


def test_header_imperial(cfg: config_lib.Config) -> None:
    cfg = dataclasses.replace(cfg, primary_unit="imperial")
    view = viewmodel.build_view(_report(cfg), None, cfg)
    assert view.header.unit_primary == "F"
    assert view.header.temp_primary == "57"
    assert view.header.temp_secondary == "14°C"


def test_first_chip_is_today(cfg: config_lib.Config) -> None:
    view = viewmodel.build_view(_report(cfg), None, cfg)
    assert view.chips[0].label == "Today"
    assert view.chips[1].label != "Today"


def test_battery_none_is_low(cfg: config_lib.Config) -> None:
    view = viewmodel.build_view(_report(cfg), None, cfg)
    assert view.battery_low is True
    assert view.battery_pct == 0


def test_battery_passthrough(cfg: config_lib.Config) -> None:
    battery = pisugar.BatteryStatus(percent=80.0, plugged=False)
    view = viewmodel.build_view(_report(cfg), battery, cfg)
    assert view.battery_pct == 80
    assert view.battery_low is False


def test_chart_bars_carry_plot_data(cfg: config_lib.Config) -> None:
    view = viewmodel.build_view(_report(cfg, n_hours=4), None, cfg)
    assert len(view.chart.bars) == 4
    for bar in view.chart.bars:
        assert bar.hour_label  # non-empty
        assert bar.temp_label.endswith("°")
        assert isinstance(bar.temp_value, float)
        assert bar.precip_pct % 10 == 0  # rounded to the nearest 10


def test_empty_chart_is_safe(cfg: config_lib.Config) -> None:
    report = dataclasses.replace(_report(cfg), hours=[])
    view = viewmodel.build_view(report, None, cfg)
    assert view.chart.bars == []
