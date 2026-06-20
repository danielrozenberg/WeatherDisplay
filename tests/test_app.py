"""Tests for app orchestration: the forecast-fetch retry loop (no network)."""

from __future__ import annotations

import dataclasses
import logging

import pytest

from weatherdisplay import app
from weatherdisplay import config as config_lib
from weatherdisplay import errors
from weatherdisplay import presets
from weatherdisplay import weather


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replaces time.sleep with a recorder and returns the captured delays."""
    delays: list[float] = []
    monkeypatch.setattr(app.time, "sleep", lambda s: delays.append(s))
    return delays


def test_fetch_retries_until_success(
    cfg: config_lib.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _no_sleep(monkeypatch)
    report = presets.build("clear-day", cfg)
    calls = {"n": 0}

    def flaky(_cfg: config_lib.Config) -> weather.WeatherReport:
        calls["n"] += 1
        if calls["n"] < 3:
            raise errors.NetworkError("no route")
        return report

    monkeypatch.setattr(weather, "fetch", flaky)
    out = app._fetch_with_retries(cfg, logging.getLogger("test"))
    assert out is report
    assert calls["n"] == 3
    assert delays == [2.0, 4.0]  # exponential backoff before each retry


def test_fetch_retries_exhausted_reraises(
    cfg: config_lib.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _no_sleep(monkeypatch)
    cfg = dataclasses.replace(cfg, fetch_retries=2)
    calls = {"n": 0}

    def always_fail(_cfg: config_lib.Config) -> weather.WeatherReport:
        calls["n"] += 1
        raise errors.NetworkError("down")

    monkeypatch.setattr(weather, "fetch", always_fail)
    with pytest.raises(errors.NetworkError):
        app._fetch_with_retries(cfg, logging.getLogger("test"))
    assert calls["n"] == 3  # one initial try + fetch_retries
    assert delays == [2.0, 4.0]  # slept before each retry, not after the last


def test_fetch_does_not_retry_api_error(
    cfg: config_lib.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _no_sleep(monkeypatch)
    calls = {"n": 0}

    def api_error(_cfg: config_lib.Config) -> weather.WeatherReport:
        calls["n"] += 1
        raise errors.ApiError("HTTP 400")

    monkeypatch.setattr(weather, "fetch", api_error)
    with pytest.raises(errors.ApiError):
        app._fetch_with_retries(cfg, logging.getLogger("test"))
    assert calls["n"] == 1  # ApiError is not retried
    assert delays == []
