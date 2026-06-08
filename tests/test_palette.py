"""Tests for the Spectra-6 palette blend and quantization."""

from __future__ import annotations

import importlib.util

import pytest
from PIL import Image

from weatherdisplay import palette


def test_blend_endpoints() -> None:
    # At saturation 0 the blend equals the desaturated palette.
    desat = palette.palette_blend(0.0)
    assert desat[:3] == [0, 0, 0]
    assert desat[3:6] == [255, 255, 255]
    # At saturation 1 it equals the saturated palette.
    sat = palette.palette_blend(1.0)
    assert sat[3:6] == [161, 164, 165]


def test_blend_has_six_colours() -> None:
    assert len(palette.palette_blend(0.5)) == 6 * 3


def test_quantize_flat_ink_colour_does_not_dither() -> None:
    # Pure black matches a palette ink exactly, so it maps to one index.
    out = palette.quantize(Image.new("RGB", (32, 32), (0, 0, 0)), 0.5)
    assert out.mode == "P"
    assert len(out.getcolors() or []) == 1


def test_quantize_uses_at_most_six_inks() -> None:
    # An in-between colour dithers, but only across the six available inks.
    out = palette.quantize(Image.new("RGB", (32, 32), (123, 200, 50)), 0.5)
    assert len(out.getcolors() or []) <= 6


def test_simulate_eink_scales() -> None:
    src = Image.new("RGB", palette.EINK_SIZE, (255, 255, 255))
    out = palette.simulate_eink(src, 0.5, scale=2)
    assert out.size == (palette.EINK_SIZE[0] * 2, palette.EINK_SIZE[1] * 2)
    assert out.mode == "RGB"


@pytest.mark.skipif(
    importlib.util.find_spec("inky") is None,
    reason="inky (Pi-only) not installed",
)
def test_palettes_match_inky_driver() -> None:
    # Guards against our copied constants drifting from the real driver.
    from inky import inky_e673  # type: ignore[import-not-found]

    assert palette.DESATURATED_PALETTE == inky_e673.DESATURATED_PALETTE
    assert palette.SATURATED_PALETTE == inky_e673.SATURATED_PALETTE
