"""Pixel-art icons, behind a swappable provider seam.

The renderer asks ``render(slug, size)`` for an on-palette RGBA glyph and never
cares where it came from. Today the default ``CodeIconProvider`` draws each
glyph in Pillow on a 16x16 grid with hard (non-antialiased) edges, then
nearest-scales to the requested size, so everything stays crisp and uses the six
panel inks. Two escape hatches keep future options open:

* ``export(dir)`` freezes the code-drawn icons to PNG files, and
* ``AssetIconProvider`` loads ``<slug>.png`` files instead —

so the icons can later be frozen to assets or replaced by hand-made art by
swapping ``default_provider``, with no change to the renderer.
"""

from __future__ import annotations

import pathlib
from typing import Protocol

from PIL import Image
from PIL import ImageDraw

from . import palette

# The grid every code icon is drawn on; scaled up (nearest) to the target size.
_GRID = 16

# Inks as RGBA (opaque); transparent is the empty background.
_K = (*palette.BLACK, 255)
_W = (*palette.WHITE, 255)
_Y = (*palette.YELLOW, 255)
_R = (*palette.RED, 255)
_B = (*palette.BLUE, 255)
_G = (*palette.GREEN, 255)
_CLEAR = (0, 0, 0, 0)

# The full set of slugs the renderer may request (weather + UI glyphs).
SLUGS = (
    "clear-day",
    "clear-night",
    "partly-cloudy-day",
    "partly-cloudy-night",
    "cloudy",
    "fog",
    "drizzle",
    "rain",
    "sleet",
    "snow",
    "thunderstorm",
    "humidity",
    "uv",
    "sunrise",
    "sunset",
    "droplet",
)

type _Draw = ImageDraw.ImageDraw


# --------------------------------------------------------------------------- #
# Shared motifs (all drawn on the 16x16 grid)
# --------------------------------------------------------------------------- #
def _sun(d: _Draw, cx: int, cy: int, r: int, *, rays: bool) -> None:
    """Draws a yellow sun centred at ``(cx, cy)`` with optional rays."""
    if rays:
        for x0, y0, x1, y1 in (
            (cx, cy - r - 3, cx, cy - r - 1),
            (cx, cy + r + 1, cx, cy + r + 3),
            (cx - r - 3, cy, cx - r - 1, cy),
            (cx + r + 1, cy, cx + r + 3, cy),
            (cx - r - 2, cy - r - 2, cx - r - 1, cy - r - 1),
            (cx + r + 1, cy + r + 1, cx + r + 2, cy + r + 2),
            (cx - r - 2, cy + r + 2, cx - r - 1, cy + r + 1),
            (cx + r + 1, cy - r - 1, cx + r + 2, cy - r - 2),
        ):
            d.line((x0, y0, x1, y1), fill=_Y)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=_Y, outline=_K)


def _moon(d: _Draw) -> None:
    """Draws a yellow crescent moon (carved out of a disc)."""
    d.ellipse((3, 3, 12, 12), fill=_Y, outline=_K)
    d.ellipse((6, 1, 14, 10), fill=_CLEAR)


def _cloud(d: _Draw, top: int, *, fill=_W) -> None:
    """Draws a black-outlined cloud whose body starts at row ``top``."""
    # Silhouette (black), then the fill inset by 1px to leave an outline.
    d.ellipse((1, top + 3, 8, top + 9), fill=_K)
    d.ellipse((5, top, 14, top + 9), fill=_K)
    d.rectangle((2, top + 6, 13, top + 9), fill=_K)
    d.ellipse((2, top + 4, 7, top + 8), fill=fill)
    d.ellipse((6, top + 1, 13, top + 8), fill=fill)
    d.rectangle((3, top + 6, 12, top + 8), fill=fill)


def _streaks(d: _Draw, colour, top: int, *, dotted: bool = False) -> None:
    """Draws three precipitation streaks (or dots) below a cloud."""
    for x in (4, 8, 11):
        if dotted:
            d.point((x, top + 1), fill=colour)
            d.point((x, top + 3), fill=colour)
        else:
            d.line((x, top, x - 1, top + 3), fill=colour)


def _flake(d: _Draw, x: int, y: int, colour) -> None:
    """Draws a small plus-shaped snowflake at ``(x, y)``."""
    d.line((x - 1, y, x + 1, y), fill=colour)
    d.line((x, y - 1, x, y + 1), fill=colour)


def _droplet(d: _Draw, cx: int, cy: int, colour) -> None:
    """Draws a teardrop centred roughly at ``(cx, cy)``."""
    d.ellipse((cx - 3, cy - 1, cx + 3, cy + 5), fill=colour, outline=_K)
    d.polygon(
        ((cx, cy - 5), (cx - 3, cy + 1), (cx + 3, cy + 1)),
        fill=colour,
        outline=_K,
    )
    d.polygon(((cx, cy - 3), (cx - 2, cy + 1), (cx + 2, cy + 1)), fill=colour)


def _horizon_sun(d: _Draw, *, arrow_up: bool) -> None:
    """Draws a half-sun on a horizon with an up/down arrow (sunrise/sunset)."""
    d.ellipse((4, 6, 11, 13), fill=_Y, outline=_K)
    d.rectangle((0, 11, 15, 15), fill=_CLEAR)
    d.line((1, 11, 14, 11), fill=_K)  # horizon
    ay = 2 if arrow_up else 4
    d.line((7, ay, 7, ay + 3), fill=_K)
    if arrow_up:
        d.line((5, ay + 2, 7, ay), fill=_K)
        d.line((9, ay + 2, 7, ay), fill=_K)
    else:
        d.line((5, ay + 1, 7, ay + 3), fill=_K)
        d.line((9, ay + 1, 7, ay + 3), fill=_K)


# --------------------------------------------------------------------------- #
# One drawer per slug
# --------------------------------------------------------------------------- #
def _clear_day(d: _Draw) -> None:
    _sun(d, 8, 8, 3, rays=True)


def _clear_night(d: _Draw) -> None:
    _moon(d)


def _partly_cloudy_day(d: _Draw) -> None:
    _sun(d, 10, 5, 2, rays=True)
    _cloud(d, 6)


def _partly_cloudy_night(d: _Draw) -> None:
    _moon(d)
    _cloud(d, 7)


def _cloudy(d: _Draw) -> None:
    _cloud(d, 4)


def _fog(d: _Draw) -> None:
    _cloud(d, 2)
    for y in (12, 14):
        d.line((2, y, 13, y), fill=_K)


def _drizzle(d: _Draw) -> None:
    _cloud(d, 2)
    _streaks(d, _B, 12, dotted=True)


def _rain(d: _Draw) -> None:
    _cloud(d, 2)
    _streaks(d, _B, 12)


def _sleet(d: _Draw) -> None:
    _cloud(d, 2)
    _streaks(d, _B, 12)
    _flake(d, 8, 14, _W)


def _snow(d: _Draw) -> None:
    _cloud(d, 2)
    for x, y in ((4, 13), (8, 14), (11, 13)):
        _flake(d, x, y, _B)


def _thunderstorm(d: _Draw) -> None:
    _cloud(d, 2)
    d.polygon(((8, 11), (6, 14), (8, 14), (7, 16), (11, 12), (8, 12)), fill=_Y)


def _humidity(d: _Draw) -> None:
    _droplet(d, 8, 8, _B)


def _uv(d: _Draw) -> None:
    _sun(d, 8, 8, 4, rays=True)


def _sunrise(d: _Draw) -> None:
    _horizon_sun(d, arrow_up=True)


def _sunset(d: _Draw) -> None:
    _horizon_sun(d, arrow_up=False)


def _droplet_icon(d: _Draw) -> None:
    _droplet(d, 8, 8, _B)


_DRAWERS = {
    "clear-day": _clear_day,
    "clear-night": _clear_night,
    "partly-cloudy-day": _partly_cloudy_day,
    "partly-cloudy-night": _partly_cloudy_night,
    "cloudy": _cloudy,
    "fog": _fog,
    "drizzle": _drizzle,
    "rain": _rain,
    "sleet": _sleet,
    "snow": _snow,
    "thunderstorm": _thunderstorm,
    "humidity": _humidity,
    "uv": _uv,
    "sunrise": _sunrise,
    "sunset": _sunset,
    "droplet": _droplet_icon,
}


# --------------------------------------------------------------------------- #
# Providers
# --------------------------------------------------------------------------- #
class IconProvider(Protocol):
    """Anything that can produce an on-palette RGBA glyph for a slug."""

    def render(self, slug: str, size: int) -> Image.Image:
        """Returns a ``size``x``size`` RGBA image for ``slug``."""
        ...


class CodeIconProvider:
    """Draws each glyph in Pillow on the 16x16 grid, then nearest-scales it."""

    def __init__(self) -> None:
        """Starts with an empty render cache."""
        self._cache: dict[tuple[str, int], Image.Image] = {}

    def render(self, slug: str, size: int) -> Image.Image:
        """Returns the cached ``size``x``size`` glyph for ``slug``."""
        key = (slug, size)
        cached = self._cache.get(key)
        if cached is None:
            base = Image.new("RGBA", (_GRID, _GRID), _CLEAR)
            drawer = _DRAWERS.get(slug, _cloudy)
            drawer(ImageDraw.Draw(base))
            cached = base.resize((size, size), Image.Resampling.NEAREST)
            self._cache[key] = cached
        return cached


class AssetIconProvider:
    """Loads ``<slug>.png`` from a directory and nearest-scales it."""

    def __init__(self, directory: pathlib.Path) -> None:
        """Stores the asset directory; files are loaded lazily on render."""
        self._dir = directory
        self._cache: dict[tuple[str, int], Image.Image] = {}

    def render(self, slug: str, size: int) -> Image.Image:
        """Returns the ``size``x``size`` glyph loaded from ``<slug>.png``."""
        key = (slug, size)
        cached = self._cache.get(key)
        if cached is None:
            path = self._dir / f"{slug}.png"
            base = Image.open(path).convert("RGBA")
            cached = base.resize((size, size), Image.Resampling.NEAREST)
            self._cache[key] = cached
        return cached


# The active provider. Swap this to change where icons come from.
default_provider: IconProvider = CodeIconProvider()


def render(slug: str, size: int) -> Image.Image:
    """Renders ``slug`` at ``size`` using the active provider."""
    return default_provider.render(slug, size)


def export(
    directory: pathlib.Path, sizes: tuple[int, ...] = (16, 32, 96)
) -> None:
    """Writes each code icon to ``<slug>@<size>.png`` under ``directory``.

    Lets the code icons be frozen to files (e.g. to hand-edit them or ship them
    as assets loaded by ``AssetIconProvider``).
    """
    directory.mkdir(parents=True, exist_ok=True)
    provider = CodeIconProvider()
    for slug in SLUGS:
        for size in sizes:
            provider.render(slug, size).save(directory / f"{slug}@{size}.png")
