"""Tests for app orchestration: retries and wake scheduling (no network)."""

from __future__ import annotations

import dataclasses
import datetime
import logging

import pytest

from weatherdisplay import app
from weatherdisplay import config as config_lib
from weatherdisplay import display
from weatherdisplay import errors
from weatherdisplay import pisugar
from weatherdisplay import presets
from weatherdisplay import render
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


class _FakeSugar:
    """A PiSugar stand-in that records schedule_wake calls in a shared log."""

    def __init__(self, events: list[str]) -> None:
        self._events = events
        self.wakes: list[datetime.datetime] = []

    def read_battery(self) -> pisugar.BatteryStatus:
        raise errors.PiSugarError("no server in tests")

    def schedule_wake(self, at: datetime.datetime) -> None:
        self._events.append("schedule_wake")
        self.wakes.append(at)


def test_update_arms_wake_before_fetching(
    cfg: config_lib.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The wake-up must be armed before the network is touched, so the cadence
    # survives the process being killed mid-cycle (e.g. systemd start timeout).
    _no_sleep(monkeypatch)
    cfg = dataclasses.replace(cfg, auto_shutdown=False)
    events: list[str] = []
    sugar = _FakeSugar(events)
    monkeypatch.setattr(pisugar, "from_config", lambda _cfg: sugar)

    def failing_fetch(_cfg: config_lib.Config) -> weather.WeatherReport:
        events.append("fetch")
        raise errors.NetworkError("down")

    monkeypatch.setattr(weather, "fetch", failing_fetch)
    shown: list[str] = []
    monkeypatch.setattr(
        display,
        "show_error",
        lambda message, *args, **kwargs: shown.append(message),
    )

    app.update(cfg)

    assert events[0] == "schedule_wake"
    assert "fetch" in events
    assert events[-1] == "schedule_wake"  # backup re-arm in finally
    assert all(wake.tzinfo is not None for wake in sugar.wakes)
    assert shown and shown[0].startswith("Network error")


def test_maybe_shutdown_waits_for_panel_before_poweroff(
    cfg: config_lib.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The panel must have time to finish its refresh before power is cut,
    # otherwise the screen is left stuck half-drawn.
    delays = _no_sleep(monkeypatch)
    monkeypatch.setattr(app, "_active_sentinel", lambda: None)
    powered_off: list[bool] = []
    monkeypatch.setattr(app, "_poweroff", lambda _log: powered_off.append(True))

    app._maybe_shutdown(cfg, logging.getLogger("test"))

    assert delays == [30.0]
    assert powered_off == [True]


def test_maybe_shutdown_disabled_skips_delay_and_poweroff(
    cfg: config_lib.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    delays = _no_sleep(monkeypatch)
    cfg = dataclasses.replace(cfg, auto_shutdown=False)
    monkeypatch.setattr(
        app, "_poweroff", lambda _log: pytest.fail("must not power off")
    )

    app._maybe_shutdown(cfg, logging.getLogger("test"))

    assert delays == []


def test_update_schedules_wake_on_success(
    cfg: config_lib.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    cfg = dataclasses.replace(cfg, auto_shutdown=False)
    events: list[str] = []
    sugar = _FakeSugar(events)
    monkeypatch.setattr(pisugar, "from_config", lambda _cfg: sugar)
    report = presets.build("clear-day", cfg)
    monkeypatch.setattr(weather, "fetch", lambda _cfg: report)
    monkeypatch.setattr(render, "render_png", lambda *args, **kwargs: b"png")
    pushed: list[bytes] = []
    monkeypatch.setattr(
        display, "show", lambda png, *args, **kwargs: pushed.append(png)
    )

    app.update(cfg)

    assert pushed == [b"png"]
    assert events == ["schedule_wake", "schedule_wake"]
