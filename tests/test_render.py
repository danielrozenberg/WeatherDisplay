"""Tests for the Pillow panel renderer."""

from __future__ import annotations

from weatherdisplay import config as config_lib
from weatherdisplay import palette
from weatherdisplay import pisugar
from weatherdisplay import presets
from weatherdisplay import render

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def test_render_image_size_and_palette(cfg: config_lib.Config) -> None:
    battery = pisugar.BatteryStatus(percent=72, plugged=True)
    inks = set(palette.INKS)
    for name in presets.names():
        image = render.render_image(presets.build(name, cfg), battery, cfg)
        assert image.size == palette.EINK_SIZE
        assert image.mode == "RGB"
        counted = image.getcolors(maxcolors=1 << 20)
        assert counted is not None
        for _, colour in counted:
            assert colour in inks, (name, colour)


def test_render_png_returns_png_bytes(cfg: config_lib.Config) -> None:
    data = render.render_png(presets.build("rainy", cfg), None, cfg)
    assert data[:8] == _PNG_MAGIC


def test_render_handles_empty_hours(cfg: config_lib.Config) -> None:
    import dataclasses

    report = dataclasses.replace(presets.build("clear-day", cfg), hours=[])
    image = render.render_image(report, None, cfg)
    assert image.size == palette.EINK_SIZE
