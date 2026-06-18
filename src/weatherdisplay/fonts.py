"""Pixel-font theme: two swappable slots and named roles.

The renderer never names a font file — it asks for a logical *role* (e.g.
``"temp-hero"``) and gets a cached Pillow font sized for the layout. Every role
resolves to one of just two *slots*, ``"title"`` and ``"body"`` (design theory:
one display face, one text face), so the whole look changes by swapping at most
two TTFs. Dev mode can override a slot at runtime with an uploaded font for
instant comparison (see ``set_override``).

The bundled default is Pixel Operator (CC0). It is a pixel font designed on a
16px grid, so sizes are kept to multiples of 16 to stay crisp.
"""

from __future__ import annotations

import functools
import pathlib
from typing import Literal

from PIL import ImageFont

type Slot = Literal["title", "body"]

_FONTS_DIR = pathlib.Path(__file__).resolve().parent / "static" / "fonts"

# Default TTF for each slot.
_DEFAULT_SLOT_FONTS: dict[Slot, pathlib.Path] = {
    "title": _FONTS_DIR / "PixelOperator-Bold.ttf",
    "body": _FONTS_DIR / "PixelOperator.ttf",
}

# Runtime overrides set by dev mode (slot -> TTF path); None uses the default.
_overrides: dict[Slot, pathlib.Path | None] = {"title": None, "body": None}
# Display name for an active override (e.g. the uploaded filename, which the
# on-disk temp path does not preserve).
_override_names: dict[Slot, str] = {"title": "", "body": ""}

# Logical role -> (slot, pixel size). Sizes are multiples of 16 (Pixel
# Operator's design grid) so the glyphs land on whole pixels.
_ROLES: dict[str, tuple[Slot, int]] = {
    "temp-hero": ("title", 96),  # the big current temperature
    "temp-unit": ("title", 32),  # its °C/°F unit
    "condition": ("title", 32),  # current-condition label
    "secondary": ("body", 32),  # the other-unit temperature
    "value": ("body", 32),  # stat values (humidity, UV, sun times)
    "chip-day": ("title", 16),  # weekday on a day chip
    "label": ("body", 16),  # stat labels, hour labels, chip temps
    "tiny": ("body", 16),  # updated text, precip %
}


@functools.cache
def _load(path: str, size: int) -> ImageFont.FreeTypeFont:
    """Loads (and caches) a TrueType font at ``size``."""
    return ImageFont.truetype(path, size)


def font(role: str) -> ImageFont.FreeTypeFont:
    """Returns the cached font for a layout ``role`` (see ``_ROLES``)."""
    slot, size = _ROLES[role]
    path = _overrides[slot] or _DEFAULT_SLOT_FONTS[slot]
    return _load(str(path), size)


def slots() -> tuple[Slot, ...]:
    """Returns the swappable slot names."""
    return ("title", "body")


def current_path(slot: Slot) -> pathlib.Path:
    """Returns the TTF path in use for ``slot`` (override or default)."""
    return _overrides[slot] or _DEFAULT_SLOT_FONTS[slot]


def current_name(slot: Slot) -> str:
    """Returns the display name of the font in use for ``slot``.

    For an override this is the name given to ``set_override`` (e.g. the
    original uploaded filename); otherwise the bundled font's filename.
    """
    if _overrides[slot] is not None:
        return _override_names[slot]
    return _DEFAULT_SLOT_FONTS[slot].name


def set_override(
    slot: Slot, path: pathlib.Path, name: str | None = None
) -> None:
    """Points ``slot`` at an arbitrary TTF (used by dev mode hot-swapping).

    ``name`` is the label shown for the override (defaults to the path's
    filename). Pass a fresh, unique ``path`` per swap: a font cached for an
    earlier path keeps that file open, so reusing the path and overwriting it
    can corrupt the still-cached font.
    """
    if slot not in _overrides:
        raise ValueError(
            f"unknown font slot {slot!r}; expected one of {slots()}"
        )
    _overrides[slot] = path
    _override_names[slot] = name or path.name


def clear_override(slot: Slot) -> None:
    """Restores ``slot`` to its bundled default font."""
    _overrides[slot] = None
    _override_names[slot] = ""


def is_valid(path: pathlib.Path) -> bool:
    """Reports whether ``path`` can be loaded as a TrueType font.

    Lets dev mode reject a bad upload before it becomes a slot override that
    would crash every later render.
    """
    try:
        ImageFont.truetype(str(path), 16)
    except OSError:
        return False
    return True
