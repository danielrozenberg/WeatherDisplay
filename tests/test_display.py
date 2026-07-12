"""Tests for the error-overlay compositing and the panel busy-wait."""

from __future__ import annotations

import enum
import sys
import types

import pytest
from PIL import Image

from weatherdisplay import display
from weatherdisplay import palette
from weatherdisplay import wmo


class _Value(enum.Enum):
    """Stand-in for gpiod.line.Value (gpiod is Pi-only)."""

    ACTIVE = 1
    INACTIVE = 0


def _install_fake_gpiod(monkeypatch: pytest.MonkeyPatch) -> None:
    """Injects a minimal gpiod stub so _wait_until_idle can import it."""
    line = types.ModuleType("gpiod.line")
    line.Value = _Value  # type: ignore[attr-defined]
    gpiod = types.ModuleType("gpiod")
    gpiod.line = line  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "gpiod", gpiod)
    monkeypatch.setitem(sys.modules, "gpiod.line", line)


def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Replaces display's time.sleep with a recorder, returning the delays."""
    delays: list[float] = []
    monkeypatch.setattr(display.time, "sleep", lambda s: delays.append(s))
    return delays


class _FakeDevice:
    """An inky-device stand-in whose BUSY line yields canned readings."""

    def __init__(self, readings: list[_Value]) -> None:
        self._readings = readings
        self.busy_pin = 17
        self._gpio = self

    def get_value(self, pin: int) -> _Value:
        assert pin == self.busy_pin
        if len(self._readings) > 1:
            return self._readings.pop(0)
        return self._readings[0]


class _FakeDriver:
    """Records _busy_wait timeouts like the inky driver would receive them."""

    def __init__(self) -> None:
        self.timeouts: list[float] = []

    def _busy_wait(self, timeout: float = 40.0) -> None:
        self.timeouts.append(timeout)


def test_patch_busy_wait_extends_refresh_wait_only() -> None:
    driver = _FakeDriver()
    display._patch_busy_wait(driver)

    driver._busy_wait(0.3)  # housekeeping waits keep their short timeout
    driver._busy_wait(32.0)  # the refresh wait gets the generous ceiling
    driver._busy_wait()

    assert driver.timeouts == [0.3, 120.0, 120.0]


def test_patch_busy_wait_skips_unknown_driver() -> None:
    display._patch_busy_wait(object())  # must not raise


def test_wait_until_idle_polls_busy_line_until_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_gpiod(monkeypatch)
    delays = _no_sleep(monkeypatch)
    device = _FakeDevice([_Value.INACTIVE, _Value.INACTIVE, _Value.ACTIVE])

    display._wait_until_idle(device)

    # Slept once per busy reading, never the blind fallback.
    assert delays == [0.2, 0.2]


def test_wait_until_idle_returns_fast_when_already_idle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_gpiod(monkeypatch)
    delays = _no_sleep(monkeypatch)

    display._wait_until_idle(_FakeDevice([_Value.ACTIVE]))

    assert delays == []


def test_wait_until_idle_sleeps_fallback_without_busy_line(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_gpiod(monkeypatch)
    delays = _no_sleep(monkeypatch)

    display._wait_until_idle(object())  # no _gpio / busy_pin attributes

    assert delays == [30.0]


def test_wait_until_idle_gives_up_after_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_fake_gpiod(monkeypatch)
    delays = _no_sleep(monkeypatch)
    clock = {"now": 0.0}

    def fake_monotonic() -> float:
        clock["now"] += 60.0
        return clock["now"]

    monkeypatch.setattr(display.time, "monotonic", fake_monotonic)

    display._wait_until_idle(_FakeDevice([_Value.INACTIVE]))

    # Gave up polling after the deadline instead of spinning forever.
    assert 0.2 in delays
    assert 30.0 not in delays


def test_overlay_on_blank_returns_panel_sized_rgb() -> None:
    out = display.overlay_error(None, "Network error: offline")
    assert out.size == palette.EINK_SIZE
    assert out.mode == "RGB"


def test_overlay_preserves_base_size() -> None:
    base = Image.new("RGB", (400, 240), (255, 255, 255))
    out = display.overlay_error(base, "API error: bad response")
    # The base is resized up to the panel resolution.
    assert out.size == palette.EINK_SIZE


def test_overlay_draws_red_banner() -> None:
    out = display.overlay_error(None, "Render error: boom")
    # Sample a point inside the banner, away from the left-aligned text.
    pixel = out.getpixel((out.width - 100, out.height // 2))
    assert isinstance(pixel, tuple)
    assert pixel[0] > 150 and pixel[1] < 90 and pixel[2] < 90


def test_wmo_unknown_code_falls_back() -> None:
    cond = wmo.describe(999, is_day=True)
    assert cond.icon == "cloudy"
    assert cond.label == "Unknown"


def test_wmo_day_night_variants() -> None:
    assert wmo.describe(0, is_day=True).icon == "clear-day"
    assert wmo.describe(0, is_day=False).icon == "clear-night"
