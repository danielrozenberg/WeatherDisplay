"""Shared test fixtures."""

from __future__ import annotations

import pytest

from weatherdisplay import config as config_lib


def make_config(**overrides: object) -> config_lib.Config:
    """Builds a valid Config with sensible defaults, overridable per test."""
    base: dict[str, object] = {
        "latitude": 51.5074,
        "longitude": -0.1278,
        "timezone": "Europe/London",
        "primary_unit": "metric",
        "saturation": 0.5,
        "chart_hours": 16,
        "day_chips": 10,
        "wake_interval_hours": 4,
        "auto_shutdown": True,
        "pisugar_host": "127.0.0.1",
        "pisugar_port": 8423,
        "dev_port": 8080,
        "verbose": False,
    }
    base.update(overrides)
    return config_lib.Config(**base)  # type: ignore[arg-type]


@pytest.fixture
def cfg() -> config_lib.Config:
    """A default metric configuration for London."""
    return make_config()
