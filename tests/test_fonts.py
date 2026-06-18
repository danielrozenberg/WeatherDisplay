"""Tests for the font theme and runtime slot overrides."""

from __future__ import annotations

from weatherdisplay import fonts
from weatherdisplay import render

_ROLES = (
    "temp-hero",
    "temp-unit",
    "condition",
    "secondary",
    "value",
    "chip-day",
    "label",
    "tiny",
)


def test_every_role_resolves() -> None:
    for role in _ROLES:
        assert fonts.font(role).size > 0


def test_slot_override_and_clear() -> None:
    other = render.static_dir() / "fonts" / "HomeVideo-Regular.ttf"
    default = fonts.current_path("title")
    assert other != default
    try:
        fonts.set_override("title", other)
        assert fonts.current_path("title") == other
        assert fonts.font("temp-hero").size > 0
    finally:
        fonts.clear_override("title")
    assert fonts.current_path("title") == default
