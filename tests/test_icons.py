"""Tests for the code-drawn pixel icons."""

from __future__ import annotations

import pathlib

from PIL import Image

from weatherdisplay import icons
from weatherdisplay import palette


def test_every_slug_renders_on_palette() -> None:
    inks = set(palette.INKS)
    for slug in icons.SLUGS:
        for size in (16, 32, 96):
            image = icons.render(slug, size)
            assert image.size == (size, size)
            assert image.mode == "RGBA"
            # Flatten onto white (transparency becomes the white ink) so every
            # remaining colour must be one of the six panel inks.
            flat = Image.new("RGB", image.size, palette.WHITE)
            flat.paste(image, (0, 0), image)
            counted = flat.getcolors(maxcolors=4096)
            assert counted is not None
            for _, colour in counted:
                assert colour in inks, (slug, size, colour)


def test_export_writes_every_icon(tmp_path: pathlib.Path) -> None:
    icons.export(tmp_path, sizes=(16,))
    assert (tmp_path / "clear-day@16.png").is_file()
    assert len(list(tmp_path.glob("*.png"))) == len(icons.SLUGS)
