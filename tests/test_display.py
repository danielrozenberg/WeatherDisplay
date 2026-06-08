"""Tests for the error-overlay compositing (no hardware needed)."""

from __future__ import annotations

from PIL import Image

from weatherdisplay import display
from weatherdisplay import palette
from weatherdisplay import wmo


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
