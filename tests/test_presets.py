"""Tests for the dev-mode weather presets."""

from __future__ import annotations

from weatherdisplay import config as config_lib
from weatherdisplay import icons
from weatherdisplay import presets
from weatherdisplay import weather


def test_all_presets_build_valid_reports(cfg: config_lib.Config) -> None:
    for name in presets.names():
        report = presets.build(name, cfg)
        assert isinstance(report, weather.WeatherReport)
        assert len(report.hours) == cfg.chart_hours
        assert len(report.days) == cfg.day_chips
        assert report.condition.icon in icons.SLUGS
        for day in report.days:
            assert day.condition.icon in icons.SLUGS
        for hour in report.hours:
            assert 0 <= hour.precipitation_probability <= 100


def test_build_unknown_preset_raises(cfg: config_lib.Config) -> None:
    import pytest

    with pytest.raises(KeyError):
        presets.build("nope", cfg)
