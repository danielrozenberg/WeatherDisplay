"""Tests for config loading and validation."""

from __future__ import annotations

import pathlib

import pytest

from weatherdisplay import config as config_lib
from weatherdisplay import errors

_VALID = """
latitude = 51.5
longitude = -0.12
timezone = "Europe/London"
saturation = 0.4
chart_hours = 12
day_chips = 7
"""


def _write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    path = tmp_path / "config.toml"
    path.write_text(text)
    return path


def test_loads_valid_config(tmp_path: pathlib.Path) -> None:
    cfg = config_lib.load_config(_write(tmp_path, _VALID))
    assert cfg.latitude == 51.5
    assert cfg.timezone == "Europe/London"
    assert cfg.chart_hours == 12
    assert cfg.day_chips == 7
    # Optional keys fall back to defaults.
    assert cfg.wake_interval_hours == 4
    assert cfg.primary_unit == "metric"


def test_tzinfo_resolves(tmp_path: pathlib.Path) -> None:
    cfg = config_lib.load_config(_write(tmp_path, _VALID))
    assert cfg.tzinfo.key == "Europe/London"


def test_missing_file_raises() -> None:
    with pytest.raises(errors.ConfigError, match="not found"):
        config_lib.load_config(pathlib.Path("/no/such/config.toml"))


def test_missing_required_key(tmp_path: pathlib.Path) -> None:
    with pytest.raises(errors.ConfigError, match="missing required"):
        config_lib.load_config(_write(tmp_path, "latitude = 1.0\n"))


def test_unknown_key_rejected(tmp_path: pathlib.Path) -> None:
    text = _VALID + "\nbogus_key = 1\n"
    with pytest.raises(errors.ConfigError, match="unknown key"):
        config_lib.load_config(_write(tmp_path, text))


def test_latitude_out_of_range(tmp_path: pathlib.Path) -> None:
    text = _VALID.replace("latitude = 51.5", "latitude = 200.0")
    with pytest.raises(errors.ConfigError, match="latitude"):
        config_lib.load_config(_write(tmp_path, text))


def test_invalid_timezone(tmp_path: pathlib.Path) -> None:
    text = _VALID.replace('"Europe/London"', '"Mars/Olympus"')
    with pytest.raises(errors.ConfigError, match="timezone"):
        config_lib.load_config(_write(tmp_path, text))


def test_bad_primary_unit(tmp_path: pathlib.Path) -> None:
    text = _VALID + '\nprimary_unit = "kelvin"\n'
    with pytest.raises(errors.ConfigError, match="primary_unit"):
        config_lib.load_config(_write(tmp_path, text))


def test_saturation_bounds(tmp_path: pathlib.Path) -> None:
    text = _VALID.replace("saturation = 0.4", "saturation = 1.7")
    with pytest.raises(errors.ConfigError, match="saturation"):
        config_lib.load_config(_write(tmp_path, text))


def test_fetch_retries_default(tmp_path: pathlib.Path) -> None:
    cfg = config_lib.load_config(_write(tmp_path, _VALID))
    assert cfg.fetch_retries == 4


def test_fetch_retries_out_of_range(tmp_path: pathlib.Path) -> None:
    text = _VALID + "fetch_retries = 11\n"
    with pytest.raises(errors.ConfigError, match="fetch_retries"):
        config_lib.load_config(_write(tmp_path, text))
